#!/usr/bin/env python3
"""Small fail-closed checks for the standard production destroy workflow."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


PREPARATION_CHANGES = {
    "module.pawlocal.aws_s3_bucket.frontend": ("aws_s3_bucket", ["update"]),
    "module.pawlocal.aws_dsql_cluster.application": ("aws_dsql_cluster", ["update"]),
    "module.pawlocal.aws_iam_policy.frontend_teardown[0]": ("aws_iam_policy", ["create"]),
    "module.pawlocal.aws_iam_role_policy_attachment.frontend_teardown[0]": (
        "aws_iam_role_policy_attachment",
        ["create"],
    ),
}
PREPARATION_FIELDS = {
    "module.pawlocal.aws_s3_bucket.frontend": {"force_destroy"},
    "module.pawlocal.aws_dsql_cluster.application": {
        "deletion_protection_enabled",
        "force_destroy",
        "encryption_details",
    },
}


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SystemExit(f"Required lifecycle file is missing: {path.name}") from exc
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Lifecycle file is not valid JSON: {path.name}") from exc
    if not isinstance(value, dict):
        raise SystemExit("Lifecycle file must contain a JSON object")
    return value


def require_plan(plan: dict[str, Any], *, require_applyable: bool = True) -> None:
    if plan.get("complete") is not True or (require_applyable and plan.get("applyable") is not True):
        raise SystemExit("Terraform plan is not complete and applyable")
    if plan.get("errored") is not False or plan.get("deferred_changes"):
        raise SystemExit("Terraform plan contains an error or deferred change")
    if plan.get("variables", {}).get("teardown_enabled", {}).get("value") is not True:
        raise SystemExit("Terraform plan does not enable protected teardown mode")


def changed_fields(change: dict[str, Any]) -> set[str]:
    before = change.get("before") or {}
    after = change.get("after") or {}
    if not isinstance(before, dict) or not isinstance(after, dict):
        return {"<root>"}
    return {key for key in set(before) | set(after) if before.get(key) != after.get(key)}


def resource_values(plan: dict[str, Any], section: str) -> dict[str, dict[str, Any]]:
    values: dict[str, dict[str, Any]] = {}

    def visit(module: dict[str, Any]) -> None:
        for resource in module.get("resources", []):
            address = resource.get("address")
            if isinstance(address, str):
                values[address] = resource.get("values") or {}
        for child in module.get("child_modules", []):
            visit(child)

    root = plan.get(section, {}).get("root_module")
    if isinstance(root, dict):
        visit(root)
    return values


def validate_preparation(plan: dict[str, Any]) -> None:
    # A rerun after the protected preparation apply can legitimately be a
    # complete no-op plan. The planned configuration still has to prove that
    # every teardown control is active before the second approval is reached.
    require_plan(plan, require_applyable=False)
    observed: dict[str, tuple[str, list[str]]] = {}
    for item in plan.get("resource_changes", []):
        actions = item.get("change", {}).get("actions", [])
        if not actions or actions == ["no-op"] or (item.get("mode") == "data" and actions == ["read"]):
            continue
        address = item.get("address", "")
        observed[address] = (item.get("type", ""), actions)
        if address not in PREPARATION_CHANGES or observed[address] != PREPARATION_CHANGES[address]:
            raise SystemExit("Preparation plan contains a change outside the teardown controls")
        allowed = PREPARATION_FIELDS.get(address)
        if allowed is not None:
            changed = changed_fields(item.get("change", {}))
            if not changed or not changed <= allowed:
                raise SystemExit("Preparation plan changes an attribute outside teardown controls")

    planned = resource_values(plan, "planned_values")
    if not PREPARATION_CHANGES.keys() <= planned.keys():
        raise SystemExit("Preparation plan does not produce every teardown control")
    bucket = planned["module.pawlocal.aws_s3_bucket.frontend"]
    database = planned["module.pawlocal.aws_dsql_cluster.application"]
    if bucket.get("force_destroy") is not True:
        raise SystemExit("Preparation plan does not enable frontend bucket cleanup")
    if database.get("force_destroy") is not True or database.get("deletion_protection_enabled") is not False:
        raise SystemExit("Preparation plan does not enable database deletion")


def prior_managed_addresses(plan: dict[str, Any]) -> set[str]:
    addresses: set[str] = set()

    def visit(module: dict[str, Any]) -> None:
        for resource in module.get("resources", []):
            if resource.get("mode", "managed") == "managed" and resource.get("address"):
                addresses.add(resource["address"])
        for child in module.get("child_modules", []):
            visit(child)

    root = plan.get("prior_state", {}).get("values", {}).get("root_module")
    if isinstance(root, dict):
        visit(root)
    return addresses


def validate_destroy(plan: dict[str, Any]) -> None:
    require_plan(plan)
    deleted: set[str] = set()
    for item in plan.get("resource_changes", []):
        actions = item.get("change", {}).get("actions", [])
        if not actions or actions == ["no-op"] or (item.get("mode") == "data" and actions == ["read"]):
            continue
        if actions != ["delete"]:
            raise SystemExit("Destroy plan contains a non-delete managed-resource action")
        address = item.get("address")
        if not isinstance(address, str) or not address.startswith("module.pawlocal."):
            raise SystemExit("Destroy plan contains a resource outside the production application module")
        deleted.add(address)
    prior = prior_managed_addresses(plan)
    if not prior or deleted != prior:
        raise SystemExit("Destroy plan does not delete every managed resource in the production state")


def state_status(path: Path) -> str:
    state = load_json(path)
    resources = state.get("resources")
    outputs = state.get("outputs", {})
    if not isinstance(resources, list) or not isinstance(outputs, dict):
        raise SystemExit("Terraform state resource or output inventory is invalid")
    return "empty" if not resources and not outputs else "nonempty"


def verify_empty(path: Path) -> None:
    if state_status(path) != "empty":
        raise SystemExit("Post-destroy Terraform state is not empty")
    print("Production application state is present and empty.")


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in ("validate-preparation", "validate-destroy", "state-status", "verify-empty-state"):
        subparsers.add_parser(name).add_argument("path", type=Path)
    args = parser.parse_args()
    if args.command == "validate-preparation":
        validate_preparation(load_json(args.path))
    elif args.command == "validate-destroy":
        validate_destroy(load_json(args.path))
    elif args.command == "state-status":
        print(state_status(args.path))
    else:
        verify_empty(args.path)


if __name__ == "__main__":
    main()
