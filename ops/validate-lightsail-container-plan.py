#!/usr/bin/env python3
"""Fail closed unless a plan changes the selected image or reviewed dev DSQL bootstrap."""

from __future__ import annotations

import argparse
import json
import re
import sys
from typing import Any


def validate(plan: dict[str, Any], environment: str, image: str) -> None:
    expected = f'module.fullstack.aws_lightsail_container_service_deployment_version.api["{environment}"]'
    dev_authorization = {
        'module.fullstack.aws_dsql_cluster_policy.api_connect["development"]': [
            "update"
        ],
        'module.fullstack.aws_iam_role.dsql_runtime["development"]': ["create"],
        'module.fullstack.aws_iam_role_policy.dsql_runtime["development"]': ["create"],
        'module.fullstack.aws_iam_role_policy.github_terraform_deploy["development"]': [
            "update"
        ],
        'module.fullstack.terraform_data.app_dsql_role["development"]': [
            "delete",
            "create",
        ],
    }
    changes = [
        item
        for item in plan.get("resource_changes", [])
        if item.get("change", {}).get("actions") not in (["no-op"], ["read"])
    ]
    if not changes:
        raise ValueError("Terraform plan contains no container deployment change")
    by_address = {item.get("address"): item for item in changes}
    allowed = {expected}
    if environment == "development" and any(
        address in by_address for address in dev_authorization
    ):
        allowed.update(dev_authorization)
        missing = set(dev_authorization) - set(by_address)
        if missing:
            raise ValueError("Development DSQL authorization changes are incomplete")
        for address, actions in dev_authorization.items():
            if by_address[address].get("change", {}).get("actions") != actions:
                raise ValueError(
                    f"Unexpected action for reviewed development authorization resource: {address}"
                )
        runtime_policy = (
            by_address[
                'module.fullstack.aws_iam_role_policy.dsql_runtime["development"]'
            ]
            .get("change", {})
            .get("after", {})
            .get("policy")
        )
        if not runtime_policy:
            raise ValueError("Development runtime role policy is missing")
        parsed_runtime_policy = json.loads(runtime_policy)
        statements = parsed_runtime_policy.get("Statement", [])
        runtime_resource = (
            statements[0].get("Resource") if len(statements) == 1 else None
        )
        if (
            len(statements) != 1
            or statements[0].get("Action") != "dsql:DbConnect"
            or statements[0].get("Effect") != "Allow"
            or not isinstance(runtime_resource, str)
            or not re.fullmatch(
                r"arn:[^:]+:dsql:[^:]+:[0-9]{12}:cluster/[^:*]+", runtime_resource
            )
        ):
            raise ValueError(
                "Development runtime role must have only cluster-scoped dsql:DbConnect"
            )
        admin_policy = (
            by_address[
                'module.fullstack.aws_iam_role_policy.github_terraform_deploy["development"]'
            ]
            .get("change", {})
            .get("after", {})
            .get("policy")
        )
        if not admin_policy:
            raise ValueError("Development Terraform role policy is missing")
        parsed_admin_policy = json.loads(admin_policy)
        admin_statements = [
            statement
            for statement in parsed_admin_policy.get("Statement", [])
            if statement.get("Sid") == "ConnectAsDsqlAdminForDevelopmentBootstrap"
        ]
        if (
            len(admin_statements) != 1
            or admin_statements[0].get("Action") != "dsql:DbConnectAdmin"
            or admin_statements[0].get("Effect") != "Allow"
            or admin_statements[0].get("Resource") != runtime_resource
        ):
            raise ValueError(
                "Development Terraform role is missing matching cluster-scoped DSQL admin bootstrap access"
            )
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
    if not any(container.get("image") == image for container in containers):
        raise ValueError("Terraform plan does not contain the selected image digest")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--environment", choices=("development", "production"), required=True
    )
    parser.add_argument("--image", required=True)
    args = parser.parse_args()
    try:
        validate(json.load(sys.stdin), args.environment, args.image)
    except (ValueError, KeyError, TypeError) as exc:
        print(f"Refusing Terraform container deployment: {exc}", file=sys.stderr)
        return 1
    print(
        "Terraform plan contains only the selected image and, when present, the complete reviewed development DSQL authorization bundle."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
