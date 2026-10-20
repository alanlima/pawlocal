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
        self.assertIn("resources = [each.value.cluster_arn]", permissions)
        self.assertIn('identity_app_role_boundary["development"].arn', roles)
        self.assertIn('identity_app_role_boundary["production"].arn', roles)
        self.assertIn('to   = aws_iam_policy.identity_app_role_boundary["development"]', permissions)

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

    def test_cloudfront_tagged_create_permission_is_temporary_and_handed_off(self) -> None:
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
            self.assertIn('"cloudfront:CreateFunction"', source)
            self.assertNotIn("cloudfront:UntagResource", source)
        self.assertIn('sid       = "TagOnlyNewEnvironmentCloudFrontDistribution"', module_permissions)
        self.assertIn('sid       = "ManageExactEnvironmentCloudFrontFunction"', module_permissions)
        self.assertIn('variable = "aws:TagKeys"', module_permissions)
        for tag_name in ("managedby", "component", "workload", "costcenter"):
            self.assertIn(f'variable = "aws:RequestTag/{tag_name}"', module_permissions)
        self.assertIn(
            'var.cloudfront_distribution_arn == "" && var.cloudfront_oac_arn == ""',
            module_permissions,
        )
        self.assertIn('var.development_distribution_arn == "" && var.development_oac_arn == ""', boundary)
        self.assertIn('var.production_distribution_arn == "" && var.production_oac_arn == ""', boundary)
        self.assertIn("tags                = local.common_tags", distribution)

    def test_environment_apply_boundaries_have_an_offline_size_and_isolation_gate(self) -> None:
        boundary = (ROOT / "infra/terraform/iam-bootstrap/environment_permissions.tf").read_text(
            encoding="utf-8"
        )
        test_file = (
            ROOT
            / "infra/terraform/iam-bootstrap/tests/environment_apply_boundary.tftest.hcl"
        ).read_text(encoding="utf-8")
        workflow = (ROOT / ".github/workflows/terraform-ci.yml").read_text(encoding="utf-8")

        self.assertIn("environment_apply_boundary_max_bytes = 5500", boundary)
        self.assertIn(".minified_json", boundary)
        self.assertIn("length(policy.minified_json) < 6144", test_file)
        self.assertIn("iam:UpdateAssumeRolePolicy", test_file)
        self.assertIn("lightsail:UntagResource", test_file)
        self.assertIn("cloudfront:UntagResource", test_file)
        self.assertIn("terraform test -no-color", workflow)

    def test_lightsail_authorization_tags_are_one_time_and_cannot_be_removed(self) -> None:
        for path in (
            ROOT / "infra/terraform/modules/pawlocal-environment/iam.tf",
            ROOT / "infra/terraform/iam-bootstrap/environment_permissions.tf",
        ):
            source = path.read_text(encoding="utf-8")
            self.assertIn('"lightsail:TagResource"', source)
            self.assertIn('variable = "aws:ResourceTag/project"', source)
            self.assertIn('variable = "aws:ResourceTag/environment"', source)
            self.assertIn('values   = ["true"]', source)
            self.assertNotIn("lightsail:UntagResource", source)

    def test_plan_and_apply_use_different_matching_roles_and_exact_plan(self) -> None:
        source = (ROOT / ".github/workflows/terraform-environment.yml").read_text(encoding="utf-8")
        bootstrap = (ROOT / "infra/terraform/iam-bootstrap/main.tf").read_text(encoding="utf-8")
        self.assertIn("pawlocal-${{ inputs.environment }}-terraform-plan", source)
        self.assertIn("pawlocal-${{ inputs.environment }}-terraform-apply", source)
        self.assertIn('subject_environment = "${env}-plan"', bootstrap)
        self.assertIn('environment:${each.value.subject_environment}', bootstrap)
        self.assertIn("terraform-plan-metadata.py verify", source)
        self.assertIn('terraform -chdir="$TF_ROOT" apply', source)
        self.assertNotIn("-auto-approve", source)
        self.assertIn("environment: ${{ inputs.environment }}-apply", source)
        self.assertIn("pawlocal-${each.value.environment}-github-deploy", bootstrap)
        self.assertIn("pawlocal-${each.value.environment}-dsql-runtime", bootstrap)
        self.assertIn("ReadExactMatchingEnvironmentPoliciesForRefresh", bootstrap)
        self.assertIn('"cloudfront:GetOriginAccessControl"', bootstrap)
        self.assertNotIn("pawlocal-production-terraform-deploy", bootstrap)

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

    def test_plan_guard_ignores_provider_data_reads(self) -> None:
        module = load_module(PLAN_GUARD, "terraform_environment_plan_data")
        rows = module.validate(
            {"resource_changes": [{"mode": "data", "type": "aws_caller_identity", "change": {"actions": ["read"]}}]},
            "development",
            False,
        )
        self.assertEqual(rows, [])

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
