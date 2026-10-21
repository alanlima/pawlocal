"""Validate and render a sanitized PawLocal environment Terraform plan."""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path


ALLOWED_TYPES = {
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

FORBIDDEN_TYPES = {
    "aws_iam_openid_connect_provider",
    "aws_iam_role",
    "aws_iam_role_policy",
}


def action_label(actions: list[str]) -> str:
    if not actions:
        return "no-op"
    if actions == ["delete", "create"] or actions == ["create", "delete"]:
        return "replace"
    return "+".join(actions)


def validate(plan: dict, environment: str, release_only: bool) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    errors: list[str] = []
    for change in plan.get("resource_changes", []):
        if change.get("mode") == "data":
            continue
        resource_type = change.get("type", "")
        actions = change.get("change", {}).get("actions", [])
        label = action_label(actions)
        if actions == ["no-op"]:
            continue
        rows.append((resource_type, label))
        if resource_type in FORBIDDEN_TYPES or resource_type not in ALLOWED_TYPES:
            errors.append(f"resource type is outside the environment ownership boundary: {resource_type}")
        expected_deployment_replacement = (
            resource_type == "aws_lightsail_container_service_deployment_version"
            and set(actions) == {"create", "delete"}
        )
        if "delete" in actions and not expected_deployment_replacement:
            errors.append(f"delete or replacement is not allowed by the normal environment workflow: {resource_type}")
        if change.get("importing") is not None or change.get("change", {}).get("importing") is not None:
            errors.append(f"application-resource import is prohibited: {resource_type}")
        if release_only and resource_type != "aws_lightsail_container_service_deployment_version":
            errors.append(f"release-only plan changes a non-release resource: {resource_type}")

    variables = plan.get("variables", {})
    selected = variables.get("environment", {}).get("value")
    if selected is not None and selected != environment:
        errors.append("plan environment does not match the selected workflow environment")
    if errors:
        raise SystemExit("Plan guard rejected the saved plan:\n- " + "\n- ".join(sorted(set(errors))))
    return rows


def render(rows: list[tuple[str, str]], environment: str) -> str:
    counts = Counter(rows)
    lines = [
        f"### Sanitized Terraform plan: {environment}",
        "",
        "Only resource types, actions, and counts are shown. Provider output, resource identifiers, values, and raw plan data are withheld.",
        "",
        "| Resource type | Action | Count |",
        "|---|---:|---:|",
    ]
    if not counts:
        lines.append("| No resource changes | no-op | 0 |")
    else:
        for (resource_type, action), count in sorted(counts.items()):
            lines.append(f"| `{resource_type}` | `{action}` | {count} |")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("plan_json", type=Path)
    parser.add_argument("--environment", choices=("development", "production"), required=True)
    parser.add_argument("--release-only", action="store_true")
    args = parser.parse_args()
    plan = json.loads(args.plan_json.read_text(encoding="utf-8"))
    print(render(validate(plan, args.environment, args.release_only), args.environment), end="")


if __name__ == "__main__":
    main()
