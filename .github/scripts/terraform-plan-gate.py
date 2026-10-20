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


def destroy_preparation_guard(plan):
    """Allow only force_destroy updates, reporting safe paths for rejected changes."""
    allowed = {
        "aws_s3_bucket.site",
        'module.fullstack.aws_s3_bucket.frontend["development"]',
        'module.fullstack.aws_s3_bucket.frontend["production"]',
        'module.fullstack.aws_dsql_cluster.app["development"]',
        'module.fullstack.aws_dsql_cluster.app["production"]',
    }
    unexpected = []

    def top_level_changed_paths(before, after):
        if not isinstance(before, dict):
            before = {}
        if not isinstance(after, dict):
            after = {}
        paths = []
        for key in sorted(set(before) | set(after), key=str):
            if key == "force_destroy" or before.get(key) == after.get(key):
                continue
            # Terraform schema attribute names are safe to show. Avoid arbitrary
            # map keys, values, and nested paths, which could contain identifiers.
            safe_key = key if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", str(key)) else "<other>"
            paths.append(f"$.{safe_key}")
        return paths

    for item in plan.get("resource_changes", []):
        change = item.get("change", {})
        actions = change.get("actions", [])
        if actions == ["no-op"] or not actions:
            continue
        if item.get("mode") == "data" and actions == ["read"]:
            continue

        before = change.get("before") or {}
        after = change.get("after") or {}
        old = dict(before) if isinstance(before, dict) else before
        new = dict(after) if isinstance(after, dict) else after
        if isinstance(old, dict):
            old.pop("force_destroy", None)
        if isinstance(new, dict):
            new.pop("force_destroy", None)
        address = item.get("address", "")
        allowed_update = (
            address in allowed
            and actions == ["update"]
            and old == new
            and isinstance(after, dict)
            and after.get("force_destroy") is True
        )
        if not allowed_update:
            paths = top_level_changed_paths(before, after)
            resource_label = address if known_address(address) else "<unlisted resource>"
            safe_actions = [
                action if action in {"create", "read", "update", "delete", "forget", "import", "no-op"} else "<other>"
                for action in actions
                if isinstance(action, str)
            ]
            unexpected.append((resource_label, safe_actions, paths))

    if unexpected:
        print("Teardown preparation plan includes changes beyond force_destroy settings:", file=sys.stderr)
        for index, (resource_label, actions, paths) in enumerate(unexpected, start=1):
            print(f"- change {index}: resource={resource_label}; actions={','.join(actions) or '<none>'}; changed attribute paths={', '.join(paths) or '<none>'}", file=sys.stderr)
        raise SystemExit(1)


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


stage = os.environ.get("PLAN_STAGE", mode)
# The teardown-preparation plan is an apply-mode plan, but its account guard
# must use the existing state just like the subsequent destroy plan. Terraform
# may omit unchanged data sources such as aws_caller_identity from planned_values
# for this stage. The workflow separately verifies the live OIDC account.
uses_prior_state = mode == "destroy" or stage == "destroy-prepare"
account_values = (
    plan.get("prior_state", {}).get("values", {}).get("root_module", {})
    if uses_prior_state
    else plan.get("planned_values", {}).get("root_module", {})
)
actual_account = find_account(account_values)
if actual_account != expected_account:
    source = "prior Terraform state" if uses_prior_state else "planned values"
    raise SystemExit(f"Terraform {source} has a different or missing AWS account than configured")


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


if len(sys.argv) > 2 and sys.argv[2] == "--destroy-prepare-guard":
    destroy_preparation_guard(plan)
    raise SystemExit(0)


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
