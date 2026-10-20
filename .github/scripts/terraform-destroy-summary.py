#!/usr/bin/env python3
"""Print a value-free inventory for a saved Terraform destroy plan."""

import json
import pathlib
import re
import sys


plan_path = pathlib.Path(sys.argv[1])
with plan_path.open(encoding="utf-8") as source:
    plan = json.load(source)

safe_address_pattern = re.compile(
    r"^(?:module\.fullstack\.)?[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_]*"
    r"(?:\[(?:0|\"(?:development|production)\")\])?$"
)
safe_actions = {"create", "read", "update", "delete", "forget", "import", "no-op"}
totals = {"create": 0, "update": 0, "delete": 0, "replace": 0, "forget": 0, "other": 0}
changes = []

for item in plan.get("resource_changes", []):
    raw_actions = item.get("change", {}).get("actions", [])
    if raw_actions == ["no-op"] or not raw_actions:
        continue
    actions = [action if action in safe_actions else "<other>" for action in raw_actions]
    if actions in (["delete", "create"], ["create", "delete"]):
        totals["replace"] += 1
    elif len(actions) == 1 and actions[0] in totals:
        totals[actions[0]] += 1
    else:
        totals["other"] += 1
    address = item.get("address", "")
    label = address if isinstance(address, str) and safe_address_pattern.fullmatch(address) else "<unlisted resource>"
    changes.append((label, ",".join(actions)))

print("## Terraform full-destroy plan inventory")
print()
print("Resource values, policy documents, account identifiers, and physical IDs are omitted.")
print()
print(
    "Actions: "
    + " · ".join(
        f"{name.title()} {totals[name]}"
        for name in ("create", "update", "delete", "replace", "forget", "other")
    )
)
print()
if changes:
    print("| Resource address | Planned action |")
    print("|---|---|")
    for address, actions in sorted(changes):
        print(f"| `{address}` | `{actions}` |")
else:
    print("No resource changes in the saved plan.")
