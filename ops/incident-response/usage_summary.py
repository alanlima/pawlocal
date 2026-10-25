"""Read numeric trusted snapshots and append human-readable Actions summaries.

Reporting is advisory: these outputs are never admission or publication evidence.
"""

import argparse
import json
import os
import re
from pathlib import Path

from quota import Denied, integer, strict_json
from enforcement import evidence

PROFILE_FIELDS = ("model", "effort", "service_tier")
LIMIT_FIELDS = ("requests_per_role", "input_per_request", "output_per_request", "input_per_role", "output_per_role", "input_rate", "output_rate", "monthly_runs", "monthly_microdollars")


def read_json(path):
    try:
        with Path(path).open("rb") as source:
            raw = source.read(65537)
        return strict_json(raw) if len(raw) <= 65536 else None
    except (OSError, ValueError, UnicodeError, RecursionError):
        return None


def validated_report(value):
    try:
        if not isinstance(value, dict) or set(value) != {"version", "requests", "failures", "exhaustions"} or type(value["version"]) is not int or value["version"] != 1:
            return None
        integer(value["failures"], 0)
        integer(value["exhaustions"], 0)
        if not isinstance(value["requests"], list) or len(value["requests"]) > 64:
            return None
        clean = []
        for item in value["requests"]:
            if not isinstance(item, dict) or set(item) != {"counted_input", "output_cap", "actual"}:
                return None
            integer(item["counted_input"], 0)
            integer(item["output_cap"])
            actual = item["actual"]
            if actual is not None:
                if not isinstance(actual, dict) or set(actual) != {"input_tokens", "output_tokens", "total_tokens", "cached_tokens", "reasoning_tokens", "output_limit_reached"}:
                    return None
                for key, number in actual.items():
                    if number is None and key in {"cached_tokens", "reasoning_tokens"}:
                        continue
                    integer(number, 0)
                if actual["total_tokens"] != actual["input_tokens"] + actual["output_tokens"]:
                    return None
                if any(actual[key] is not None and actual[key] > actual[ceiling] for key, ceiling in (("cached_tokens", "input_tokens"), ("reasoning_tokens", "output_tokens"))):
                    return None
            clean.append({"counted_input": item["counted_input"], "output_cap": item["output_cap"], "actual": actual})
        return {"version": 1, "requests": clean, "failures": value["failures"], "exhaustions": value["exhaustions"]}
    except (Denied, TypeError):
        return None


def parse_env(name):
    try:
        return strict_json(os.environ.get(name, ""))
    except (Denied, RecursionError):
        return None


def limits_from_profile(path):
    try:
        raw = read_json(path)
        if raw is None:
            return None
        # Report historical accepted profiles even if expiry passed during work.
        return validate_limits({name: raw[name] for name in LIMIT_FIELDS + PROFILE_FIELDS})
    except (KeyError, Denied, TypeError):
        return None


def validate_limits(value):
    try:
        if not isinstance(value, dict) or set(value) != set(LIMIT_FIELDS + PROFILE_FIELDS):
            return None
        if not isinstance(value["model"], str) or not re.fullmatch(r"[A-Za-z0-9_.:/-]{1,160}", value["model"]):
            return None
        if value["effort"] not in {"minimal", "low", "medium", "high", "xhigh"} or value["service_tier"] != "default":
            return None
        return {key: None if key == "monthly_microdollars" and value[key] is None else integer(value[key]) for key in LIMIT_FIELDS} | {key: value[key] for key in PROFILE_FIELDS}
    except (Denied, TypeError):
        return None


def amount(used, limit):
    if used is None:
        return "unknown / " + (f"{limit:,}" if limit else "unknown limit")
    return f"{used:,} / {limit:,} ({100 * used / limit:.1f}%; {max(0, limit - used):,} headroom)" if limit else f"{used:,} / unknown limit"


def money(tokens_in, tokens_out, limits):
    if limits is None:
        return "unknown"
    micro = (tokens_in * limits["input_rate"] + tokens_out * limits["output_rate"] + 999999) // 1000000
    return f"${micro / 1000000:.6f}"


def render(reports, limits, states=None, admitted=None, preview=False):
    lines = ["## Incident responder token usage", "", "Provider usage is observed usage. Charged allocation includes the full output allowance; neither report refunds quota. Costs use approved worst-case rates, ignore cache discounts, and are estimates, not invoices.", ""]
    if limits:
        monthly_spending = "Unlimited" if limits["monthly_microdollars"] is None else f"${limits['monthly_microdollars'] / 1000000:.6f}"
        monthly_audit = (
            "Reservations remain recorded for audit; no monthly spending ceiling is enforced."
            if limits["monthly_microdollars"] is None
            else "Remaining monthly balance requires the protected ledger; these observations do not settle it."
        )
        lines += [f"Model `{limits['model']}`; reasoning `{limits['effort']}`; service tier `{limits['service_tier']}`.", ""]
    if admitted is False:
        lines += ["**No model admission recorded.** Inspect preflight output for disabled configuration, a no-op, or admission failure. Missing observations are not zero usage.", ""]
    if preview:
        if limits:
            lines += [f"Configured full incident token ceiling: {2 * (limits['input_per_role'] + limits['output_per_role']):,} across fixer and reviewer.", f"Monthly spending ceiling {monthly_spending}; monthly run limit {limits['monthly_runs']:,}.", f"Monthly reservation per admitted incident: {money(2 * limits['input_per_role'], 2 * limits['output_per_role'], limits)}. Per execution: {limits['requests_per_role']:,} requests; {limits['input_per_role']:,} input and {limits['output_per_role']:,} output tokens."]
        else:
            lines += ["Configured limits unavailable; inspect admission output. No usage measurement is available at preflight."]
        lines += ["", "This is an admission preview. Final usage and job outcomes appear in Record incident outcome after the execution jobs finish."]
        return "\n".join(lines) + "\n"
    table_start = len(lines)
    lines += ["| Execution | Requests charged / limit | Provider input | Provider output | Cached input* | Reasoning output* | Unknown requests |", "| --- | --- | --- | --- | --- | --- | --- |"]
    total_in = total_out = charged_in = charged_out = unknown = 0
    complete = True
    known_requests = 0
    available_reports = 0
    insights = []
    request_tables = []
    for role, report in reports.items():
        state = (states or {}).get(role, "unknown")
        state = state if state in {"success", "failure", "cancelled", "skipped"} else "unknown"
        role_label = role + (f" ({state})" if states else "")
        report = validated_report(report)
        if report is None:
            lines += [f"| {role} ({state}; report unavailable) | unknown | unknown | unknown | unknown | unknown | unknown |"]
            complete = False
            continue
        available_reports += 1
        calls = report["requests"]
        known = [call["actual"] for call in calls if call["actual"] is not None]
        known_requests += len(known)
        missing = len(calls) - len(known)
        ins = sum(item["input_tokens"] for item in known)
        outs = sum(item["output_tokens"] for item in known)
        def detail(name):
            return f"{sum(item[name] for item in known):,}" if len(known) == len(calls) and all(item[name] is not None for item in known) else "unknown/partial"
        input_limit = limits["input_per_role"] if limits else None
        output_limit = limits["output_per_role"] if limits else None
        insights += [f"{role} charged input: {amount(sum(call['counted_input'] for call in calls), input_limit)}; charged output: {amount(sum(call['output_cap'] for call in calls), output_limit)}."]
        if not calls:
            insights += [f"{role}: no inference requests charged by this gateway."]
        if calls:
            request_tables += ["", f"### {role} requests", "", "| Request | Counted input | Output allowance charged | Provider input | Provider output |", "| --- | --- | --- | --- | --- |"]
            for index, call in enumerate(calls, 1):
                actual = call["actual"]
                provider_input = f"{actual['input_tokens']:,}" if actual else "unknown"
                provider_output = f"{actual['output_tokens']:,}" if actual else "unknown"
                request_tables += [f"| {index} | {call['counted_input']:,} | {call['output_cap']:,} | {provider_input} | {provider_output} |"]
        calls_limit = limits["requests_per_role"] if limits else None
        lines += [f"| {role_label} | {amount(len(calls), calls_limit)} | {ins:,}{' observed' if missing else ''} | {outs:,}{' observed' if missing else ''} | {detail('cached_tokens')} | {detail('reasoning_tokens')} | {missing} |"]
        total_in += ins
        total_out += outs
        charged_in += sum(call["counted_input"] for call in calls)
        charged_out += sum(call["output_cap"] for call in calls)
        unknown += missing
        if report["failures"] or report["exhaustions"]:
            insights += [f"{role}: {report['failures']} gateway failures; {report['exhaustions']} quota denials. Inspect raw gateway diagnostics for the stage and exact bound."]
        hits = sum(item["output_limit_reached"] for item in known)
        if hits:
            insights += [f"{role}: {hits} responses ended at max_output_tokens; consider output allowance when tuning."]
    lines += ["", *insights]
    complete = complete and unknown == 0
    multiplier = 2 if len(reports) > 1 else 1
    ceiling = multiplier * (limits["input_per_role"] + limits["output_per_role"]) if limits else None
    label = "Overall" if multiplier == 2 else "Execution"
    actual_total = total_in + total_out if known_requests or complete else None
    charged_total = charged_in + charged_out if available_reports else None
    summary = ["", f"**{label} provider tokens {'used' if complete else 'observed (partial; total unknown)'}:** {amount(actual_total, ceiling)}.", f"**Charged request allocation{' observed (partial)' if not all(validated_report(r) is not None for r in reports.values()) else ''}:** {amount(charged_total, ceiling)}.", f"Provider usage estimate{' (partial)' if not complete else ''}: {money(total_in, total_out, limits) if actual_total is not None else 'unknown'}. Charged request upper estimate: {money(charged_in, charged_out, limits) if charged_total is not None else 'unknown'}.", "", "*Cached input is included in input; reasoning is included in output. Do not add them again."]
    lines[table_start:table_start] = summary + [""]
    if limits:
        cap = min(limits["output_per_request"], limits["output_per_role"] // limits["requests_per_role"])
        lines += ["", f"Per request: input cap {limits['input_per_request']:,}; configured output cap {limits['output_per_request']:,}; effective output allowance {cap:,}. Per execution: input {limits['input_per_role']:,}, output {limits['output_per_role']:,}, requests {limits['requests_per_role']:,}.", f"Monthly admission reserves both complete execution envelopes: {money(2 * limits['input_per_role'], 2 * limits['output_per_role'], limits)} per admitted run. Monthly ceiling {monthly_spending} and {limits['monthly_runs']:,} runs. {monthly_audit}"]
    if not complete:
        lines += ["", "Missing, interrupted or malformed usage stays unknown. Charged reservations remain consumed. Headroom shown against observed usage is provisional; use charged allocation and gateway denials to troubleshoot enforcement."]
    lines += request_tables
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("preflight", "fixer", "reviewer", "overall"))
    args = parser.parse_args()
    temporary = Path(os.environ["RUNNER_TEMP"])
    limits = None
    report = None
    if args.mode == "overall":
        limits = validate_limits(parse_env("USAGE_LIMITS"))
        reports = {role: parse_env(role.upper() + "_USAGE") for role in ("fixer", "reviewer")}
        text = render(reports, limits, {role: os.environ.get(role.upper() + "_RESULT") for role in reports}, os.environ.get("ADMITTED") == "true")
    elif args.mode == "preflight":
        limits = limits_from_profile(temporary / "oncall-admission/profile.json")
        text = render({"fixer": None, "reviewer": None}, limits, admitted=os.environ.get("ADMITTED") == "true", preview=True)
    else:
        root = temporary / "oncall-trusted"
        report = validated_report(read_json(root / "gateway-usage.json"))
        limits = limits_from_profile(root / "profile.json")
        text = render({args.mode: report}, limits)
    with Path(os.environ["GITHUB_STEP_SUMMARY"]).open("a", encoding="utf-8") as output:
        mode = evidence()
        output.write(
            "\nIncident enforcement: **"
            + ("enabled" if mode["enabled"] else "disabled")
            + "**.\n"
        )
        if not mode["enabled"]:
            output.write(
                "Disabled policy categories: "
                + ", ".join(mode["disabled_categories"])
                + ". Configured ceilings below are reference values; skipped checks are not passes.\n"
            )
        output.write(text)
    if "GITHUB_OUTPUT" in os.environ:
        with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as output:
            output.write("usage=" + json.dumps(report, separators=(",", ":")) + "\n")
            output.write("limits=" + json.dumps(limits, separators=(",", ":")) + "\n")


if __name__ == "__main__":
    main()
