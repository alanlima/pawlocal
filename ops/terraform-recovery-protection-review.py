"""Sanitize the separate Terraform plan that disables legacy DSQL deletion protection."""

from __future__ import annotations

import json
import importlib.util
from pathlib import Path
import sys
from typing import Any

EXPECTED = {
    'module.fullstack.aws_dsql_cluster.app["development"]',
    'module.fullstack.aws_dsql_cluster.app["production"]',
}
_SPEC = importlib.util.spec_from_file_location(
    "terraform_recovery_inventory", Path(__file__).with_name("terraform-recovery-plan-review.py")
)
assert _SPEC and _SPEC.loader
_INVENTORY = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_INVENTORY)


def render(plan: dict[str, Any]) -> str:
    if not isinstance(plan.get("format_version"), str) or not isinstance(plan.get("resource_changes"), list):
        raise ValueError("Input is not a Terraform plan JSON document")
    if plan.get("applyable") is not True or plan.get("complete") is not True or plan.get("errored") is not False:
        raise ValueError("DSQL protection plan must be complete, applyable, and error-free")
    if plan.get("deferred_changes") or plan.get("output_changes"):
        raise ValueError("DSQL protection plan contains deferred or output changes")

    found: set[str] = set()
    for item in plan["resource_changes"]:
        address = item.get("address")
        mode = item.get("mode", "managed")
        change = item.get("change", {})
        actions = change.get("actions") if isinstance(change, dict) else None
        if mode == "data" and address in _INVENTORY.ALLOWED_DATA and actions in (["read"], ["no-op"]):
            continue
        if mode == "managed" and address in _INVENTORY.ALLOWED_MANAGED and actions == ["no-op"]:
            continue
        if address not in EXPECTED or item.get("type") != "aws_dsql_cluster" or mode != "managed":
            raise ValueError("DSQL protection plan contains an unsupported managed address")
        if address in found or actions != ["update"]:
            raise ValueError("Each DSQL cluster must have exactly one direct update")
        before = change.get("before")
        after = change.get("after")
        if not isinstance(before, dict) or not isinstance(after, dict):
            raise ValueError("DSQL protection update is missing prior or proposed values")
        if before.get("deletion_protection_enabled") is not True or after.get("deletion_protection_enabled") is not False:
            raise ValueError("DSQL protection plan must change only enabled to disabled")
        found.add(address)
    if found != EXPECTED:
        raise ValueError("DSQL protection plan must include exactly the development and production clusters")
    return "\n".join([
        "### Legacy DSQL deletion-protection stage",
        "",
        "The exact saved Terraform plan changes deletion protection from enabled to disabled on these two clusters:",
        "",
        *(f"- `{address}`" for address in sorted(found)),
        "",
        "No other managed resource action, output change, or deferred change is accepted. Attribute values are omitted.",
    ])


def main() -> None:
    try:
        print(render(json.load(sys.stdin)))
    except (json.JSONDecodeError, ValueError) as exc:
        print(f"DSQL protection plan review rejected: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
