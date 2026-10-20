#!/usr/bin/env python3
"""Print safe drift/configuration summaries from Terraform plan JSON files."""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any


SAFE_ACTIONS = {"create", "read", "update", "delete", "forget", "import", "no-op"}
SAFE_LABEL = re.compile(r"[A-Za-z0-9_.\[\]*-]+")
SAFE_ATTRIBUTE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def read_plan(path: str) -> dict[str, Any]:
    with Path(path).open(encoding="utf-8") as source:
        value = json.load(source)
    if not isinstance(value, dict):
        raise ValueError("Terraform plan JSON must be an object")
    return value


def safe_resource_label(address: Any) -> str:
    if not isinstance(address, str):
        return "<unlisted resource>"
    label = re.sub(r"\[[^\]]*\]", "[*]", address)
    return label if SAFE_LABEL.fullmatch(label) else "<unlisted resource>"


def safe_actions(actions: Any) -> str:
    if not isinstance(actions, list):
        return "<unknown>"
    return ",".join(action if action in SAFE_ACTIONS else "<other>" for action in actions)


def changed_top_level_paths(before: Any, after: Any) -> list[str]:
    old = before if isinstance(before, dict) else {}
    new = after if isinstance(after, dict) else {}
    paths = []
    for key in sorted(set(old) | set(new), key=str):
        if old.get(key) == new.get(key):
            continue
        safe_key = key if isinstance(key, str) and SAFE_ATTRIBUTE.fullmatch(key) else "<other>"
        paths.append(f"$.{safe_key}")
    return paths


def _contains_wildcard_resource(value: Any) -> bool:
    if isinstance(value, str):
        return value == "*" or "*" in value
    if isinstance(value, list):
        return any(_contains_wildcard_resource(item) for item in value)
    return False


def _as_sequence(value: Any) -> list[Any]:
    return value if isinstance(value, list) else [value]


def _service_names(statements: list[dict[str, Any]]) -> list[str]:
    services = set()
    for statement in statements:
        for action in _as_sequence(statement.get("Action", [])):
            if isinstance(action, str) and ":" in action:
                service = action.split(":", 1)[0]
                if re.fullmatch(r"[a-z0-9-]{1,32}", service):
                    services.add(service)
    return sorted(services)


def _action_classes(statements: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    classes: dict[str, dict[str, int]] = {}
    for statement in statements:
        effect = statement.get("Effect")
        if effect not in {"Allow", "Deny"}:
            continue
        counts = classes.setdefault(effect.lower(), {})
        for action in _as_sequence(statement.get("Action", [])):
            if not isinstance(action, str) or ":" not in action:
                category = "other"
            else:
                verb = action.split(":", 1)[1].split("*", 1)[0]
                if action.endswith(":*") or action == "*":
                    category = "wildcard"
                elif re.match(r"^(Get|Describe|List|Head|Read|Lookup|Search|Check|View)", verb, re.IGNORECASE):
                    category = "read"
                elif re.match(r"^(Delete|Remove|Revoke|Purge|Destroy)", verb, re.IGNORECASE):
                    category = "delete"
                elif re.match(r"^(Put|Create|Update|Modify|Tag|Untag|Set|Associate|Attach|Detach|Import|Upload|Restore|Enable|Disable|Start|Stop)", verb, re.IGNORECASE):
                    category = "write"
                else:
                    category = "other"
            counts[category] = counts.get(category, 0) + 1
    return classes


def _resource_categories(statements: list[dict[str, Any]]) -> dict[str, int]:
    categories = {"wildcard": 0, "s3": 0, "iam": 0, "cloudfront": 0, "dsql": 0, "route53": 0, "lightsail": 0, "other_arn": 0, "other": 0}
    for statement in statements:
        for resource in _as_sequence(statement.get("Resource", [])):
            if not isinstance(resource, str):
                categories["other"] += 1
            elif resource == "*":
                categories["wildcard"] += 1
            elif resource.startswith("arn:"):
                category = next((name for name in ("s3", "iam", "cloudfront", "dsql", "route53", "lightsail") if f":{name}:" in resource), "other_arn")
                categories[category] += 1
            else:
                categories["other"] += 1
    return {name: count for name, count in categories.items() if count}


def policy_summary(value: Any) -> str:
    """Summarize policy structure and fingerprint without printing policy values."""
    if value is None:
        return "absent"
    try:
        policy = json.loads(value) if isinstance(value, str) else value
        if not isinstance(policy, dict):
            return "unavailable"
        statements = policy.get("Statement", [])
        if isinstance(statements, dict):
            statements = [statements]
        if not isinstance(statements, list) or any(not isinstance(item, dict) for item in statements):
            return "unavailable"
        canonical = json.dumps(policy, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        allow_count = sum(item.get("Effect") == "Allow" for item in statements)
        deny_count = sum(item.get("Effect") == "Deny" for item in statements)
        wildcard_resources = sum(_contains_wildcard_resource(item.get("Resource")) for item in statements)
        principal_count = sum("Principal" in item for item in statements)
        condition_count = sum(isinstance(item.get("Condition"), dict) for item in statements)
        actions_count = sum(len(_as_sequence(item.get("Action", []))) for item in statements)
        resources_count = sum(len(_as_sequence(item.get("Resource", []))) for item in statements)
        principal_types = sorted({
            key
            for item in statements
            for key in (item.get("Principal", {}) if isinstance(item.get("Principal"), dict) else {})
            if key in {"AWS", "Service", "Federated", "CanonicalUser"}
        })
        condition_operators = sorted({
            operator
            for item in statements
            for operator in (item.get("Condition", {}) if isinstance(item.get("Condition"), dict) else {})
            if isinstance(operator, str) and re.fullmatch(r"[A-Za-z0-9]+", operator)
        })
        return (
            f"sha256={digest}; statements={len(statements)}; allow={allow_count}; deny={deny_count}; "
            f"actions={actions_count}; action_services={','.join(_service_names(statements)) or 'none'}; "
            f"action_effect_classes={json.dumps(_action_classes(statements), sort_keys=True)}; "
            f"resources={resources_count}; resource_categories={json.dumps(_resource_categories(statements), sort_keys=True)}; "
            f"wildcard_resource_statements={wildcard_resources}; principals={principal_count}; "
            f"principal_types={','.join(principal_types) or 'none'}; conditioned_statements={condition_count}; "
            f"condition_operators={','.join(condition_operators) or 'none'}"
        )
    except (TypeError, ValueError, json.JSONDecodeError):
        return "unavailable"


def encryption_summary(value: Any) -> str:
    """Show only approved enum fields and a fingerprint, never arbitrary values."""
    if value is None:
        return "absent"
    try:
        details = json.loads(value) if isinstance(value, str) else value
        if not isinstance(details, dict):
            return "unavailable"
        canonical = json.dumps(details, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        output = [f"sha256={digest}"]
        safe_enums = {
            "encryption_status": {"ENABLED", "DISABLED"},
            "encryption_type": {"AWS_OWNED_KMS_KEY", "CUSTOMER_MANAGED_KMS_KEY"},
        }
        for key in ("encryption_status", "encryption_type"):
            candidate = details.get(key)
            if candidate is None:
                output.append(f"{key}=absent")
            elif isinstance(candidate, str) and candidate.upper() in safe_enums[key]:
                output.append(f"{key}={candidate.upper()}")
            else:
                output.append(f"{key}=present")
        output.append(f"fields={','.join(sorted(key for key in details if key in {'encryption_status', 'encryption_type'})) or 'none'}")
        return "; ".join(output)
    except (TypeError, ValueError, json.JSONDecodeError):
        return "unavailable"


def summarize_plan(plan: dict[str, Any], label: str) -> list[tuple[str, str, list[str], str | None]]:
    output = []
    for item in plan.get("resource_changes", []):
        if not isinstance(item, dict):
            continue
        change = item.get("change", {})
        if not isinstance(change, dict):
            continue
        actions = change.get("actions", [])
        if not isinstance(actions, list) or actions == ["no-op"] or not actions:
            continue
        if item.get("mode") == "data" and actions == ["read"]:
            continue
        before = change.get("before")
        after = change.get("after")
        paths = changed_top_level_paths(before, after)
        policy_detail = None
        if "$.policy" in paths:
            old_policy = before.get("policy") if isinstance(before, dict) else None
            new_policy = after.get("policy") if isinstance(after, dict) else None
            policy_detail = f"before[{policy_summary(old_policy)}]; after[{policy_summary(new_policy)}]"
        elif "$.encryption_details" in paths:
            old_details = before.get("encryption_details") if isinstance(before, dict) else None
            new_details = after.get("encryption_details") if isinstance(after, dict) else None
            policy_detail = f"before[{encryption_summary(old_details)}]; after[{encryption_summary(new_details)}]"
        output.append((safe_resource_label(item.get("address")), safe_actions(actions), paths, policy_detail))
    return output


def print_section(title: str, rows: list[tuple[str, str, list[str], str | None]]) -> None:
    print(f"### {title}")
    if not rows:
        print("No managed resource changes.")
        print()
        return
    print("| Resource label | Actions | Changed attribute paths | Sanitized before/after summary |")
    print("|---|---|---|---|")
    for label, actions, paths, policy in rows:
        path_text = ", ".join(paths) if paths else "<none>"
        policy_text = policy or "<not a policy change>"
        print(f"| `{label}` | `{actions}` | `{path_text}` | `{policy_text}` |")
    print()


def main() -> int:
    if len(sys.argv) != 3:
        print("Usage: terraform-refresh-diagnostic.py REFRESH_ONLY_PLAN_JSON NORMAL_PLAN_JSON", file=sys.stderr)
        return 2
    try:
        refresh_plan = read_plan(sys.argv[1])
        normal_plan = read_plan(sys.argv[2])
    except (OSError, json.JSONDecodeError, ValueError):
        print("Terraform plan JSON unavailable; detailed values were withheld.", file=sys.stderr)
        return 1

    print("## Destroy-preparation refresh and configuration diagnostic")
    print("Refresh-only planning is read-only; no plan is applied and Terraform state is not written.")
    print("The normal plan is evaluated separately after refresh; the existing strict preparation gate remains authoritative.")
    print()
    print_section("Refresh-only state reconciliation candidates", summarize_plan(refresh_plan, "refresh-only"))
    print_section("Normal plan changes after refresh", summarize_plan(normal_plan, "normal"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
