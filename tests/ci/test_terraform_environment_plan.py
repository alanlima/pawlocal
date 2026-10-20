import importlib.util
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
    def test_accepts_allowlisted_environment_resource_and_noops(self):
        plan = {
            "resource_changes": [
                resource('module.fullstack.aws_s3_bucket.frontend["development"]', ["create"]),
                resource('module.fullstack.aws_dsql_cluster.app["development"]', ["no-op"]),
                resource('module.fullstack.data.aws_caller_identity.current', ["read"]),
            ]
        }
        self.assertEqual(
            VALIDATOR.validate_plan(plan, "development"),
            ['module.fullstack.aws_s3_bucket.frontend["development"]'],
        )

    def test_rejects_other_environment_shared_and_unclassified_resources(self):
        addresses = (
            'module.fullstack.aws_s3_bucket.frontend["production"]',
            'module.fullstack.aws_iam_role.github_terraform_plan["development"]',
            'module.fullstack.aws_cloudtrail.dsql_auth[0]',
            'aws_iam_openid_connect_provider.github[0]',
            'module.other.aws_s3_bucket.frontend["development"]',
        )
        for address in addresses:
            with self.subTest(address=address), self.assertRaises(VALIDATOR.UnsafePlan):
                VALIDATOR.validate_plan({"resource_changes": [resource(address, ["update"])]}, "development")

    def test_rejects_deletes_replacements_and_unclassified_actions(self):
        address = 'module.fullstack.aws_s3_bucket.frontend["development"]'
        for actions in (["delete"], ["delete", "create"], ["create", "delete"], ["forget"]):
            with self.subTest(actions=actions), self.assertRaises(VALIDATOR.UnsafePlan):
                VALIDATOR.validate_plan({"resource_changes": [resource(address, actions)]}, "development")

    def test_rejects_sensitive_values_in_resource_and_all_plan_output_sections(self):
        address = 'module.fullstack.aws_s3_bucket.frontend["development"]'
        plans = (
            {"resource_changes": [resource(address, ["update"], after_sensitive={"secret": True})]},
            {"resource_changes": [], "output_changes": {"token": {"after_sensitive": True}}},
            {"resource_changes": [], "planned_values": {"outputs": {"token": {"sensitive": True}}}},
            {"resource_changes": [], "prior_state": {"values": {"outputs": {"token": {"sensitive": True}}}}},
            {"resource_changes": [], "resource_drift": [resource(address, ["update"], before_sensitive={"password": True})]},
            {"resource_changes": [], "checks": [{"status": "pass", "sensitive": True}]},
        )
        for plan in plans:
            with self.subTest(plan=plan), self.assertRaises(VALIDATOR.UnsafePlan):
                VALIDATOR.validate_plan(plan, "development")

    def test_only_allows_the_known_non_secret_certificate_marker(self):
        address = 'module.fullstack.aws_cloudfront_distribution.app["development"]'
        plan = {
            "resource_changes": [
                resource(address, ["update"], after_sensitive={"viewer_certificate": {"acm_certificate_arn": True}})
            ]
        }
        self.assertEqual(VALIDATOR.validate_plan(plan, "development"), [address])
        plan["output_changes"] = {"certificate": {"after_sensitive": True}}
        with self.assertRaises(VALIDATOR.UnsafePlan):
            VALIDATOR.validate_plan(plan, "development")

    def test_malformed_plan_fails_closed(self):
        for plan in ({}, {"resource_changes": "invalid"}, {"resource_changes": [None]}, []):
            with self.subTest(plan=plan), self.assertRaises(VALIDATOR.UnsafePlan):
                VALIDATOR.validate_plan(plan, "development")


class TerraformWorkflowGateTests(unittest.TestCase):
    def test_workflow_is_explicitly_blocked_before_any_aws_or_terraform_action(self):
        workflow = (ROOT / ".github/workflows/terraform-infrastructure-deploy.yml").read_text()
        self.assertIn("bootstrap-blocker", workflow)
        self.assertIn("No authorized GitHub Actions Terraform bootstrap role", workflow)
        self.assertNotIn("id-token: write", workflow)
        self.assertNotIn("configure-aws-credentials", workflow)
        self.assertNotIn("terraform plan", workflow)
        self.assertNotIn("terraform apply", workflow)
        self.assertNotIn("upload-artifact", workflow)

    def test_removed_environment_plan_roles_cannot_create_prod_role_in_dev_plan(self):
        terraform = (ROOT / "infra/terraform/fullstack/main.tf").read_text(encoding="utf-8")
        outputs = (ROOT / "infra/terraform/fullstack/outputs.tf").read_text(encoding="utf-8")
        self.assertNotIn('resource "aws_iam_role" "github_terraform_plan"', terraform)
        self.assertNotIn('resource "aws_iam_role_policy" "github_terraform_plan"', terraform)
        self.assertNotIn("terraform_plan_role_arn", outputs)

    def test_validator_cli_rejects_shared_policy_change(self):
        plan = {"resource_changes": [resource('module.fullstack.aws_iam_policy.example["development"]', ["update"])]}
        with tempfile.TemporaryDirectory() as temp_dir:
            plan_path = Path(temp_dir) / "plan.json"
            plan_path.write_text(json.dumps(plan), encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--environment", "development", "--plan-json", str(plan_path)],
                capture_output=True, text=True, check=False,
            )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("not allowlisted", result.stderr)


if __name__ == "__main__":
    unittest.main()
