"""Render a value-sanitized, environment-scoped Terraform plan review."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from typing import Any

SUPPORTED_RESOURCE_TYPES = {
    "aws_cognito_user_pool",
    "aws_cognito_user_pool_client",
    "aws_cognito_user_pool_domain",
    "aws_cloudfront_distribution",
    "aws_cloudfront_function",
    "aws_cloudfront_origin_access_control",
    "aws_dsql_cluster",
    "aws_dsql_cluster_policy",
    "aws_iam_openid_connect_provider",
    "aws_iam_policy_document",
    "aws_iam_role",
    "aws_iam_role_policy",
    "aws_lightsail_certificate",
    "aws_lightsail_container_service",
    "aws_lightsail_container_service_deployment_version",
    "aws_route53_record",
    "aws_route53_zone",
    "aws_s3_bucket",
    "aws_s3_bucket_lifecycle_configuration",
    "aws_s3_bucket_ownership_controls",
    "aws_s3_bucket_policy",
    "aws_s3_bucket_public_access_block",
    "aws_s3_bucket_server_side_encryption_configuration",
    "aws_caller_identity",
    "aws_iam_policy_document",
    "aws_iam_openid_connect_provider",
    "random_id",
    "terraform_data",
}
SUPPORTED_ACTIONS = {"create", "update", "read", "no-op"}
SENSITIVE_KEY = re.compile(
    r"password|secret|token|credential|private.?key|access.?key|api.?key|authorization|cookie",
    re.IGNORECASE,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--environment", choices=("development", "production"), required=True)
    return parser.parse_args()


def flatten(value: Any, mask: Any, path: str = "", parent_key: str = "") -> dict[str, Any]:
    if mask is True or SENSITIVE_KEY.search(parent_key):
        return {path or "<root>": "[REDACTED]"}
    if isinstance(value, dict):
        if not value:
            return {path or "<root>": {}}
        result: dict[str, Any] = {}
        for key, child in value.items():
            child_path = f"{path}.{key}" if path else str(key)
            child_mask = mask.get(key, False) if isinstance(mask, dict) else False
            result.update(flatten(child, child_mask, child_path, str(key)))
        return result
    if isinstance(value, list):
        if not value:
            return {path or "<root>": []}
        result = {}
        for index, child in enumerate(value):
            child_path = f"{path}[{index}]"
            child_mask = mask[index] if isinstance(mask, list) and index < len(mask) else False
            result.update(flatten(child, child_mask, child_path, parent_key))
        return result
    return {path or "<root>": value}


def escape_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("`", "\\`").replace("\n", " ")


def change_rows(plan: dict[str, Any], environment: str) -> tuple[list[str], Counter[str]]:
    rows: list[str] = []
    counts: Counter[str] = Counter()
    other_environment = "production" if environment == "development" else "development"

    for item in plan.get("resource_changes", []):
        address = str(item.get("address", ""))
        resource_type = str(item.get("type", ""))
        change = item.get("change", {})
        actions = change.get("actions")
        if not isinstance(actions, list) or not actions:
            raise ValueError("Terraform plan contains an unclassifiable action list")
        if "delete" in actions:
            raise ValueError("Terraform plan contains a delete or replacement; deployment is blocked")
        if resource_type == "aws_cloudfront_origin_access_control" and "update" in actions:
            raise ValueError("Terraform plan updates a CloudFront origin access control; refresh exact-ARN IAM scope and review the change first")
        unknown_actions = set(actions) - SUPPORTED_ACTIONS
        if unknown_actions:
            raise ValueError(f"Unsupported Terraform actions: {sorted(unknown_actions)}")
        if resource_type not in SUPPORTED_RESOURCE_TYPES:
            raise ValueError("Terraform plan contains an unsupported resource type")
        if other_environment in address:
            raise ValueError(f"{environment} plan contains a {other_environment}-scoped resource")
        if actions == ["no-op"]:
            continue

        for action in actions:
            counts[str(action)] += 1
        before = flatten(change.get("before"), change.get("before_sensitive", False))
        after = flatten(change.get("after"), change.get("after_sensitive", False))
        after_unknown = flatten(change.get("after_unknown", {}), False)
        attributes = []
        for path in sorted(set(before) | set(after) | set(after_unknown)):
            before_value = before.get(path, "[absent]")
            after_value = after.get(path, "[absent]")
            if path in after_unknown and after_unknown[path] is True:
                after_value = "[unknown until apply]"
            if before_value != after_value:
                if before_value == "[REDACTED]" or after_value == "[REDACTED]":
                    attributes.append("(sensitive attribute omitted)")
                elif SENSITIVE_KEY.search(path):
                    attributes.append("(credential-like attribute omitted)")
                else:
                    attributes.append(f"`{escape_cell(path)}`")
        path_summary = "; ".join(sorted(set(attributes))) if attributes else "(no attribute diff available)"
        action_text = "+".join(str(action) for action in actions)
        rows.append(
            f"| `{escape_cell(address)}` | `{action_text}` | {path_summary} |"
        )

    return rows, counts


def build_review(plan: dict[str, Any], environment: str) -> str:
    if not isinstance(plan.get("format_version"), str) or not isinstance(plan.get("resource_changes"), list):
        raise ValueError("Input is not a Terraform plan JSON document")
    if plan.get("applyable") is not True:
        raise ValueError("Terraform plan is not applyable")
    if plan.get("complete") is not True:
        raise ValueError("Terraform plan is incomplete")
    if plan.get("errored") is not False:
        raise ValueError("Terraform plan reports an error")

    output_changes = plan.get("output_changes", {})
    if not isinstance(output_changes, dict):
        raise ValueError("Terraform plan output_changes is not a mapping")
    output_count = 0
    for name, change in output_changes.items():
        if not isinstance(change, dict) or not isinstance(change.get("actions"), list):
            raise ValueError("Terraform plan contains an unclassifiable output change")
        actions = change["actions"]
        if not actions or set(actions) - SUPPORTED_ACTIONS or "delete" in actions:
            raise ValueError("Terraform plan contains an unsupported or destructive output change")
        output_count += 1

    deferred_changes = plan.get("deferred_changes", [])
    if not isinstance(deferred_changes, list):
        raise ValueError("Terraform plan deferred_changes is not a list")
    if deferred_changes:
        raise ValueError("Terraform plan contains deferred changes that cannot be safely reviewed")

    rows, counts = change_rows(plan, environment)
    if not rows:
        rows = ["| (no resource changes) | `no-op` | (none) |"]
    counts_text = ", ".join(f"{name}: {counts[name]}" for name in sorted(counts)) or "no changes"
    return "\n".join([
        f"### {environment.title()} change summary",
        "",
        f"Resource actions: {counts_text}",
        f"Output changes: {output_count}",
        "Deferred changes: 0",
        "",
        "| Resource address | Action | Sanitized changed attributes |",
        "|---|---|---|",
        *rows,
        "",
        "This public summary includes no Terraform attribute values. Sensitive and credential-like fields are omitted.",
    ])


def main() -> None:
    args = parse_args()
    try:
        plan = json.load(sys.stdin)
        print(build_review(plan, args.environment))
    except (json.JSONDecodeError, ValueError) as exc:
        print(f"Terraform plan review rejected: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
