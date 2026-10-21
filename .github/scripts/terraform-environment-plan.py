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

RELEASE_RESOURCE_TYPE = "aws_lightsail_container_service_deployment_version"
RELEASE_ACTIONS = {
    ("create",),
    ("create", "delete"),
    ("delete", "create"),
}
DSQL_SETUP_RESOURCE_ADDRESS = (
    "module.pawlocal.module.dsql_post_apply_setup[0].terraform_data.setup"
)
DSQL_SETUP_ACTIONS = {
    ("create",),
    ("create", "delete"),
    ("delete", "create"),
}


def action_label(actions: list[str]) -> str:
    if not actions:
        return "no-op"
    if actions == ["delete", "create"] or actions == ["create", "delete"]:
        return "replace"
    return "+".join(actions)


def plan_rows(plan: dict) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    for change in plan.get("resource_changes", []):
        if change.get("mode") == "data":
            continue
        actions = change.get("change", {}).get("actions", [])
        if actions == ["no-op"]:
            continue
        rows.append((change.get("type", ""), action_label(actions)))
    return rows


def validate(plan: dict, environment: str, release_only: bool) -> list[tuple[str, str]]:
    rows = plan_rows(plan)
    errors: list[str] = []
    for change in plan.get("resource_changes", []):
        if change.get("mode") == "data":
            continue
        resource_type = change.get("type", "")
        resource_address = change.get("address", "")
        managed_dsql_setup = (
            resource_type == "terraform_data"
            and resource_address == DSQL_SETUP_RESOURCE_ADDRESS
        )
        reported_type = (
            resource_type
            if (
                resource_type in ALLOWED_TYPES
                or resource_type in FORBIDDEN_TYPES
                or resource_type == "terraform_data"
            )
            else "withheld_resource_type"
        )
        change_details = change.get("change", {})
        actions = change_details.get("actions", [])
        importing = (
            change.get("importing") is not None
            or change_details.get("importing") is not None
        )
        if importing:
            errors.append(f"application-resource import is prohibited: {reported_type}")
        if "forget" in actions:
            errors.append(f"forget action is prohibited: {reported_type}")
        if actions == ["no-op"]:
            continue
        if (
            resource_type in FORBIDDEN_TYPES
            or (resource_type not in ALLOWED_TYPES and not managed_dsql_setup)
        ):
            errors.append(
                f"resource type is outside the environment ownership boundary: {reported_type}"
            )
        expected_deployment_replacement = (
            resource_type == RELEASE_RESOURCE_TYPE
            and set(actions) == {"create", "delete"}
        )
        expected_dsql_setup_replacement = (
            managed_dsql_setup and set(actions) == {"create", "delete"}
        )
        if (
            "delete" in actions
            and not expected_deployment_replacement
            and not expected_dsql_setup_replacement
        ):
            errors.append(
                "delete or replacement is not allowed by the normal environment workflow: "
                f"{reported_type}"
            )
        if managed_dsql_setup and tuple(actions) not in DSQL_SETUP_ACTIONS:
            errors.append(
                f"managed DSQL setup uses an unsupported action: {reported_type}"
            )
        if release_only:
            if resource_type != RELEASE_RESOURCE_TYPE:
                errors.append(
                    f"release-only plan changes a non-release resource: {reported_type}"
                )
            elif tuple(actions) not in RELEASE_ACTIONS:
                errors.append(
                    "release-only plan uses an unsupported deployment action: "
                    f"{reported_type}"
                )

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
    rows = validate(plan, args.environment, args.release_only)
    print(render(rows, args.environment), end="")


if __name__ == "__main__":
    main()
