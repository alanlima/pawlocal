#!/usr/bin/env python3
"""Fail closed unless a plan changes only the selected container image."""

from __future__ import annotations

import argparse
import json
import re
import sys
from typing import Any


def validate(plan: dict[str, Any], environment: str, image: str, account_id: str) -> None:
    if not re.fullmatch(r"[0-9]{12}", account_id):
        raise ValueError("Terraform state has no valid AWS account ID")
    if not re.fullmatch(r"ghcr\.io/alanlima/pawlocal-api@sha256:[0-9a-f]{64}", image):
        raise ValueError("Selected image digest must be a digest-pinned PawLocal API image")
    expected = f'module.fullstack.aws_lightsail_container_service_deployment_version.api["{environment}"]'
    changes = [
        item
        for item in plan.get("resource_changes", [])
        if item.get("change", {}).get("actions") not in (["no-op"], ["read"])
    ]
    if not changes:
        raise ValueError("Terraform plan contains no container deployment change")
    by_address = {item.get("address"): item for item in changes}
    allowed = {expected}
    if any(item.get("address") not in allowed for item in changes):
        raise ValueError(
            "Terraform plan changes resources outside the selected container deployment"
        )
    if expected not in by_address:
        raise ValueError(
            "Terraform plan contains no selected container deployment change"
        )
    change = by_address[expected]["change"]
    if change.get("actions") not in (
        ["create"],
        ["update"],
        ["delete", "create"],
        ["create", "delete"],
    ):
        raise ValueError(
            "Selected container deployment is not a create, update, or replacement"
        )
    containers = (change.get("after") or {}).get("container") or []
    selected = next(
        (
            container
            for container in containers
            if container.get("container_name") == "pawlocal-api"
        ),
        None,
    )
    if selected is None or selected.get("image") != image:
        raise ValueError("Terraform plan does not contain the selected image digest")
    environment_values = selected.get("environment") or {}
    if environment_values.get("PAWLOCAL_RELEASE_ENVIRONMENT") != environment:
        raise ValueError("Container release environment does not match the selected environment")
    if (
        environment_values.get("PAWLOCAL_RELEASE_IMAGE_DIGEST")
        != image.rsplit("@", maxsplit=1)[1]
    ):
        raise ValueError("Container release image digest does not match the selected image")
    if environment == "development":
        expected_role = f"arn:aws:iam::{account_id}:role/pawlocal-development-dsql-runtime"
        if environment_values.get("PAWLOCAL_DSQL_ASSUME_ROLE_ARN") != expected_role:
            raise ValueError(
                "Development deployment must assume only the development DSQL runtime role"
            )
    elif "PAWLOCAL_DSQL_ASSUME_ROLE_ARN" in environment_values:
        raise ValueError("Production deployment must not change its DSQL runtime role configuration")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--environment", choices=("development", "production"), required=True
    )
    parser.add_argument("--image", required=True)
    parser.add_argument("--aws-account-id", required=True)
    args = parser.parse_args()
    try:
        validate(
            json.load(sys.stdin),
            args.environment,
            args.image,
            args.aws_account_id,
        )
    except (ValueError, KeyError, TypeError) as exc:
        print(f"Refusing Terraform container deployment: {exc}", file=sys.stderr)
        return 1
    print(
        "Terraform plan contains only the selected environment's container deployment and requested image digest."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
