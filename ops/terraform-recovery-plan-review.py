"""Render a value-free review summary for the approved legacy state teardown."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from typing import Any

SUPPORTED_RESOURCE_TYPES = {
    "aws_cognito_user_pool", "aws_cognito_user_pool_client", "aws_cognito_user_pool_domain",
    "aws_cloudfront_distribution", "aws_cloudfront_function", "aws_cloudfront_origin_access_control",
    "aws_dsql_cluster", "aws_dsql_cluster_policy", "aws_iam_openid_connect_provider",
    "aws_iam_policy_document", "aws_iam_role", "aws_iam_role_policy", "aws_lightsail_certificate",
    "aws_lightsail_container_service", "aws_lightsail_container_service_deployment_version",
    "aws_route53_record", "aws_route53_zone", "aws_s3_bucket",
    "aws_s3_bucket_lifecycle_configuration", "aws_s3_bucket_ownership_controls", "aws_s3_bucket_policy",
    "aws_s3_bucket_public_access_block", "aws_s3_bucket_server_side_encryption_configuration",
    "aws_caller_identity", "random_id", "terraform_data",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-bucket-name", required=True)
    return parser.parse_args()


def render(plan: dict[str, Any], state_bucket_name: str) -> str:
    if not isinstance(plan.get("format_version"), str) or not isinstance(plan.get("resource_changes"), list):
        raise ValueError("Input is not a Terraform plan JSON document")

    counts_by_type: Counter[str] = Counter()
    counts: Counter[str] = Counter()
    non_mutating = 0
    for item in plan["resource_changes"]:
        resource_type = str(item.get("type", ""))
        mode = item.get("mode", "managed")
        change = item.get("change", {})
        actions = change.get("actions")
        if resource_type not in SUPPORTED_RESOURCE_TYPES:
            raise ValueError("Recovery plan contains an unsupported resource type")
        if mode == "data" and actions in (["read"], ["no-op"]):
            non_mutating += 1
            continue
        if mode == "managed" and actions == ["no-op"]:
            non_mutating += 1
            continue
        if actions != ["delete"]:
            raise ValueError("Recovery plan must contain only direct deletes; create, update, replacement, and unknown actions are rejected")
        before = change.get("before") or {}
        if resource_type == "aws_s3_bucket" and before.get("bucket") == state_bucket_name:
            raise ValueError("Recovery plan attempts to delete the Terraform backend bucket")
        counts["delete"] += 1
        counts_by_type[resource_type] += 1

    rows = [f"| `{resource_type}` | `delete` | {count} |" for resource_type, count in sorted(counts_by_type.items())]
    if not rows:
        rows.append("| (no changes) | `no-op` | 0 |")
    return "\n".join([
        "### Legacy Terraform state recovery plan",
        "",
        f"Resources to delete: {counts['delete']}",
        f"Non-mutating reads/no-ops: {non_mutating}",
        "",
        "| Resource type | Action | Count |",
        "|---|---|---:|",
        *rows,
        "",
        "Resource addresses and attribute values are omitted. The Terraform backend bucket is explicitly protected.",
    ])


def main() -> None:
    args = parse_args()
    try:
        print(render(json.load(sys.stdin), args.state_bucket_name))
    except (json.JSONDecodeError, ValueError) as exc:
        print(f"Recovery plan review rejected: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
