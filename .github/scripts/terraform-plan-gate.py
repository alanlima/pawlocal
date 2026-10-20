#!/usr/bin/env python3
"""Validate a Terraform plan summary before a protected apply or destroy."""

import json
import os
import pathlib
import re
import sys


plan_path = pathlib.Path(sys.argv[1])
mode = os.environ["PLAN_MODE"]
expected_account = os.environ["PAWLOCAL_AWS_ACCOUNT_ID"]
state_key = os.environ["TF_STATE_KEY"]

with plan_path.open(encoding="utf-8") as source:
    plan = json.load(source)

if plan.get("applyable") is not True:
    raise SystemExit("Terraform plan is not marked applyable")
if plan.get("complete") is not True:
    raise SystemExit("Terraform plan is incomplete")
if plan.get("errored") is not False:
    raise SystemExit("Terraform plan reports an error")
if plan.get("deferred_changes"):
    raise SystemExit("Terraform plan contains deferred changes")


def find_account(module):
    for resource in module.get("resources", []):
        if (
            resource.get("mode") == "data"
            and resource.get("type") == "aws_caller_identity"
            and resource.get("name") == "current"
        ):
            return resource.get("values", {}).get("account_id")
    for child in module.get("child_modules", []):
        account = find_account(child)
        if account:
            return account
    return None


actual_account = find_account(plan.get("planned_values", {}).get("root_module", {}))
if actual_account != expected_account:
    raise SystemExit("Terraform resolved a different AWS account than configured")


def declared_resource_names(folder):
    names = set()
    for path in pathlib.Path(folder).glob("*.tf"):
        for match in re.finditer(r'\bresource\s+"([^\"]+)"\s+"([^\"]+)"', path.read_text(encoding="utf-8")):
            names.add(f"{match.group(1)}.{match.group(2)}")
    return names


root_resources = declared_resource_names(".")
module_resources = declared_resource_names("fullstack")
root_count_resources = {"aws_iam_openid_connect_provider.github"}
module_for_each_resources = {
    "random_id.bucket_suffix", "aws_s3_bucket.frontend", "aws_s3_bucket_ownership_controls.frontend",
    "aws_s3_bucket_public_access_block.frontend", "aws_s3_bucket_server_side_encryption_configuration.frontend",
    "aws_cloudfront_origin_access_control.frontend", "aws_dsql_cluster.app", "aws_lightsail_certificate.api",
    "aws_route53_record.api_certificate_validation", "aws_lightsail_container_service.api",
    "aws_iam_role.dsql_runtime", "aws_iam_role_policy.dsql_runtime",
    "aws_lightsail_container_service_deployment_version.api", "aws_dsql_cluster_policy.api_connect",
    "aws_route53_record.api", "aws_cloudfront_distribution.app", "aws_cloudfront_function.spa",
    "aws_s3_bucket_policy.frontend", "aws_route53_record.frontend_a", "aws_route53_record.frontend_aaaa",
    "random_id.cognito_domain_suffix", "aws_cognito_user_pool.app", "aws_cognito_user_pool_domain.app",
    "aws_cognito_user_pool_client.app", "aws_iam_role.github_deploy", "aws_iam_role_policy.github_deploy",
    "aws_iam_role.github_terraform_deploy", "aws_iam_role_policy.github_terraform_deploy",
    "terraform_data.app_dsql_role",
}
module_count_resources = {
    "aws_iam_openid_connect_provider.github", "aws_s3_bucket.cloudtrail",
    "aws_s3_bucket_lifecycle_configuration.cloudtrail", "aws_s3_bucket_public_access_block.cloudtrail",
    "aws_s3_bucket_server_side_encryption_configuration.cloudtrail", "aws_s3_bucket_policy.cloudtrail",
    "aws_cloudtrail.dsql_auth", "aws_cloudwatch_event_rule.dsql_auth", "aws_sns_topic.dsql_auth",
    "aws_sns_topic_subscription.dsql_auth_email", "aws_cloudwatch_event_target.dsql_auth",
    "aws_sns_topic_policy.dsql_auth",
}
safe_identity_keys = (
    "id", "arn", "name", "bucket", "cluster_identifier", "distribution_id",
    "record_name", "domain_name", "service_name", "user_pool_id", "user_pool_domain",
    "client_id", "role_name", "function_name", "certificate_name", "trail_name",
    "name_prefix", "prefix",
)


def known_address(address):
    if address.startswith("module.fullstack."):
        resource_address = address.removeprefix("module.fullstack.")
        names = module_resources
        count_names = module_count_resources
        for_each_names = module_for_each_resources
    elif address.startswith("module."):
        return False
    else:
        resource_address = address
        names = root_resources
        count_names = root_count_resources
        for_each_names = set()
    for name in names:
        if name in for_each_names:
            suffix = r'\["(?:development|production)"\]'
        elif name in count_names:
            suffix = r"\[0\]"
        else:
            suffix = ""
        if re.fullmatch(re.escape(name) + suffix, resource_address):
            return True
    return False


changes = []
totals = {"create": 0, "update": 0, "delete": 0, "replace": 0}
for item in plan.get("resource_changes", []):
    actions = item.get("change", {}).get("actions", [])
    if actions == ["no-op"] or not actions:
        continue
    address = item.get("address", "<unknown>")
    if mode == "destroy":
        if actions != ["delete"]:
            raise SystemExit(f"Destroy plan contains a non-delete action at {address}")
        if not known_address(address):
            raise SystemExit(f"Destroy plan contains an address outside the current Terraform roots: {address}")
    before = item.get("change", {}).get("before") or {}
    identity = {key: before[key] for key in safe_identity_keys if isinstance(before, dict) and before.get(key) is not None}
    if mode == "destroy" and not identity:
        raise SystemExit(f"Destroy plan has no reviewable remote identifier for {address}")
    changes.append((address, actions, identity))
    if actions == ["create"]:
        totals["create"] += 1
    elif actions == ["update"]:
        totals["update"] += 1
    elif actions == ["delete"]:
        totals["delete"] += 1
    elif actions in (["delete", "create"], ["create", "delete"]):
        totals["replace"] += 1

output_changes = plan.get("output_changes", {})
stage = os.environ.get("PLAN_STAGE", mode)
print(f"## Terraform {mode} plan: {stage}")
print()
print(f"Commit: `{os.environ['GITHUB_SHA']}`  ")
print(f"Account: `{actual_account}`  ")
print(f"State: `{state_key}`  ")
print("Plan is complete and applyable; attribute values are omitted except allowlisted resource identifiers.")
print()
print(f"Creates: {totals['create']} · Updates: {totals['update']} · Deletes: {totals['delete']} · Replacements: {totals['replace']}")
print()
if changes:
    print("| Resource address | Actions | Reviewable identifiers |")
    print("|---|---|---|")
    for address, actions, identity in changes:
        identifier_text = ", ".join(
            f"{key}=`{str(value).replace('|', '&#124;').replace('`', '&#96;').replace(chr(10), ' ')}`"
            for key, value in sorted(identity.items())
        ) or "none"
        print(f"| `{address}` | `{', '.join(actions)}` | {identifier_text} |")
else:
    print("No managed resource changes.")
if output_changes:
    print()
    print("Output changes (values omitted):")
    for name, change in sorted(output_changes.items()):
        actions = change.get("actions", [])
        print(f"- `{name}`: `{', '.join(actions)}`")
print()
print(f"Deferred changes: {len(plan.get('deferred_changes', []))}")
