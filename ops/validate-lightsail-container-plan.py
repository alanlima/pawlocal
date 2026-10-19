#!/usr/bin/env python3
"""Fail closed unless a Terraform plan changes only the selected container image."""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any


def validate(plan: dict[str, Any], environment: str, image: str) -> None:
    expected = f'module.fullstack.aws_lightsail_container_service_deployment_version.api["{environment}"]'
    changes = [
        item for item in plan.get("resource_changes", [])
        if item.get("change", {}).get("actions") not in (["no-op"], ["read"])
    ]
    if not changes:
        raise ValueError("Terraform plan contains no container deployment change")
    if any(item.get("address") != expected for item in changes):
        raise ValueError("Terraform plan changes resources outside the selected container deployment")
    change = changes[0]["change"]
    if change.get("actions") not in (["create"], ["update"]):
        raise ValueError("Selected container deployment is not a create or update")
    containers = (change.get("after") or {}).get("container") or []
    if not any(container.get("image") == image for container in containers):
        raise ValueError("Terraform plan does not contain the selected image digest")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--environment", choices=("development", "production"), required=True)
    parser.add_argument("--image", required=True)
    args = parser.parse_args()
    try:
        validate(json.load(sys.stdin), args.environment, args.image)
    except (ValueError, KeyError, TypeError) as exc:
        print(f"Refusing Terraform container deployment: {exc}", file=sys.stderr)
        return 1
    print("Terraform plan changes only the selected container deployment and image digest.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
