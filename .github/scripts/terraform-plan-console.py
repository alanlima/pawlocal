#!/usr/bin/env python3
"""Render an opt-in, value-free console view of an exact saved Terraform plan."""

from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from pathlib import Path


SAFE_RESOURCE_TYPES = {
    "aws_cloudfront_distribution",
    "aws_cloudfront_function",
    "aws_cloudfront_origin_access_control",
    "aws_cognito_user_pool",
    "aws_cognito_user_pool_client",
    "aws_cognito_user_pool_domain",
    "aws_dsql_cluster",
    "aws_dsql_cluster_policy",
    "aws_iam_policy",
    "aws_iam_role_policy_attachment",
    "aws_lightsail_certificate",
    "aws_lightsail_container_service",
    "aws_lightsail_container_service_deployment_version",
    "aws_route53_record",
    "aws_s3_bucket",
    "aws_s3_bucket_ownership_controls",
    "aws_s3_bucket_policy",
    "aws_s3_bucket_public_access_block",
    "aws_s3_bucket_server_side_encryption_configuration",
    "random_id",
    "time_sleep",
}

ACTION_REASONS = {
    "delete_because_count_index": "configured count no longer selects this instance",
    "delete_because_each_key": "configured for_each no longer selects this instance",
    "delete_because_no_resource_config": "resource is absent from configuration",
    "delete_because_wrong_repetition": "resource repetition mode changed",
    "read_because_config_unknown": "configuration is not fully known until apply",
    "read_because_dependency_pending": "a dependency has a pending change",
    "replace_because_cannot_update": "provider requires replacement for this change",
    "replace_because_tainted": "tainted state requires replacement",
    "replace_by_request": "replacement was explicitly requested",
}


def action_label(actions: list[str]) -> str:
    if actions in (["delete", "create"], ["create", "delete"]):
        return "replace"
    if len(actions) == 1 and actions[0] in {"create", "delete", "no-op", "read", "update"}:
        return actions[0]
    return "withheld"


def rows(plan: dict[str, object]) -> tuple[Counter[tuple[str, str, str]], int, int]:
    counts: Counter[tuple[str, str, str]] = Counter()
    imports = 0
    data_reads = 0
    for change in plan.get("resource_changes", []):
        if not isinstance(change, dict):
            continue
        details = change.get("change", {})
        if not isinstance(details, dict):
            details = {}
        actions = details.get("actions", [])
        if not isinstance(actions, list) or not all(isinstance(action, str) for action in actions):
            actions = []
        if change.get("mode") == "data":
            if actions == ["read"]:
                data_reads += 1
            continue

        resource_type = change.get("type")
        safe_type = resource_type if resource_type in SAFE_RESOURCE_TYPES else "withheld_resource_type"
        action = action_label(actions)
        reason = ACTION_REASONS.get(change.get("action_reason"), "")
        counts[(safe_type, action, reason)] += 1
        if change.get("importing") is not None or details.get("importing") is not None:
            imports += 1
    return counts, imports, data_reads


def render(plan: dict[str, object], environment: str) -> str:
    counts, imports, data_reads = rows(plan)
    action_totals = Counter()
    for (_, action, _), count in counts.items():
        action_totals[action] += count

    lines = [
        "Saved Terraform plan diagnostic (sanitized)",
        f"Environment: {environment}",
        "Resource addresses, names, identifiers, values, outputs, variables, provider details, and plan metadata are withheld.",
        "",
        "Managed-resource totals: "
        + ", ".join(
            f"{action}={action_totals.get(action, 0)}"
            for action in ("create", "update", "delete", "replace", "read", "no-op", "withheld")
        ),
        f"Imports: {imports}",
        f"Data reads: {data_reads}",
        "",
        "Resource type | Action | Terraform reason | Count",
        "---|---|---|---:",
    ]
    if not counts:
        lines.append("No managed resource changes | no-op |  | 0")
    else:
        for (resource_type, action, reason), count in sorted(counts.items()):
            lines.append(f"{resource_type} | {action} | {reason or 'not reported'} | {count}")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("plan_json", type=Path)
    parser.add_argument("--environment", choices=("development", "production"), required=True)
    args = parser.parse_args()

    if os.environ.get("PAWLOCAL_TERRAFORM_DIAGNOSTIC_LOGS") != "true":
        return 0

    try:
        plan = json.loads(args.plan_json.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        print("Saved Terraform plan diagnostic unavailable; raw plan output was withheld.")
        return 0
    if not isinstance(plan, dict):
        print("Saved Terraform plan diagnostic unavailable; raw plan output was withheld.")
        return 0

    print(render(plan, args.environment), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
