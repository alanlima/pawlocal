import importlib.util
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "ops/validate-terraform-environment-plan.py"
SPEC = importlib.util.spec_from_file_location("terraform_env_plan", SCRIPT)
VALIDATOR = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = VALIDATOR
SPEC.loader.exec_module(VALIDATOR)


def resource(address, actions, before_sensitive=None, after_sensitive=None):
    return {
        "address": address,
        "change": {
            "actions": actions,
            "before_sensitive": before_sensitive or {},
            "after_sensitive": after_sensitive or {},
        },
    }


class TerraformEnvironmentPlanTests(unittest.TestCase):
    def test_accepts_only_selected_environment_create_or_update(self):
        plan = {
            "resource_changes": [
                resource('module.fullstack.aws_iam_role.example["development"]', ["update"]),
                resource('module.fullstack.aws_s3_bucket.example["development"]', ["create"]),
                resource('module.fullstack.aws_dsql_cluster.example["development"]', ["no-op"]),
            ]
        }
        self.assertEqual(
            VALIDATOR.validate_plan(plan, "development"),
            [
                'module.fullstack.aws_iam_role.example["development"]',
                'module.fullstack.aws_s3_bucket.example["development"]',
            ],
        )

    def test_rejects_other_environment_and_shared_resources(self):
        for address in (
            'module.fullstack.aws_s3_bucket.example["production"]',
            "aws_iam_openid_connect_provider.github[0]",
        ):
            with self.subTest(address=address), self.assertRaises(VALIDATOR.UnsafePlan):
                VALIDATOR.validate_plan(
                    {"resource_changes": [resource(address, ["update"])]}, "development"
                )

    def test_rejects_mixed_environment_address(self):
        plan = {
            "resource_changes": [
                resource(
                    'module.fullstack.aws_iam_policy.example["development"]["production"]',
                    ["update"],
                )
            ]
        }
        with self.assertRaises(VALIDATOR.UnsafePlan):
            VALIDATOR.validate_plan(plan, "development")

    def test_rejects_deletes_replacements_and_sensitive_values(self):
        address = 'module.fullstack.aws_resource.example["development"]'
        for actions in (["delete"], ["delete", "create"], ["create", "delete"]):
            with self.subTest(actions=actions), self.assertRaises(VALIDATOR.UnsafePlan):
                VALIDATOR.validate_plan({"resource_changes": [resource(address, actions)]}, "development")
        with self.assertRaises(VALIDATOR.UnsafePlan):
            VALIDATOR.validate_plan(
                {
                    "resource_changes": [
                        resource(address, ["update"], after_sensitive={"credential": True})
                    ]
                },
                "development",
            )

    def test_allows_only_known_non_secret_sensitive_certificate_arn(self):
        address = 'module.fullstack.aws_cloudfront_distribution.app["development"]'
        plan = {
            "resource_changes": [
                resource(
                    address,
                    ["update"],
                    after_sensitive={"viewer_certificate": {"acm_certificate_arn": True}},
                )
            ]
        }
        self.assertEqual(VALIDATOR.validate_plan(plan, "development"), [address])

    def test_rejects_malformed_plan(self):
        for plan in ({}, {"resource_changes": "invalid"}, {"resource_changes": [None]}):
            with self.subTest(plan=plan), self.assertRaises(VALIDATOR.UnsafePlan):
                VALIDATOR.validate_plan(plan, "development")


class TerraformWorkflowGateTests(unittest.TestCase):
    def test_workflow_orders_reviewed_dev_then_fresh_prod(self):
        workflow = (ROOT / ".github/workflows/terraform-infrastructure-deploy.yml").read_text()
        self.assertIn("environment: development-plan", workflow)
        self.assertIn("environment: development\n", workflow)
        self.assertIn("needs: apply-development", workflow)
        self.assertIn("needs: verify-development", workflow)
        self.assertIn("environment: production-plan", workflow)
        self.assertIn("environment: production\n", workflow)
        self.assertIn("terraform plan -input=false -lock-timeout=5m -no-color -out=development.tfplan", workflow)
        self.assertIn("terraform plan -input=false -lock-timeout=5m -no-color -out=production.tfplan", workflow)
        self.assertIn("terraform apply -input=false -lock-timeout=5m -no-color development.tfplan", workflow)
        self.assertIn("terraform apply -input=false -lock-timeout=5m -no-color production.tfplan", workflow)
        self.assertIn("retention-days: 1", workflow)
        self.assertIn("needs.plan-development.outputs.plan_sha256", workflow)
        self.assertIn("needs.plan-production.outputs.plan_sha256", workflow)
        self.assertNotIn("-target", workflow)
        self.assertNotIn("workflow_dispatch:\n  inputs:", workflow)

    def test_validator_cli_fails_closed_on_production_action_in_dev_plan(self):
        plan = {
            "resource_changes": [
                resource('module.fullstack.aws_iam_role.example["production"]', ["update"])
            ]
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            plan_path = Path(temp_dir) / "plan.json"
            plan_path.write_text(json.dumps(plan), encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--environment",
                    "development",
                    "--plan-json",
                    str(plan_path),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("not isolated", result.stderr)

    def test_artifact_checksum_verifier_accepts_exact_bytes_and_rejects_tampering(self):
        artifact_script = ROOT / "ops/verify-terraform-plan-artifact.py"
        payload = b"reviewed plan bytes"
        expected = hashlib.sha256(payload).hexdigest()
        with tempfile.TemporaryDirectory() as temp_dir:
            artifact = Path(temp_dir) / "saved.tfplan"
            artifact.write_bytes(payload)
            accepted = subprocess.run(
                [sys.executable, str(artifact_script), "--file", str(artifact), "--expected-sha256", expected],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(accepted.returncode, 0)
            artifact.write_bytes(payload + b"tampered")
            rejected = subprocess.run(
                [sys.executable, str(artifact_script), "--file", str(artifact), "--expected-sha256", expected],
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("mismatch", rejected.stderr)

    def test_terraform_plan_roles_are_environment_scoped_and_do_not_mutate_stack(self):
        terraform = (ROOT / "infra/terraform/fullstack/main.tf").read_text(encoding="utf-8")
        plan_role = terraform.split('resource "aws_iam_role" "github_terraform_plan"', 1)[1].split(
            'data "aws_iam_policy_document" "github_terraform_plan"', 1
        )[0]
        plan_policy = terraform.split('data "aws_iam_policy_document" "github_terraform_plan"', 1)[1].split(
            'resource "aws_iam_role_policy" "github_terraform_plan"', 1
        )[0]
        self.assertIn('environment:${each.key}-plan', terraform)
        self.assertIn('name               = "pawlocal-${each.key}-terraform-plan"', plan_role)
        self.assertNotIn('lightsail:CreateContainerServiceDeployment', plan_policy)
        self.assertNotIn('iam:Create', plan_policy)
        self.assertNotIn('iam:Put', plan_policy)
        self.assertIn('pawlocal/terraform.tfstate.tflock', plan_policy)


if __name__ == "__main__":
    unittest.main()
