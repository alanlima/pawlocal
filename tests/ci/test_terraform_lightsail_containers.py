from __future__ import annotations

import importlib.util
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[2]
VALIDATOR_PATH = ROOT / "ops/validate-lightsail-container-plan.py"
SPEC = importlib.util.spec_from_file_location("container_plan_validator", VALIDATOR_PATH)
assert SPEC and SPEC.loader
VALIDATOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VALIDATOR)


class TerraformLightsailContainerTests(unittest.TestCase):
    image = "ghcr.io/alanlima/pawlocal-api@sha256:" + "a" * 64

    @staticmethod
    def plan(address: str, actions: list[str], image: str) -> dict:
        return {"resource_changes": [{"address": address, "change": {
            "actions": actions, "after": {"container": [{"image": image}]}
        }}]}

    def test_accepts_only_selected_environment_container_deployment(self) -> None:
        address = 'module.fullstack.aws_lightsail_container_service_deployment_version.api["development"]'
        VALIDATOR.validate(self.plan(address, ["update"], self.image), "development", self.image)

    def test_accepts_selected_immutable_container_deployment_replacement(self) -> None:
        address = 'module.fullstack.aws_lightsail_container_service_deployment_version.api["development"]'
        VALIDATOR.validate(self.plan(address, ["delete", "create"], self.image), "development", self.image)

    def test_rejects_unrelated_infrastructure_changes(self) -> None:
        plan = self.plan('module.fullstack.aws_lightsail_container_service.api["development"]', ["update"], self.image)
        with self.assertRaisesRegex(ValueError, "outside the selected"):
            VALIDATOR.validate(plan, "development", self.image)

    def test_rejects_changes_to_both_environments(self) -> None:
        plan = self.plan('module.fullstack.aws_lightsail_container_service_deployment_version.api["development"]', ["update"], self.image)
        plan["resource_changes"].append(self.plan('module.fullstack.aws_lightsail_container_service_deployment_version.api["production"]', ["update"], self.image)["resource_changes"][0])
        with self.assertRaisesRegex(ValueError, "outside the selected"):
            VALIDATOR.validate(plan, "development", self.image)

    def test_rejects_wrong_image_and_destroy(self) -> None:
        address = 'module.fullstack.aws_lightsail_container_service_deployment_version.api["production"]'
        with self.assertRaisesRegex(ValueError, "image digest"):
            VALIDATOR.validate(self.plan(address, ["update"], "other"), "production", self.image)
        with self.assertRaisesRegex(ValueError, "create, update, or replacement"):
            VALIDATOR.validate(self.plan(address, ["delete"], self.image), "production", self.image)

    def test_release_workflows_do_not_use_ssh_or_manual_ingress(self) -> None:
        for filename in ("fullstack-release.yml", "deploy-production.yml", "rollback-development.yml"):
            workflow = (ROOT / ".github/workflows" / filename).read_text(encoding="utf-8")
            self.assertIn("terraform-lightsail-container-deploy.sh", workflow)
            self.assertNotIn("terraform-lightsail-ingress.sh", workflow)
            self.assertNotIn("PAWLOCAL_DEPLOY_SSH_PRIVATE_KEY", workflow)
            self.assertNotIn("PAWLOCAL_DSQL_ACCESS_KEY_ID", workflow)

    def test_container_release_records_running_image_digest(self) -> None:
        deploy = (ROOT / "ops/terraform-lightsail-container-deploy.sh").read_text(encoding="utf-8")
        adapter = (ROOT / "ops/deployment-adapters/lightsail-dsql.sh").read_text(encoding="utf-8")
        self.assertIn("get-container-services", deploy)
        self.assertIn("currentDeployment", deploy)
        self.assertIn("PAWLOCAL_RELEASE_IMAGE_DIGEST", (ROOT / "infra/terraform/fullstack/main.tf").read_text(encoding="utf-8"))
        self.assertIn("running_image_digest", adapter)

    def test_development_rollback_requires_prior_verified_release(self) -> None:
        workflow = (ROOT / ".github/workflows/rollback-development.yml").read_text(encoding="utf-8")
        restore_step = workflow.split("      - name: Restore the selected frontend artifact\n", 1)[1].split("      - name:", 1)[0]
        verify_step = workflow.split("      - name: Verify restored development release\n", 1)[1].split("      - name:", 1)[0]
        adapter_variable = "PAWLOCAL_DEPLOY_ADAPTER_PATH: ${{ vars.PAWLOCAL_DEPLOY_ADAPTER_PATH }}"
        self.assertIn(adapter_variable, restore_step)
        self.assertIn(adapter_variable, verify_step)
        self.assertIn("No successful main-branch full-stack release", workflow)
        self.assertIn("no successful verified development deployment", workflow)
        self.assertIn("terraform-lightsail-container-deploy.sh development", workflow)
        self.assertIn("validate-release-metadata.py", workflow)

    def test_nullable_dsql_retention_validation_is_null_safe(self) -> None:
        for filename in ("infra/terraform/variables.tf", "infra/terraform/fullstack/variables.tf"):
            text = (ROOT / filename).read_text(encoding="utf-8")
            self.assertIn(
                "var.dsql_auth_retention_days == null ? true : (var.dsql_auth_retention_days > 0 && floor(var.dsql_auth_retention_days) == var.dsql_auth_retention_days)",
                text,
            )

    def test_terraform_release_role_scopes_cloudfront_and_cognito_refresh_reads(self) -> None:
        text = (ROOT / "infra/terraform/fullstack/main.tf").read_text(encoding="utf-8")
        frontend_publish = re.search(
            r'sid\s*=\s*"ListFrontendBucket"(.*?)(?=\n  statement|\n})',
            text,
            re.DOTALL,
        )
        self.assertIsNotNone(frontend_publish)
        self.assertIn('"s3:ListBucket"', frontend_publish.group(1))
        self.assertIn("aws_s3_bucket.frontend[each.key].arn", frontend_publish.group(1))
        self.assertNotIn('resources = ["*"]', frontend_publish.group(1))

        terraform_bucket_read = re.search(
            r'sid\s*=\s*"ListPawLocalFrontendBucketsForTerraformRefresh"(.*?)(?=\n  statement|\n})',
            text,
            re.DOTALL,
        )
        self.assertIsNotNone(terraform_bucket_read)
        self.assertIn('"s3:ListBucket"', terraform_bucket_read.group(1))
        self.assertIn('aws_s3_bucket.frontend["development"].arn', terraform_bucket_read.group(1))
        self.assertIn("var.additional_frontend_bucket_arns", terraform_bucket_read.group(1))
        self.assertNotIn('resources = ["*"]', terraform_bucket_read.group(1))

        acceleration_read = re.search(
            r'sid\s*=\s*"ReadPawLocalFrontendBucketAccelerationForTerraformRefresh"(.*?)(?=\n  statement|\n})',
            text,
            re.DOTALL,
        )
        self.assertIsNotNone(acceleration_read)
        self.assertIn('"s3:GetAccelerateConfiguration"', acceleration_read.group(1))
        self.assertIn('aws_s3_bucket.frontend["development"].arn', acceleration_read.group(1))
        self.assertIn("var.additional_frontend_bucket_arns", acceleration_read.group(1))
        self.assertNotIn('resources = ["*"]', acceleration_read.group(1))

        replication_read = re.search(
            r'dynamic\s+"statement"\s*\{(.*?ReadPawLocalFrontendBucketReplicationForTerraformRefresh.*?)\n  \}',
            text,
            re.DOTALL,
        )
        self.assertIsNotNone(replication_read)
        self.assertIn('for_each = each.key == "development" ? [true] : []', replication_read.group(1))
        self.assertIn('actions   = ["s3:GetReplicationConfiguration"]', replication_read.group(1))
        self.assertIn('aws_s3_bucket.frontend["development"].arn', replication_read.group(1))
        self.assertIn("var.additional_frontend_bucket_arns", replication_read.group(1))
        self.assertNotIn('resources = ["*"]', replication_read.group(1))
        root_module = (ROOT / "infra/terraform/main.tf").read_text(encoding="utf-8")
        self.assertIn("additional_frontend_bucket_arns = [aws_s3_bucket.site.arn]", root_module)

        cloudfront = re.search(
            r'sid\s*=\s*"DescribePawLocalSpaFunctionsForTerraformRefresh"(.*?)(?=\n  statement|\n})',
            text,
            re.DOTALL,
        )
        cognito = re.search(
            r'sid\s*=\s*"ReadPawLocalUserPoolMfaForTerraformRefresh"(.*?)(?=\n  statement|\n})',
            text,
            re.DOTALL,
        )
        self.assertIsNotNone(cloudfront)
        self.assertIn('"cloudfront:DescribeFunction"', cloudfront.group(1))
        self.assertIn("function.arn", cloudfront.group(1))
        self.assertIn("pawlocal-production-spa-routing", cloudfront.group(1))
        self.assertNotIn('resources = ["*"]', cloudfront.group(1))
        self.assertIsNotNone(cognito)
        self.assertIn('"cognito-idp:GetUserPoolMfaConfig"', cognito.group(1))
        self.assertIn("user_pool.arn", cognito.group(1))
        self.assertNotIn('resources = ["*"]', cognito.group(1))

    def test_dsql_role_bootstrap_fingerprint_is_line_ending_stable(self) -> None:
        text = (ROOT / "infra/terraform/fullstack/main.tf").read_text(encoding="utf-8")
        self.assertIn(
            'sha256(replace(replace(file("${path.module}/../../../backend/pawlocal/dsql_role_bootstrap.py"), "\\r\\n", "\\n"), "\\n", "\\r\\n"))',
            text,
        )


if __name__ == "__main__":
    unittest.main()
