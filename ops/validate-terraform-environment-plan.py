#!/usr/bin/env python3
"""Fail closed unless every Terraform effect is explicitly environment-scoped."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

# Resource type and Terraform name pairs whose effects are confined to the
# selected environment. IAM, account-wide, shared, and unknown resources are
# intentionally absent. Additions require code review and dedicated tests.
ENVIRONMENT_RESOURCE_ALLOWLIST = {
    ("aws_cloudfront_distribution", "app"),
    ("aws_cloudfront_function", "spa"),
    ("aws_cloudfront_origin_access_control", "frontend"),
    ("aws_cognito_user_pool", "app"),
    ("aws_cognito_user_pool_client", "app"),
    ("aws_cognito_user_pool_domain", "app"),
    ("aws_dsql_cluster", "app"),
    ("aws_dsql_cluster_policy", "api_connect"),
    ("aws_lightsail_certificate", "api"),
    ("aws_lightsail_container_service", "api"),
    ("aws_lightsail_container_service_deployment_version", "api"),
    ("aws_route53_record", "api"),
    ("aws_route53_record", "api_certificate_validation"),
    ("aws_route53_record", "frontend_a"),
    ("aws_route53_record", "frontend_aaaa"),
    ("aws_s3_bucket", "frontend"),
    ("aws_s3_bucket_ownership_controls", "frontend"),
    ("aws_s3_bucket_policy", "frontend"),
    ("aws_s3_bucket_public_access_block", "frontend"),
    ("aws_s3_bucket_server_side_encryption_configuration", "frontend"),
    ("terraform_data", "app_dsql_role"),
}

ENVIRONMENT_ADDRESS = re.compile(
    r'^module\.fullstack\.(?P<type>[a-z0-9_]+)\.(?P<name>[a-z0-9_]+)'
    r'\["(?P<environment>development|production)"\]$'
)
CERTIFICATE_ARN_MARKER = ("viewer_certificate", "acm_certificate_arn")


class UnsafePlan(ValueError):
    """The plan contains an effect the environment gate cannot approve."""


def _sensitive_markers(value: Any, path: tuple[str, ...] = ()) -> list[tuple[str, ...]]:
    """Find true sensitivity markers throughout the full show-json document."""
    found: list[tuple[str, ...]] = []
    if isinstance(value, dict):
        for key, item in value.items():
            child_path = (*path, str(key))
            key_is_marker = key == "sensitive" or key == "sensitive_values" or key.endswith("_sensitive")
            if key == "sensitive" and item is True:
                found.append(child_path)
            elif key_is_marker:
                found.extend(_true_leaves(item, child_path))
            else:
                found.extend(_sensitive_markers(item, child_path))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            found.extend(_sensitive_markers(item, (*path, str(index))))
    return found


def _true_leaves(value: Any, path: tuple[str, ...]) -> list[tuple[str, ...]]:
    if value is True:
        return [path]
    if isinstance(value, dict):
        return [entry for key, item in value.items() for entry in _true_leaves(item, (*path, str(key)))]
    if isinstance(value, list):
        return [entry for index, item in enumerate(value) for entry in _true_leaves(item, (*path, str(index)))]
    return []


def _sensitivity_allowed(path: tuple[str, ...], plan: dict[str, Any]) -> bool:
    normalized = tuple(part for part in path if not part.isdigit())
    if normalized[-2:] != CERTIFICATE_ARN_MARKER:
        return False
    try:
        section = path.index("resource_changes")
        index = int(path[section + 1])
        resource = plan["resource_changes"][index]
        address = resource["address"]
    except (ValueError, IndexError, KeyError, TypeError):
        return False
    # Only the CloudFront viewer certificate ARN is intentionally marked
    # sensitive by the AWS provider while remaining non-secret.
    return isinstance(address, str) and re.fullmatch(
        r'module\.fullstack\.aws_cloudfront_distribution\.app\["(development|production)"\]',
        address,
    ) is not None


def _validate_sensitive_metadata(plan: dict[str, Any]) -> None:
    unexpected = [path for path in _sensitive_markers(plan) if not _sensitivity_allowed(path, plan)]
    if unexpected:
        paths = [".".join(path) for path in unexpected]
        raise UnsafePlan("Terraform marks values sensitive in the plan document: " + ", ".join(paths))


def _validate_resource_effect(resource: dict[str, Any], environment: str) -> str | None:
    address = resource.get("address")
    change = resource.get("change")
    if not isinstance(address, str) or not isinstance(change, dict):
        raise UnsafePlan("Plan contains a resource change without address or change details")
    actions = change.get("actions")
    if not isinstance(actions, list) or not actions:
        raise UnsafePlan(f"Invalid actions for {address}")
    if actions == ["no-op"] or actions == ["read"]:
        return None
    if actions not in (["create"], ["update"]):
        raise UnsafePlan(f"Delete, replacement, or unclassified action is forbidden: {address} ({actions})")

    match = ENVIRONMENT_ADDRESS.fullmatch(address)
    if not match:
        raise UnsafePlan(f"Shared, account-wide, or unclassified resource change is forbidden: {address}")
    resource_type, resource_name, resource_environment = match.group("type", "name", "environment")
    if resource_environment != environment:
        raise UnsafePlan(f"Change is not isolated to {environment}: {address}")
    if (resource_type, resource_name) not in ENVIRONMENT_RESOURCE_ALLOWLIST:
        raise UnsafePlan(f"Resource effect is not allowlisted for environment deployment: {address}")
    return address


def validate_plan(plan: dict[str, Any], environment: str) -> list[str]:
    if environment not in {"development", "production"}:
        raise UnsafePlan(f"Unsupported environment: {environment}")
    if not isinstance(plan, dict):
        raise UnsafePlan("Plan JSON must be an object")
    changes = plan.get("resource_changes")
    if not isinstance(changes, list):
        raise UnsafePlan("Plan is missing a valid resource_changes list")

    _validate_sensitive_metadata(plan)
    accepted: list[str] = []
    for resource in changes:
        if not isinstance(resource, dict):
            raise UnsafePlan("Plan contains an invalid resource change entry")
        address = _validate_resource_effect(resource, environment)
        if address is not None:
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
