from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PLAN_GUARD = ROOT / ".github/scripts/terraform-environment-plan.py"
METADATA = ROOT / ".github/scripts/terraform-plan-metadata.py"


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class GreenfieldTerraformTests(unittest.TestCase):
    def test_active_terraform_roots_and_workflows_pin_the_local_review_version(self) -> None:
        version = "1.14.3"
        for relative_path in (
            "infra/terraform/iam-bootstrap/versions.tf",
            "infra/terraform/environments/development/versions.tf",
            "infra/terraform/environments/production/versions.tf",
            "infra/terraform/modules/pawlocal-environment/versions.tf",
        ):
            with self.subTest(path=relative_path):
                source = (ROOT / relative_path).read_text(encoding="utf-8")
                self.assertIn(f'required_version = "= {version}"', source)

        environment_workflow = (ROOT / ".github/workflows/terraform-environment.yml").read_text(
            encoding="utf-8"
        )
        ci_workflow = (ROOT / ".github/workflows/terraform-ci.yml").read_text(encoding="utf-8")
        self.assertIn(f"TERRAFORM_VERSION: {version}", environment_workflow)
        self.assertIn(f"terraform_version: {version}", ci_workflow)

    def test_roots_and_backend_keys_are_explicit_and_distinct(self) -> None:
        for environment in ("development", "production"):
            root = ROOT / f"infra/terraform/environments/{environment}"
            self.assertTrue((root / "versions.tf").is_file())
            self.assertIn('backend "s3" {}', (root / "versions.tf").read_text(encoding="utf-8"))
        workflow = (ROOT / ".github/workflows/terraform-environment.yml").read_text(encoding="utf-8")
        self.assertIn("TF_ROOT: infra/terraform/environments/${{ inputs.environment }}", workflow)
        self.assertIn("TF_STATE_KEY: pawlocal/${{ inputs.environment }}/terraform.tfstate", workflow)
        self.assertNotIn("pawlocal/terraform.tfstate", workflow)

    def test_environment_module_does_not_manage_role_identity_or_trust(self) -> None:
        source = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (ROOT / "infra/terraform/modules/pawlocal-environment").glob("*.tf")
        )
        self.assertNotIn('resource "aws_iam_role"', source)
        self.assertNotIn('resource "aws_iam_openid_connect_provider"', source)
        self.assertNotIn("assume_role_policy", source)
        self.assertIn('resource "aws_iam_policy" "application"', source)
        self.assertIn('resource "aws_iam_role_policy_attachment" "application"', source)

    def test_lightsail_names_use_one_suffix_map_without_bootstrap_duplicates(self) -> None:
        module = (ROOT / "infra/terraform/modules/pawlocal-environment/main.tf").read_text(
            encoding="utf-8"
        )
        bootstrap = (ROOT / "infra/terraform/iam-bootstrap/main.tf").read_text(encoding="utf-8")

        module_locals = module.split("locals {", 1)[1].split('resource "random_id"', 1)[0]
        bootstrap_environments = bootstrap.split("environments = {", 1)[1].split(
            "role_definitions", 1
        )[0]

        self.assertEqual(module_locals.count("resource_suffixes = {"), 1)
        self.assertIn('cert              = "cert"', module_locals)
        self.assertIn('container_service = "api"', module_locals)
        self.assertIn(
            'cert              = "${local.resource_name_prefix}-${local.resource_suffixes.container_service}-${local.resource_suffixes.cert}"',
            module_locals,
        )
        self.assertIn(
            'container_service = "${local.resource_name_prefix}-${local.resource_suffixes.container_service}"',
            module_locals,
        )
        self.assertNotIn("certificate_name", module_locals)
        self.assertNotIn("service_name", module_locals)
        self.assertNotIn("certificate", bootstrap_environments)
        self.assertNotIn("service_name", bootstrap_environments)

    def test_environment_creation_roots_wait_for_application_permissions(self) -> None:
        module = (ROOT / "infra/terraform/modules/pawlocal-environment/main.tf").read_text(
            encoding="utf-8"
        )
        versions = [
            ROOT / "infra/terraform/modules/pawlocal-environment/versions.tf",
            ROOT / "infra/terraform/environments/development/versions.tf",
            ROOT / "infra/terraform/environments/production/versions.tf",
        ]

        barrier = module.split('resource "time_sleep" "application_permissions_propagation" {', 1)[1].split(
            "\n}", 1
        )[0]
        self.assertIn('create_duration = "30s"', barrier)
        self.assertIn(
            "application_policy_sha256 = sha256(data.aws_iam_policy_document.application.json)",
            barrier,
        )
        self.assertIn("depends_on = [aws_iam_role_policy_attachment.application]", barrier)

        creation_roots = (
            ("aws_s3_bucket", "frontend"),
            ("aws_cloudfront_origin_access_control", "frontend"),
            ("aws_cloudfront_function", "spa"),
            ("aws_dsql_cluster", "application"),
            ("aws_lightsail_certificate", "api"),
            ("aws_cognito_user_pool", "application"),
        )
        for resource_type, resource_name in creation_roots:
            with self.subTest(resource=f"{resource_type}.{resource_name}"):
                block = module.split(f'resource "{resource_type}" "{resource_name}" {{', 1)[1].split(
                    '\nresource "', 1
                )[0]
                self.assertIn(
                    "depends_on",
                    block,
                )
                self.assertIn("time_sleep.application_permissions_propagation", block)
                self.assertNotIn("aws_iam_role_policy_attachment.application]", block)

        for path in versions:
            with self.subTest(path=path):
                source = path.read_text(encoding="utf-8")
                self.assertIn('source  = "hashicorp/time"', source)
                self.assertIn('version = "= 0.13.1"', source)

        for environment in ("development", "production"):
            with self.subTest(environment=environment):
                root = ROOT / f"infra/terraform/environments/{environment}"
                self.assertIn(
                    'source = "../../modules/pawlocal-environment"',
                    (root / "main.tf").read_text(encoding="utf-8"),
                )
                self.assertIn(
                    'provider "registry.terraform.io/hashicorp/time"',
                    (root / ".terraform.lock.hcl").read_text(encoding="utf-8"),
                )

    def test_bootstrap_declaratively_imports_only_verified_development_role(self) -> None:
        source = (ROOT / "infra/terraform/iam-bootstrap/identity_roles.tf").read_text(encoding="utf-8")
        self.assertIn("import_existing_development_deploy_role", source)
        import_block = source.split("import {", 1)[1].split("\n}", 1)[0]
        self.assertIn("development_frontend", import_block)
        self.assertNotIn("production_frontend =", import_block)

    def test_bootstrap_app_role_boundaries_are_environment_specific(self) -> None:
        permissions = (ROOT / "infra/terraform/iam-bootstrap/identity_permissions.tf").read_text(encoding="utf-8")
        roles = (ROOT / "infra/terraform/iam-bootstrap/identity_roles.tf").read_text(encoding="utf-8")
        self.assertIn("for_each = local.identity_environment_resources", permissions)
        self.assertIn('s3:::pawlocal-${environment}-*', permissions)
        self.assertIn(':cloudfront::${data.aws_caller_identity.current.account_id}:distribution/*', permissions)
        self.assertIn(':dsql:${var.aws_region}:${data.aws_caller_identity.current.account_id}:cluster/*', permissions)
        self.assertIn("resources = [each.value.cluster_arn]", permissions)
        self.assertIn('variable = "aws:ResourceTag/environment"', permissions)
        self.assertNotIn("PENDING", permissions)
        self.assertNotIn("identity_scope_pending", permissions)
        self.assertIn('identity_app_role_boundary["development"].arn', roles)
        self.assertIn('identity_app_role_boundary["production"].arn', roles)
        self.assertIn('to   = aws_iam_policy.identity_app_role_boundary["development"]', permissions)

    def test_environment_owned_publisher_and_runtime_policies_remain_exact(self) -> None:
        environment = (ROOT / "infra/terraform/modules/pawlocal-environment/iam.tf").read_text(
            encoding="utf-8"
        )
        self.assertIn('resources = [aws_s3_bucket.frontend.arn]', environment)
        self.assertIn('resources = ["${aws_s3_bucket.frontend.arn}/*"]', environment)
        self.assertIn('resources = [aws_cloudfront_distribution.frontend.arn]', environment)
        self.assertIn('resources = [aws_dsql_cluster.application.arn]', environment)

    def test_existing_development_identity_boundary_keeps_state_compatible_description(self) -> None:
        permissions = (ROOT / "infra/terraform/iam-bootstrap/identity_permissions.tf").read_text(
            encoding="utf-8"
        )
        self.assertIn("identity_app_role_boundary_descriptions = {", permissions)
        self.assertIn(
            'development = "Permissions ceiling for the three fixed PawLocal app identity roles."',
            permissions,
        )
        self.assertIn("description = local.identity_app_role_boundary_descriptions[each.key]", permissions)

    def test_bootstrap_removes_duplicate_app_policies_and_environment_roots_are_sole_owners(self) -> None:
        bootstrap_permissions = (ROOT / "infra/terraform/iam-bootstrap/identity_permissions.tf").read_text(
            encoding="utf-8"
        )
        bootstrap_roles = (ROOT / "infra/terraform/iam-bootstrap/identity_roles.tf").read_text(
            encoding="utf-8"
        )
        environment = (ROOT / "infra/terraform/modules/pawlocal-environment/main.tf").read_text(
            encoding="utf-8"
        )
        for name in (
            "identity_development_frontend",
            "identity_production_frontend",
            "identity_development_runtime",
            "identity_production_runtime",
        ):
            with self.subTest(name=name):
                self.assertNotIn(f'resource "aws_iam_policy" "{name}"', bootstrap_permissions)
                self.assertIn(f"from = aws_iam_policy.{name}", bootstrap_permissions)
        self.assertEqual(bootstrap_permissions.count("destroy = true"), 4)
        self.assertNotIn('output "identity_managed_policy_arns"', bootstrap_roles)
        self.assertIn('output "identity_app_boundary_arns"', bootstrap_roles)
        self.assertIn('resource "aws_iam_policy" "application"', environment)
        self.assertIn('resource "aws_iam_policy" "frontend_publish"', environment)
        self.assertIn('resource "aws_iam_policy" "runtime"', environment)
        self.assertIn('resource "aws_iam_policy" "dsql_setup"', environment)

    def test_protected_dsql_setup_permissions_and_workflow_are_fail_closed(self) -> None:
        permissions = (
            ROOT / "infra/terraform/modules/pawlocal-environment/iam.tf"
        ).read_text(encoding="utf-8")
        boundary = (
            ROOT / "infra/terraform/iam-bootstrap/environment_permissions.tf"
        ).read_text(encoding="utf-8")
        roles = (ROOT / "infra/terraform/iam-bootstrap/identity_roles.tf").read_text(
            encoding="utf-8"
        )
        workflow = (ROOT / ".github/workflows/terraform-environment.yml").read_text(
            encoding="utf-8"
        )

        self.assertIn('actions   = ["dsql:DbConnectAdmin"]', permissions)
        self.assertIn('actions   = ["sts:AssumeRole"]', permissions)
        self.assertIn('"dsql:DbConnectAdmin"', boundary)
        self.assertIn('"sts:AssumeRole"', boundary)
        self.assertIn("AllowExactDevelopmentTerraformApply", roles)
        self.assertIn("AllowExactProductionTerraformApply", roles)
        self.assertIn("requirements-dsql-post-apply.txt", workflow)
        requirements = (
            ROOT / ".github/scripts/requirements-dsql-post-apply.txt"
        ).read_text(encoding="utf-8")
        self.assertIn("psycopg-pool==3.3.3", requirements)
        self.assertIn("import aurora_dsql_psycopg.pool", workflow)
        self.assertIn("group: pawlocal-terraform-${{ inputs.environment }}", workflow)
        self.assertIn("cancel-in-progress: false", workflow)
        self.assertIn('apply -input=false -lock-timeout=5m', workflow)
        self.assertLess(
            workflow.index("Install pinned Aurora DSQL setup dependencies"),
            workflow.index("terraform -chdir=\"$TF_ROOT\" apply"),
        )
        self.assertFalse((ROOT / "ops/bootstrap-development-dsql-role.ps1").exists())

    def test_cloudfront_boundary_is_stable_while_environment_policy_is_exact(self) -> None:
        module_permissions = (ROOT / "infra/terraform/modules/pawlocal-environment/iam.tf").read_text(
            encoding="utf-8"
        )
        boundary = (ROOT / "infra/terraform/iam-bootstrap/environment_permissions.tf").read_text(
            encoding="utf-8"
        )
        distribution = (ROOT / "infra/terraform/modules/pawlocal-environment/main.tf").read_text(
            encoding="utf-8"
        )
        for source in (module_permissions, boundary):
            self.assertIn('"cloudfront:TagResource"', source)
            self.assertIn('variable = "aws:RequestTag/environment"', source)
            self.assertNotIn("cloudfront:UntagResource", source)
        self.assertIn('"cloudfront:CreateFunction"', module_permissions)
        self.assertIn('"cloudfront:*Function"', boundary)
        self.assertIn('sid     = "TagOnlyNewEnvironmentResources"', module_permissions)
        self.assertIn('sid       = "ManageExactEnvironmentCloudFrontFunction"', module_permissions)
        self.assertIn('variable = "aws:TagKeys"', module_permissions)
        for tag_name in ("managedby", "component", "workload", "costcenter"):
            self.assertIn(f'variable = "aws:RequestTag/{tag_name}"', module_permissions)
        self.assertIn(
            'var.cloudfront_distribution_arn == "" && var.cloudfront_oac_arn == ""',
            module_permissions,
        )
        for generated_input in (
            "development_distribution_arn",
            "development_oac_arn",
            "production_distribution_arn",
            "production_oac_arn",
        ):
            self.assertNotIn(generated_input, boundary)
        self.assertIn(":distribution/*", boundary)
        self.assertIn(":origin-access-control/*", boundary)
        self.assertIn(
            'actions   = ["cloudfront:DeleteDistribution", "cloudfront:UpdateDistribution"]',
            boundary,
        )
        self.assertIn(
            'actions   = ["cloudfront:DeleteOriginAccessControl", "cloudfront:UpdateOriginAccessControl"]',
            boundary,
        )
        self.assertIn("tags                = local.common_tags", distribution)

    def test_tagged_create_permissions_match_provider_dependencies(self) -> None:
        module_permissions = (ROOT / "infra/terraform/modules/pawlocal-environment/iam.tf").read_text(
            encoding="utf-8"
        )
        module_main = (ROOT / "infra/terraform/modules/pawlocal-environment/main.tf").read_text(
            encoding="utf-8"
        )
        boundary = (ROOT / "infra/terraform/iam-bootstrap/environment_permissions.tf").read_text(
            encoding="utf-8"
        )
        baseline = (ROOT / "infra/terraform/iam-bootstrap/main.tf").read_text(encoding="utf-8")
        module_test = (
            ROOT
            / "infra/terraform/modules/pawlocal-environment/tests/tagged_create_permissions.tftest.hcl"
        ).read_text(encoding="utf-8")

        for source in (module_permissions, boundary):
            for action in (
                "s3:TagResource",
                "dsql:TagResource",
                "lightsail:TagResource",
                "cognito-idp:TagResource",
                "cloudfront:TagResource",
            ):
                self.assertIn(f'"{action}"', source)
            self.assertIn('variable = "aws:RequestTag/project"', source)
            self.assertIn('variable = "aws:RequestTag/environment"', source)
            self.assertNotIn("lightsail:UntagResource", source)
            self.assertNotIn("cloudfront:UntagResource", source)

        self.assertIn('["s3:CreateBucket", "s3:TagResource"]', module_permissions)
        self.assertIn('["s3:CreateBucket", "s3:TagResource"]', boundary)
        self.assertIn('sid       = "CreateOnlyTaggedMatchingFrontendBucket"', module_permissions)
        self.assertIn('sid    = "ReadOnlyMatchingFrontendBucketBeforeTagHandoff"', module_permissions)
        self.assertIn('"s3:PutBucketTagging"', module_permissions)
        self.assertIn('"s3:ListTagsForResource"', module_permissions)
        self.assertIn('"s3:PutBucketPublicAccessBlock"', module_permissions)
        self.assertNotIn('"s3:PutPublicAccessBlock"', module_permissions)
        self.assertIn('"s3:GetBucket*", "s3:Get*Configuration"', boundary)
        self.assertNotIn('"s3:Get*"', boundary)
        self.assertIn('Certificate/*', module_permissions)
        self.assertIn('Certificate/*', boundary)
        self.assertIn('ContainerService/*', module_permissions)
        self.assertIn('ContainerService/*', boundary)
        self.assertNotIn('ContainerService/pawlocal-${var.environment}-api', module_permissions)
        self.assertNotIn('ContainerService/${each.value.service_name}', boundary)
        self.assertIn('userpool/*', module_permissions)
        self.assertIn('iam_managed_policy_max_bytes = 6144', module_main)
        self.assertIn('dsql_tags = merge(local.common_tags', module_main)
        self.assertIn('tags                        = local.dsql_tags', module_main)
        self.assertIn('sid       = "CreateAndTagOnlyNewEnvironmentDSQLCluster"', module_permissions)
        self.assertIn('for_each = local.dsql_tags', module_permissions)
        self.assertIn('environment_dsql_tags = {', boundary)
        self.assertIn('for_each = local.environment_dsql_tags[each.key]', boundary)
        self.assertIn(".minified_json", module_test)
        self.assertIn('"aws:RequestTag/Name"', module_test)
        self.assertIn('"aws:RequestTag/purpose"', module_test)
        self.assertIn('toset(keys(local.dsql_tags))', module_test)
        self.assertIn('"s3:ListTagsForResource"', baseline)

        for tag_name in ("project", "environment", "managedby", "component", "workload", "costcenter"):
            self.assertIn(f'variable = "aws:RequestTag/{tag_name}"', module_permissions)

    def test_environment_apply_boundaries_have_an_offline_size_and_isolation_gate(self) -> None:
        boundary = (ROOT / "infra/terraform/iam-bootstrap/environment_permissions.tf").read_text(
            encoding="utf-8"
        )
        test_file = (
            ROOT
            / "infra/terraform/iam-bootstrap/tests/environment_apply_boundary.tftest.hcl"
        ).read_text(encoding="utf-8")
        workflow = (ROOT / ".github/workflows/terraform-ci.yml").read_text(encoding="utf-8")

        self.assertIn("environment_apply_boundary_max_bytes = 6100", boundary)
        self.assertIn(".minified_json", boundary)
        self.assertIn("length(policy.minified_json) < 6144", test_file)
        self.assertIn('environment_apply_boundary["development"].minified_json) == 6040', test_file)
        self.assertIn('!contains(flatten([statement.Resource]), "*")', test_file)
        self.assertIn("Post-create DSQL and Lightsail mutations", test_file)
        self.assertIn("Post-create Cognito mutations", test_file)
        self.assertIn('keys(local.environment_dsql_tags[environment])', test_file)
        self.assertIn('"aws:RequestTag/Name"', test_file)
        self.assertIn('"aws:RequestTag/purpose"', test_file)
        self.assertIn("iam:UpdateAssumeRolePolicy", test_file)
        self.assertIn("lightsail:UntagResource", test_file)
        self.assertIn("cloudfront:UntagResource", test_file)
        self.assertIn("terraform test -no-color", workflow)
        self.assertIn("matrix.root == 'modules/pawlocal-environment'", workflow)

    def test_create_time_tagging_uses_request_tags_and_post_create_mutation_uses_resource_tags(self) -> None:
        for path in (
            ROOT / "infra/terraform/modules/pawlocal-environment/iam.tf",
            ROOT / "infra/terraform/iam-bootstrap/environment_permissions.tf",
        ):
            source = path.read_text(encoding="utf-8")
            self.assertIn('"lightsail:TagResource"', source)
            self.assertIn('variable = "aws:ResourceTag/project"', source)
            self.assertIn('variable = "aws:ResourceTag/environment"', source)
            self.assertNotIn('test     = "Null"', source)
            self.assertNotIn("lightsail:UntagResource", source)

    def test_plan_and_apply_use_different_matching_roles_and_exact_plan(self) -> None:
        source = (ROOT / ".github/workflows/terraform-environment.yml").read_text(encoding="utf-8")
        bootstrap = (ROOT / "infra/terraform/iam-bootstrap/main.tf").read_text(encoding="utf-8")
        self.assertIn("pawlocal-${{ inputs.environment }}-terraform-plan", source)
        self.assertIn("pawlocal-${{ inputs.environment }}-terraform-apply", source)
        self.assertIn('subject_environments = ["${env}-plan"]', bootstrap)
        self.assertIn("for subject_environment in each.value.subject_environments", bootstrap)
        self.assertIn('"production-destroy-prepare"', bootstrap)
        self.assertIn('"production-destroy"', bootstrap)
        self.assertIn("terraform-plan-metadata.py verify", source)
        self.assertIn('terraform -chdir="$TF_ROOT" apply', source)
        self.assertNotIn("-auto-approve", source)
        self.assertIn("environment: ${{ inputs.environment }}-apply", source)
        self.assertIn("pawlocal-${each.value.environment}-github-deploy", bootstrap)
        self.assertIn("pawlocal-${each.value.environment}-dsql-runtime", bootstrap)
        self.assertIn("ReadExactMatchingEnvironmentPoliciesForRefresh", bootstrap)
        self.assertIn('"cloudfront:GetOriginAccessControl"', bootstrap)
        self.assertNotIn("pawlocal-production-terraform-deploy", bootstrap)

    def test_environment_roles_can_poll_lightsail_provider_operations(self) -> None:
        bootstrap = (ROOT / "infra/terraform/iam-bootstrap/main.tf").read_text(encoding="utf-8")
        regional_reads = bootstrap.split("regional_read_actions = [", 1)[1].split("\n  ]", 1)[0]

        self.assertIn('"lightsail:GetOperation"', regional_reads)
        self.assertNotIn('"lightsail:GetOperations"', regional_reads)
        self.assertIn('"lightsail:GetOperations"', bootstrap)

    def test_apply_runs_only_after_a_successful_direct_plan(self) -> None:
        source = (ROOT / ".github/workflows/terraform-environment.yml").read_text(encoding="utf-8")
        apply_header = source.split("\n  apply:\n", 1)[1].split("\n    steps:\n", 1)[0]

        self.assertIn("needs: plan", apply_header)
        self.assertIn("if: ${{ !cancelled() && needs.plan.result == 'success' }}", apply_header)
        self.assertNotIn("always()", apply_header)
        self.assertNotIn("production-eligibility", apply_header)

    def test_release_workflows_call_matching_environment_root_workflow(self) -> None:
        development = (ROOT / ".github/workflows/fullstack-release.yml").read_text(encoding="utf-8")
        production = (ROOT / ".github/workflows/deploy-production.yml").read_text(encoding="utf-8")
        self.assertIn("uses: ./.github/workflows/terraform-environment.yml", development)
        self.assertIn("environment: development", development)
        self.assertIn("release_only: true", development)
        self.assertIn("uses: ./.github/workflows/terraform-environment.yml", production)
        self.assertIn("environment: production", production)
        self.assertIn("release_only: true", production)

    def test_plan_guard_rejects_roles_imports_deletes_and_non_release_changes(self) -> None:
        module = load_module(PLAN_GUARD, "terraform_environment_plan")
        with self.assertRaises(SystemExit):
            module.validate(
                {"resource_changes": [{"type": "aws_iam_role", "change": {"actions": ["create"]}}]},
                "development",
                False,
            )
        with self.assertRaises(SystemExit):
            module.validate(
                {"resource_changes": [{"type": "aws_s3_bucket", "change": {"actions": ["delete"]}}]},
                "development",
                False,
            )
        with self.assertRaises(SystemExit):
            module.validate(
                {"resource_changes": [{"type": "aws_s3_bucket", "importing": {}, "change": {"actions": ["create"]}}]},
                "development",
                False,
            )
        with self.assertRaises(SystemExit):
            module.validate(
                {"resource_changes": [{"type": "aws_s3_bucket", "change": {"actions": ["update"]}}]},
                "development",
                True,
            )

    def test_sanitized_plan_summary_omits_addresses_and_values(self) -> None:
        module = load_module(PLAN_GUARD, "terraform_environment_plan_summary")
        plan = {
            "resource_changes": [{
                "address": "module.pawlocal.aws_s3_bucket.frontend",
                "type": "aws_s3_bucket",
                "change": {"actions": ["create"], "after": {"bucket": "private-value"}},
            }]
        }
        summary = module.render(module.validate(plan, "development", False), "development")
        self.assertIn("aws_s3_bucket", summary)
        self.assertNotIn("module.pawlocal", summary)
        self.assertNotIn("private-value", summary)

    def test_summary_only_mode_skips_enforcement_but_marks_the_accepted_risk(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            plan = Path(directory) / "plan.json"
            plan.write_text(
                json.dumps({
                    "resource_changes": [{
                        "type": "aws_iam_role",
                        "change": {"actions": ["delete", "create"]},
                    }]
                }),
                encoding="utf-8",
            )
            result = subprocess.run(
                [
                    sys.executable,
                    str(PLAN_GUARD),
                    str(plan),
                    "--environment",
                    "development",
                    "--release-only",
                    "--skip-enforcement",
                ],
                check=True,
                capture_output=True,
                text=True,
            )
        self.assertIn("`aws_iam_role` | `replace` | 1", result.stdout)
        self.assertIn("plan ownership enforcement was skipped", result.stdout)

    def test_plan_guard_ignores_provider_data_reads(self) -> None:
        module = load_module(PLAN_GUARD, "terraform_environment_plan_data")
        rows = module.validate(
            {"resource_changes": [{"mode": "data", "type": "aws_caller_identity", "change": {"actions": ["read"]}}]},
            "development",
            False,
        )
        self.assertEqual(rows, [])

    def test_plan_guard_accepts_the_initial_permissions_propagation_barrier(self) -> None:
        module = load_module(PLAN_GUARD, "terraform_environment_plan_time_sleep")
        plan = {
            "resource_changes": [{
                "address": "module.pawlocal.time_sleep.application_permissions_propagation",
                "type": "time_sleep",
                "change": {"actions": ["create"]},
            }],
            "variables": {"environment": {"value": "development"}},
        }
        self.assertEqual(module.validate(plan, "development", False), [("time_sleep", "create")])
        rendered = module.render(module.validate(plan, "development", False), "development")
        self.assertIn("`time_sleep`", rendered)

    def test_plan_guard_accepts_only_the_expected_immutable_deployment_replacement(self) -> None:
        module = load_module(PLAN_GUARD, "terraform_environment_plan_replacement")
        plan = {
            "resource_changes": [{
                "type": "aws_lightsail_container_service_deployment_version",
                "change": {"actions": ["delete", "create"]},
            }],
            "variables": {"environment": {"value": "development"}},
        }
        self.assertEqual(
            module.validate(plan, "development", True),
            [("aws_lightsail_container_service_deployment_version", "replace")],
        )
        plan["resource_changes"][0]["type"] = "aws_lightsail_container_service"
        with self.assertRaises(SystemExit):
            module.validate(plan, "development", False)

    def test_plan_metadata_is_bound_to_run_and_digest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            plan = Path(directory) / "tfplan"
            metadata = Path(directory) / "metadata.json"
            plan.write_bytes(b"opaque plan")
            args = [
                "--environment", "development", "--state-key", "pawlocal/development/terraform.tfstate",
                "--account-id", "1" * 12, "--backend-bucket", "private-state", "--backend-region", "test-region-1",
                "--commit", "a" * 40, "--repository-id", "1", "--run-id", "2", "--run-attempt", "1",
            ]
            created = subprocess.run(
                [sys.executable, str(METADATA), "create", str(plan), str(metadata), *args],
                check=True, capture_output=True, text=True,
            ).stdout.strip()
            self.assertEqual(created, hashlib.sha256(plan.read_bytes()).hexdigest())
            subprocess.run(
                [sys.executable, str(METADATA), "verify", str(plan), str(metadata), *args],
                check=True, capture_output=True, text=True,
            )
            mismatched_target = list(args)
            mismatched_target[mismatched_target.index("private-state")] = "other-state"
            result = subprocess.run(
                [sys.executable, str(METADATA), "verify", str(plan), str(metadata), *mismatched_target],
                capture_output=True, text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            plan.write_bytes(b"changed")
            result = subprocess.run(
                [sys.executable, str(METADATA), "verify", str(plan), str(metadata), *args],
                capture_output=True, text=True,
            )
            self.assertNotEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
