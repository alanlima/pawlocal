#!/usr/bin/env python3
"""Fail closed unless a Terraform plan contains only safe changes for one env."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

ENVIRONMENT_ADDRESS = re.compile(r'\["(development|production)"\]')
NON_SECRET_SENSITIVE_PATHS = {"viewer_certificate.acm_certificate_arn"}


class UnsafePlan(ValueError):
    pass


def _sensitive_paths(value: Any, path: tuple[str, ...] = ()) -> list[str]:
    if value is True:
        return [".".join(path)]
    if isinstance(value, dict):
        return [
            sensitive_path
            for key, item in value.items()
            for sensitive_path in _sensitive_paths(item, (*path, str(key)))
        ]
    if isinstance(value, list):
        return [
            sensitive_path
            for index, item in enumerate(value)
            for sensitive_path in _sensitive_paths(item, (*path, str(index)))
        ]
    return []


def validate_plan(plan: dict[str, Any], environment: str) -> list[str]:
    if environment not in {"development", "production"}:
        raise UnsafePlan(f"Unsupported environment: {environment}")

    changes = plan.get("resource_changes")
    if not isinstance(changes, list):
        raise UnsafePlan("Plan is missing a valid resource_changes list")

    accepted: list[str] = []
    for resource in changes:
        if not isinstance(resource, dict):
            raise UnsafePlan("Plan contains an invalid resource change entry")
        change = resource.get("change")
        address = resource.get("address")
        if not isinstance(change, dict) or not isinstance(address, str):
            raise UnsafePlan("Plan contains a resource change without address or actions")

        actions = change.get("actions")
        if not isinstance(actions, list) or not actions:
            raise UnsafePlan(f"Invalid actions for {address}")

        sensitive_paths = _sensitive_paths(change.get("before_sensitive", {})) + _sensitive_paths(
            change.get("after_sensitive", {})
        )
        unexpected_sensitive_paths = [
            path
            for path in sensitive_paths
            if re.sub(r"\.\d+(?=\.|$)", "", path) not in NON_SECRET_SENSITIVE_PATHS
        ]
        if unexpected_sensitive_paths:
            raise UnsafePlan(
                f"Sensitive values are present in the plan artifact: {address} "
                f"({', '.join(unexpected_sensitive_paths)})"
            )
        if actions == ["no-op"]:
            continue

        keys = ENVIRONMENT_ADDRESS.findall(address)
        if not keys or any(key != environment for key in keys):
            other = ", ".join(keys) if keys else "shared or unkeyed resource"
            raise UnsafePlan(f"Change is not isolated to {environment}: {address} ({other})")

        if any(action not in {"create", "update"} for action in actions):
            raise UnsafePlan(f"Delete or replacement is forbidden: {address} ({actions})")

        accepted.append(address)

    return accepted


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--environment", required=True, choices=["development", "production"])
    parser.add_argument("--plan-json", required=True, type=Path)
    args = parser.parse_args()

    try:
        plan = json.loads(args.plan_json.read_text(encoding="utf-8"))
        accepted = validate_plan(plan, args.environment)
    except (OSError, json.JSONDecodeError, UnsafePlan) as exc:
        print(f"Terraform plan rejected: {exc}", file=sys.stderr)
        return 1

    print(f"Terraform plan accepted for {args.environment}: {len(accepted)} resource change(s)")
    for address in accepted:
        print(f"- {address}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
