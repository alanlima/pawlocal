"""Render a value-free review summary for the approved legacy state teardown."""

from __future__ import annotations

import argparse
import json
import re
import sys
from typing import Any

ENVIRONMENTS = ("development", "production")

# These addresses are derived from infra/terraform/main.tf and fullstack/main.tf.
# Optional deployment versions are included only when present in the legacy state.
ROOT_MANAGED = {
    "random_id.site_bucket_suffix",
    "aws_s3_bucket.site",
    "aws_s3_bucket_ownership_controls.site",
    "aws_s3_bucket_public_access_block.site",
    "aws_s3_bucket_server_side_encryption_configuration.site",
    "aws_cloudfront_origin_access_control.site",
    "aws_cloudfront_distribution.site",
    "aws_cloudfront_function.site_spa",
    "aws_s3_bucket_policy.site",
    "aws_route53_record.site_a",
    "aws_route53_record.site_aaaa",
    "aws_iam_role.github_deploy",
    "aws_iam_role_policy.github_deploy",
    "aws_iam_openid_connect_provider.github[0]",
}
FULLSTACK_PER_ENV = {
    "random_id.bucket_suffix",
    "aws_s3_bucket.frontend",
    "aws_s3_bucket_ownership_controls.frontend",
    "aws_s3_bucket_public_access_block.frontend",
    "aws_s3_bucket_server_side_encryption_configuration.frontend",
    "aws_cloudfront_origin_access_control.frontend",
    "aws_dsql_cluster.app",
    "aws_lightsail_certificate.api",
    "aws_route53_record.api_certificate_validation",
    "aws_lightsail_container_service.api",
    "aws_dsql_cluster_policy.api_connect",
    "aws_route53_record.api",
    "aws_cloudfront_distribution.app",
    "aws_cloudfront_function.spa",
    "aws_s3_bucket_policy.frontend",
    "aws_route53_record.frontend_a",
    "aws_route53_record.frontend_aaaa",
    "random_id.cognito_domain_suffix",
    "aws_cognito_user_pool.app",
    "aws_cognito_user_pool_domain.app",
    "aws_cognito_user_pool_client.app",
    "aws_iam_role.github_deploy",
    "aws_iam_role_policy.github_deploy",
    "aws_iam_role.github_terraform_deploy",
    "aws_iam_role_policy.github_terraform_deploy",
    "terraform_data.app_dsql_role",
}
OPTIONAL_FULLSTACK_PER_ENV = {"aws_lightsail_container_service_deployment_version.api"}
DEV_ONLY = {"aws_iam_role.dsql_runtime", "aws_iam_role_policy.dsql_runtime"}

ROOT_DATA = {
    "data.aws_route53_zone.site",
    "data.aws_caller_identity.current",
    "data.aws_iam_policy_document.site_bucket",
    "data.aws_iam_openid_connect_provider.github[0]",
    "data.aws_iam_policy_document.github_deploy_assume_role",
    "data.aws_iam_policy_document.github_deploy",
}
FULLSTACK_DATA = {
    "data.aws_route53_zone.root",
    "data.aws_caller_identity.current",
    "data.aws_partition.current",
    "data.aws_iam_openid_connect_provider.github[0]",
}
FULLSTACK_DATA_PER_ENV = {
    "data.aws_iam_policy_document.dsql_runtime_trust",
    "data.aws_iam_policy_document.frontend_bucket",
    "data.aws_iam_policy_document.github_deploy_trust",
    "data.aws_iam_policy_document.github_deploy",
    "data.aws_iam_policy_document.github_terraform_deploy",
}


def _managed_inventory() -> tuple[set[str], set[str]]:
    required = set(ROOT_MANAGED)
    optional: set[str] = set()
    for environment in ENVIRONMENTS:
        for name in FULLSTACK_PER_ENV:
            required.add(f"module.fullstack.{name}[\"{environment}\"]")
        for name in OPTIONAL_FULLSTACK_PER_ENV:
            optional.add(f"module.fullstack.{name}[\"{environment}\"]")
    for name in DEV_ONLY:
        required.add(f"module.fullstack.{name}[\"development\"]")
    return required, optional


REQUIRED_MANAGED, OPTIONAL_MANAGED = _managed_inventory()
ALLOWED_MANAGED = REQUIRED_MANAGED | OPTIONAL_MANAGED
REQUIRED_PRODUCTION_FRONTEND = {
    "module.fullstack.random_id.bucket_suffix[\"production\"]",
    "module.fullstack.aws_s3_bucket.frontend[\"production\"]",
    "module.fullstack.aws_s3_bucket_ownership_controls.frontend[\"production\"]",
    "module.fullstack.aws_s3_bucket_public_access_block.frontend[\"production\"]",
    "module.fullstack.aws_s3_bucket_server_side_encryption_configuration.frontend[\"production\"]",
    "module.fullstack.aws_cloudfront_origin_access_control.frontend[\"production\"]",
    "module.fullstack.aws_cloudfront_distribution.app[\"production\"]",
    "module.fullstack.aws_cloudfront_function.spa[\"production\"]",
    "module.fullstack.aws_s3_bucket_policy.frontend[\"production\"]",
    "module.fullstack.aws_route53_record.frontend_a[\"production\"]",
    "module.fullstack.aws_route53_record.frontend_aaaa[\"production\"]",
}


def _allowed_data_addresses() -> set[str]:
    allowed = set(ROOT_DATA)
    allowed.update(f"module.fullstack.{address}" for address in FULLSTACK_DATA)
    for environment in ENVIRONMENTS:
        allowed.update(
            f"module.fullstack.{address}[\"{environment}\"]"
            for address in FULLSTACK_DATA_PER_ENV
        )
    return allowed


ALLOWED_DATA = _allowed_data_addresses()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-bucket-name", required=True)
    return parser.parse_args()


def _validate_bucket(address: str, before: dict[str, Any], state_bucket_name: str) -> None:
    bucket = before.get("bucket")
    if not isinstance(bucket, str) or bucket == state_bucket_name:
        raise ValueError("Recovery plan attempts to delete the backend bucket or has no verifiable bucket name")
    if address == "aws_s3_bucket.site":
        valid = re.fullmatch(r"pawlocal-frontend-[0-9a-f]{8}", bucket)
    else:
        match = re.fullmatch(r'module\.fullstack\.aws_s3_bucket\.frontend\["(development|production)"\]', address)
        valid = re.fullmatch(rf"pawlocal-{match.group(1)}-[0-9a-f]{{6}}", bucket) if match else None
    if not valid:
        raise ValueError("Recovery plan contains a bucket outside the exact legacy frontend naming scheme")


def _resource_type_from_address(address: str) -> str:
    segments = address.split(".")
    for segment in segments:
        if segment.startswith(("aws_", "random_", "terraform_")):
            return segment.split("[", 1)[0]
    return ""


def render(plan: dict[str, Any], state_bucket_name: str) -> str:
    if not isinstance(plan.get("format_version"), str) or not isinstance(plan.get("resource_changes"), list):
        raise ValueError("Input is not a Terraform plan JSON document")
    if plan.get("errored") is True or plan.get("complete") is False or plan.get("applyable") is False:
        raise ValueError("Recovery plan must be complete, applyable, and error-free")
    if plan.get("deferred_changes"):
        raise ValueError("Recovery plan contains deferred changes")
    if plan.get("output_changes"):
        raise ValueError("Recovery plan must not contain output changes")

    deleted: list[str] = []
    observed_managed: set[str] = set()
    non_mutating = 0
    for item in plan["resource_changes"]:
        if not isinstance(item, dict):
            raise ValueError("Recovery plan contains a malformed resource change")
        address = item.get("address")
        resource_type = item.get("type")
        mode = item.get("mode", "managed")
        change = item.get("change", {})
        actions = change.get("actions") if isinstance(change, dict) else None
        if not isinstance(address, str) or not isinstance(resource_type, str):
            raise ValueError("Recovery plan contains a resource without a verifiable address and type")
        if mode == "data":
            if address not in ALLOWED_DATA or actions not in (["read"], ["no-op"]):
                raise ValueError("Recovery plan contains an unsupported data source or action")
            non_mutating += 1
            continue
        if mode != "managed" or address not in ALLOWED_MANAGED:
            raise ValueError("Recovery plan contains an unsupported address, including unrelated or shared resources")
        if address in observed_managed:
            raise ValueError("Recovery plan contains a duplicate managed resource address")
        observed_managed.add(address)
        expected_type = _resource_type_from_address(address)
        if resource_type != expected_type:
            raise ValueError("Recovery plan resource type does not match its source-declared address")
        if actions != ["delete"]:
            raise ValueError("Recovery plan must contain only direct managed deletes; no-op, update, replacement, and unknown actions are rejected")
        before = change.get("before")
        if not isinstance(before, dict):
            raise ValueError("Recovery plan delete is missing its prior resource identity")
        if resource_type == "aws_s3_bucket":
            _validate_bucket(address, before, state_bucket_name)
        if resource_type == "aws_iam_openid_connect_provider":
            if before.get("url") != "https://token.actions.githubusercontent.com":
                raise ValueError("Recovery plan OIDC provider URL does not match the PawLocal GitHub provider")
        if resource_type == "aws_dsql_cluster" and before.get("deletion_protection_enabled") is not False:
            raise ValueError("DSQL deletion protection must be disabled by a separately approved Terraform stage before destroy")
        deleted.append(address)

    missing = REQUIRED_MANAGED - observed_managed
    if missing:
        raise ValueError("Recovery plan is incomplete; required source-owned resources are missing: " + ", ".join(sorted(missing)))
    if not (observed_managed & REQUIRED_PRODUCTION_FRONTEND) == REQUIRED_PRODUCTION_FRONTEND:
        raise ValueError("Recovery plan does not include the complete production frontend resource set")
    if sum(address.startswith("aws_iam_openid_connect_provider.github") for address in observed_managed) != 1:
        raise ValueError("Recovery plan must delete exactly one legacy GitHub OIDC provider")

    lines = [
        "### Legacy Terraform state recovery plan",
        "",
        f"Managed resources to delete: {len(deleted)}",
        f"Non-mutating data reads: {non_mutating}",
        "",
        "| Exact Terraform address | Action |",
        "|---|---|",
        *(f"| `{address}` | `delete` |" for address in sorted(deleted)),
        "",
        "Only source-declared PawLocal root and fullstack addresses are accepted. Attribute values are omitted.",
        "The Terraform backend bucket is protected, optional audit/shared resources are rejected, and the complete production frontend plus one legacy GitHub OIDC provider are required.",
    ]
    return "\n".join(lines)


def main() -> None:
    args = parse_args()
    try:
        print(render(json.load(sys.stdin), args.state_bucket_name))
    except (json.JSONDecodeError, ValueError) as exc:
        print(f"Recovery plan review rejected: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
