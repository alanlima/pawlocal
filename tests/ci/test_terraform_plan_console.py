from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONSOLE = ROOT / ".github/scripts/terraform-plan-console.py"
WORKFLOW = ROOT / ".github/workflows/terraform-environment.yml"


class TerraformPlanConsoleTests(unittest.TestCase):
    def sample_plan(self) -> dict[str, object]:
        account_id = "1" * 12
        return {
            "terraform_version": "1.14.3",
            "variables": {
                "root_domain": {"value": "private.example.invalid"},
                "route53_zone_id": {"value": "PRIVATEZONE123"},
                "certificate": {"value": f"arn:aws:acm:region:{account_id}:certificate/private"},
                "token": {"value": "short-secret"},
            },
            "resource_changes": [
                {
                    "address": "module.pawlocal.aws_s3_bucket.frontend",
                    "type": "aws_s3_bucket",
                    "action_reason": "replace_because_tainted",
                    "change": {
                        "actions": ["delete", "create"],
                        "before": {"bucket": "private-bucket-name"},
                        "after": {"bucket": "private-bucket-name"},
                    },
                },
                {
                    "address": "module.pawlocal.aws_dsql_cluster.application",
                    "type": "aws_dsql_cluster",
                    "change": {
                        "actions": ["create"],
                        "after": {"arn": f"arn:aws:dsql:region:{account_id}:cluster/private"},
                    },
                },
                {
                    "address": "module.pawlocal.private_resource_name.secret",
                    "type": "private_resource_name",
                    "action_reason": "private_reason",
                    "change": {"actions": ["update"], "after": {"value": "Authorization-private"}},
                },
                {
                    "address": "data.aws_caller_identity.current",
                    "mode": "data",
                    "type": "aws_caller_identity",
                    "change": {"actions": ["read"], "after": {"account_id": account_id}},
                },
            ],
            "output_changes": {"private_output": {"after": "private-output-value"}},
        }

    def run_console(self) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as directory:
            plan = Path(directory) / "plan.json"
            plan.write_text(json.dumps(self.sample_plan()), encoding="utf-8")
            return subprocess.run(
                [sys.executable, str(CONSOLE), str(plan), "--environment", "development"],
                check=True,
                capture_output=True,
                text=True,
            )

    def test_inventory_always_prints_only_value_free_allowlisted_plan_details(self) -> None:
        output = self.run_console().stdout
        self.assertIn("Saved Terraform plan diagnostic (sanitized)", output)
        self.assertIn("aws_s3_bucket | replace | tainted state requires replacement | 1", output)
        self.assertIn("aws_dsql_cluster | create | not reported | 1", output)
        self.assertIn("withheld_resource_type | update | not reported | 1", output)
        self.assertIn("Data reads: 1", output)
        for sensitive in (
            "1" * 12,
            "private.example.invalid",
            "PRIVATEZONE123",
            "private-bucket-name",
            "private_resource_name",
            "private_reason",
            "short-secret",
            "Authorization-private",
            "private-output-value",
            "module.pawlocal",
            "arn:aws",
        ):
            with self.subTest(sensitive=sensitive):
                self.assertNotIn(sensitive, output)

    def test_workflow_always_prints_sanitized_inventory_before_summary(self) -> None:
        workflow = WORKFLOW.read_text(encoding="utf-8")
        diagnostic = workflow.index("      - name: Print sanitized saved-plan diagnostics")
        raw = workflow.index("      - name: Print raw saved plan for diagnosis")
        summary = workflow.index(
            "      - name: Publish sanitized summary with ownership enforcement skipped for MVP"
        )
        self.assertLess(diagnostic, raw)
        self.assertLess(raw, summary)
        block = workflow[diagnostic:raw]
        self.assertNotIn("if:", block)
        self.assertIn("terraform-plan-console.py", block)
        for name in (
            "PAWLOCAL_AWS_ACCOUNT_ID",
            "PAWLOCAL_TF_STATE_BUCKET",
            "PLAN_PREFIX",
            "PLAN_TRANSFER_BUCKET",
            "TERRAFORM_ROLE_ARN",
            "TF_STATE_KEY",
            "TF_VAR_cloudfront_certificate_arn",
            "TF_VAR_root_domain",
            "TF_VAR_route53_zone_id",
        ):
            with self.subTest(name=name):
                self.assertIn(f'{name}: ""', block)

    def test_workflow_prints_raw_plan_only_when_diagnostics_are_enabled(self) -> None:
        workflow = WORKFLOW.read_text(encoding="utf-8")
        requirement = workflow.index(
            "      - name: Require exact-plan visibility while ownership enforcement is skipped"
        )
        raw = workflow.index("      - name: Print raw saved plan for diagnosis")
        summary = workflow.index(
            "      - name: Publish sanitized summary with ownership enforcement skipped for MVP"
        )
        self.assertLess(requirement, raw)
        block = workflow[raw:summary]
        self.assertIn("if: ${{ vars.PAWLOCAL_TERRAFORM_DIAGNOSTIC_LOGS == 'true' }}", block)
        self.assertIn("script --quiet --return", block)
        self.assertIn("--command=", block)
        self.assertIn('terraform -chdir=\\"$TF_ROOT\\" show tfplan', block)
        self.assertNotIn("-no-color", block)
        self.assertNotIn("terraform-plan-diagnostic.py", block)
        self.assertNotIn('TF_ROOT: ""', block)
        for name in (
            "AWS_ACCESS_KEY_ID",
            "AWS_SECRET_ACCESS_KEY",
            "AWS_SESSION_TOKEN",
            "PAWLOCAL_AWS_ACCOUNT_ID",
            "TF_VAR_cloudfront_certificate_arn",
            "TF_VAR_root_domain",
            "TF_VAR_route53_zone_id",
        ):
            with self.subTest(name=name):
                self.assertIn(f'{name}: ""', block)

        requirement_block = workflow[requirement:raw]
        self.assertIn("PAWLOCAL_TERRAFORM_DIAGNOSTIC_LOGS", requirement_block)
        self.assertIn("raw exact-plan diagnostics are enabled", requirement_block)
        self.assertIn("exit 1", requirement_block)

    def test_workflow_keeps_summary_and_skips_only_ownership_enforcement_for_mvp(self) -> None:
        workflow = WORKFLOW.read_text(encoding="utf-8")
        summary = workflow.index(
            "      - name: Publish sanitized summary with ownership enforcement skipped for MVP"
        )
        metadata = workflow.index("      - name: Bind exact plan metadata")
        block = workflow[summary:metadata]
        self.assertIn("terraform-environment-plan.py", block)
        self.assertIn("--skip-enforcement", block)
        self.assertIn('>> "$GITHUB_STEP_SUMMARY"', block)
        self.assertIn("#148", block)


if __name__ == "__main__":
    unittest.main()
