"""Value-free per-run Markdown reporting; never a source of readiness or state."""

from __future__ import annotations

import argparse
import os
import re
import sys
from collections import Counter
from dataclasses import dataclass
from html import escape
from pathlib import Path

DISCLAIMER = (
    "GitHub does not return secret values. A successful secret API write confirms "
    "acceptance, not a readback or content comparison. Secret values cannot be "
    "verified as unchanged."
)
COMPLETE = "<!-- configuration-report-complete -->"


def cell(value):
    text = (
        escape(str(value), quote=True)
        .replace("|", "&#124;")
        .replace("\n", " ")
        .replace("\r", " ")
        .replace("`", "&#96;")
    )
    for character in "\\*_[]":
        text = text.replace(character, f"&#{ord(character)};")
    return text


def run_link():
    run_id = os.environ.get("GITHUB_RUN_ID", "")
    if re.fullmatch(r"[0-9]+", run_id):
        return f"[Open run](https://github.com/alanlima/pawlocal/actions/runs/{run_id})"
    return "Unavailable outside GitHub Actions"


@dataclass
class Row:
    source: str
    target: str
    name: str
    secret: bool
    status: str = "Not attempted"
    reason: str = "Operation did not reach this destination."
    mutation: str = "none"
    diagnostic: str = ""


class Report:
    def __init__(self, environment, mode, selection, operation="reconcile"):
        # Only fixed choices are reportable, including on argument/setup failure.
        self.environment = (
            environment if environment in {"development", "production"} else "Unknown"
        )
        self.mode = mode if mode in {"audit", "enforce"} else "Unknown"
        self.selection = (
            selection
            if isinstance(selection, str)
            and re.fullmatch(r"[a-z][a-z0-9-]*-mapping[.]yaml", selection)
            else "invalid-mapping"
        )

        self.operation = (
            operation
            if operation in {"reconcile", "legacy-cleanup", "destroy-cleanup"}
            else "Unknown"
        )
        self.rows = {}
        self.inventory = False
        self.result = "FAILED"
        self.reason = "Setup or execution failed; no success is claimed."

    @staticmethod
    def path():
        value = os.environ.get("CONFIG_SUMMARY_PATH") or os.environ.get(
            "GITHUB_STEP_SUMMARY"
        )
        return Path(value) if value else None

    @classmethod
    def clear(cls):
        path = cls.path()
        if path:
            path.unlink(missing_ok=True)

    def inventory_for(self, mappings, selected):
        chosen = {(m.github_environment, m.env_name) for m in selected}
        self.rows = {
            (m.github_environment, m.env_name): Row(
                m.store_key,
                m.github_environment,
                m.env_name,
                m.secret,
                "Not attempted"
                if (m.github_environment, m.env_name) in chosen
                else "Not selected",
                "No destination write started."
                if (m.github_environment, m.env_name) in chosen
                else "Outside the selected environment/manifest; no read/write.",
            )
            for m in mappings
        }
        self.inventory = True

    def cleanup_inventory(self, targets):
        self.rows = {
            (target, name): Row("", target, name, kind == "secrets")
            for target, kind, name in targets
        }
        self.inventory = True

    def row(self, mapping):
        return self.rows[(mapping.github_environment, mapping.env_name)]

    def progress(self, mapping, stage):
        self.row(mapping).mutation = stage

    def failure(self, mapping, reason):
        row = self.row(mapping)
        row.status, row.reason = "Failed", reason

    def succeeded(self):
        self.result = "SUCCESS"
        if self.operation != "reconcile":
            self.reason = (
                "Exact cleanup completed; mapped entries were not synchronized."
            )
        elif any(row.diagnostic for row in self.rows.values()):
            if any(row.diagnostic for row in self.rows.values()):
                self.result = "SUCCESS WITH WARNINGS"
            self.reason = "Reconciliation completed with warnings; skipped sources/targets do not establish release readiness."
        else:
            self.reason = "Selected YAML mappings verified; publication still requires its consumer checks and existing apply/promotion gates."

    def render(self):
        lines = [
            "# Configuration reconciliation",
            "",
            f"> **Secrets:** {DISCLAIMER}",
            "",
            "No source/destination values or error payloads are included.",
            "",
            "| Environment | Mode | Mapping manifest | Operation | Overall result | Run |",
            "|---|---|---|---|---|---|",
            f"| {cell(self.environment)} | {cell(self.mode)} | {cell(self.selection)} | {cell(self.operation)} | **{self.result}** | {run_link()} |",
            "",
            self.reason,
            "",
        ]
        if not self.inventory:
            return "\n".join(
                lines
                + [
                    "**INCOMPLETE: mapping/target inventory unavailable. No destination outcomes can be inferred.**",
                    "",
                ]
            )
        counts = Counter(row.status for row in self.rows.values())
        cleanup = self.operation != "reconcile"
        statuses = (
            ["Deleted", "Already absent", "Failed", "Not attempted", "Not recorded"]
            if cleanup
            else [
                "Created",
                "Updated",
                "Unchanged",
                "Secret write accepted",
                "Missing source",
                "Invalid source",
                "Missing target",
                "Missing required source",
                "Missing optional source",
                "Failed",
                "Not attempted",
                "Not selected",
                "Not recorded",
            ]
        )
        lines += [
            "| " + " | ".join(statuses) + " |",
            "|" + "---|" * len(statuses),
            "| " + " | ".join(str(counts[s]) for s in statuses) + " |",
            "",
            f"{len(self.rows)} expanded {'cleanup targets' if cleanup else 'mapping destinations'} accounted for. Counts describe destination outcomes.",
        ]
        diagnostics = Counter(
            row.diagnostic for row in self.rows.values() if row.diagnostic
        )
        if diagnostics:
            lines += [
                "",
                "Source diagnostics (not additional destination outcomes): "
                + "; ".join(
                    f"{cell(name)}: {count}" for name, count in diagnostics.items()
                )
                + ".",
            ]
        changed = {}
        for row in self.rows.values():
            if row.mutation != "none":
                totals = changed.setdefault(row.target, Counter())
                totals[row.status if row.mutation == "verified" else row.mutation] += 1
                if row.status in {"Created", "Updated"}:
                    totals["verified-total"] += 1
        lines += ["", "## GitHub Environment changes", ""]
        if not changed:
            lines.append("None. No destination mutations were recorded.")
        else:
            labels = (
                [
                    "Deleted",
                    "Accepted deletion, absence unverified",
                    "Possible deletion, acceptance unknown",
                ]
                if cleanup
                else [
                    "Created",
                    "Updated",
                    "Verified variable changes",
                    "Secret writes accepted (content change unverified)",
                    "Accepted mutation, verification incomplete",
                    "Possible changes, acceptance unknown",
                ]
            )
            keys = (
                ["Deleted", "accepted", "possible"]
                if cleanup
                else [
                    "Created",
                    "Updated",
                    "verified-total",
                    "secret-accepted",
                    "accepted",
                    "possible",
                ]
            )
            lines += [
                "| Environment | " + " | ".join(labels) + " |",
                "|" + "---|" * (len(labels) + 1),
            ]
            for target, totals in sorted(changed.items()):
                lines.append(
                    f"| {cell(target)} | "
                    + " | ".join(str(totals[key]) for key in keys)
                    + " |"
                )
        lines += [
            "",
            "Completed writes are not rolled back. Accepted or possible changes are not a verified no-op.",
            "",
            "## Exact cleanup targets" if cleanup else "## Full mapping",
            "",
        ]
        for target in sorted({r.target for r in self.rows.values()}):
            group = sorted(
                (r for r in self.rows.values() if r.target == target),
                key=lambda r: (r.source, r.name),
            )
            lines += [
                "<details>",
                f"<summary>{cell(target)} - {len(group)} destinations</summary>",
                "",
            ]
            if cleanup:
                lines += [
                    "| Target Environment | Exact target name | Type | Result | Safe reason |",
                    "|---|---|---|---|---|",
                ]
            else:
                lines += [
                    "| Parameter Store key | Source environment | Target GitHub Environment | Target name | Type | Result | Safe reason |",
                    "|---|---|---|---|---|---|---|",
                ]
            for row in group:
                reason = row.reason
                if row.mutation == "accepted":
                    reason += " Write accepted; verification incomplete."
                elif row.mutation == "possible":
                    reason += " Write acceptance unknown; changes may have occurred."
                prefix = [] if cleanup else [row.source, row.source.split("/")[2]]
                kind = "Secret" if row.secret else "Variable"
                if not cleanup:
                    kind += " / SecureString" if row.secret else " / String"
                lines.append(
                    "| "
                    + " | ".join(
                        cell(c)
                        for c in prefix
                        + [row.target, row.name, kind, row.status, reason]
                    )
                    + " |"
                )
            lines += ["", "</details>", ""]
        lines += [
            "A cancellation or runner loss may prevent a final report. Incomplete reports show only recorded outcomes; missing records never prove no writes occurred.",
            "",
        ]
        return "\n".join(lines)

    def write(self):
        path = self.path()
        if path:
            # Replace one value-free Markdown document; never leave stale success.
            self.clear()
            temporary = path.with_name(path.name + ".tmp")
            try:
                temporary.write_bytes((self.render() + COMPLETE + "\n").encode("utf-8"))
                temporary.replace(path)
                if os.environ.get("GITHUB_OUTPUT"):
                    with open(
                        os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8"
                    ) as output:
                        output.write("summary_written=true\n")
            finally:
                temporary.unlink(missing_ok=True)


def publish():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--environment", required=True)
    parser.add_argument("--mode", required=True)
    parser.add_argument("--operation", default="reconcile")
    args = parser.parse_args()
    try:
        private_path = os.environ.get("CONFIG_SUMMARY_PATH", "")
        content = (
            Path(private_path).read_text(encoding="utf-8")
            if private_path and Path(private_path).is_file()
            else ""
        )
        outcome = os.environ.get(
            "SYNC_OUTCOME" if args.operation == "reconcile" else "CLEANUP_OUTCOME", ""
        )
        if not content.endswith(COMPLETE + "\n") or (
            outcome != "success" and os.environ.get("REPORT_WRITTEN") != "true"
        ):
            report = Report(
                args.environment, args.mode, "parameter-mapping.yaml", args.operation
            )
            report.result = "INCOMPLETE"
            report.reason = "Operation report unavailable: setup failed or execution was interrupted. No readiness is claimed."
            try:
                if args.operation in {"reconcile", "legacy-cleanup", "destroy-cleanup"}:
                    from reconcile import inventory_mappings

                    all_mappings = inventory_mappings(
                        "development"
                    ) + inventory_mappings("production")
                    current = inventory_mappings(args.environment)
                    if args.operation == "reconcile":
                        report.inventory_for(all_mappings, current)
                    else:
                        from cleanup import cleanup_targets

                        report.cleanup_inventory(
                            cleanup_targets(current, args.environment, args.operation)
                        )
                    outcome = (
                        "SYNC_OUTCOME"
                        if args.operation == "reconcile"
                        else "CLEANUP_OUTCOME"
                    )
                    started = os.environ.get(outcome) not in {"skipped", ""}
                    for row in report.rows.values():
                        if row.status != "Not selected":
                            row.status = "Not recorded" if started else "Not attempted"
                            row.reason = (
                                "Execution interrupted; read/write outcomes unavailable."
                                if started
                                else "Operation step did not start."
                            )
                            row.mutation = "possible" if started else "none"
            except Exception as error:  # noqa: BLE001 - preserve incomplete report and operational context
                print(
                    f"Cannot build configuration summary inventory: {type(error).__name__}: {error}",
                    file=sys.stderr,
                )
                report.inventory = False
            content = report.render()
        if os.environ.get("JOB_STATUS") == "cancelled":
            content = re.sub(
                r"\*\*(?:SUCCESS(?: WITH WARNINGS)?|FAILED)\*\*",
                "**INCOMPLETE**",
                content,
                count=1,
            )
            content += (
                "\n**Job cancelled: publication is not authorized by this report.**\n"
            )
        with open(
            os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8", newline="\n"
        ) as output:
            output.write(content)
    except Exception as error:  # noqa: BLE001 - keep standard operational errors
        print(
            f"Cannot publish configuration summary: {type(error).__name__}: {error}",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(publish())
