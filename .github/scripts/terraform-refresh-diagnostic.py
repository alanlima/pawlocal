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


def policy_summary(value: Any) -> str:
    """Summarize policy shape and fingerprint without printing policy contents."""
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
        return (
            f"sha256={digest}; statements={len(statements)}; allow={allow_count}; deny={deny_count}; "
            f"wildcard_resource_statements={wildcard_resources}; principals={principal_count}; "
            f"conditioned_statements={condition_count}"
        )
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
        output.append((safe_resource_label(item.get("address")), safe_actions(actions), paths, policy_detail))
    return output


def print_section(title: str, rows: list[tuple[str, str, list[str], str | None]]) -> None:
    print(f"### {title}")
    if not rows:
        print("No managed resource changes.")
        print()
        return
    print("| Resource label | Actions | Changed attribute paths | Sanitized policy summary |")
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
