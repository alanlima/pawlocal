from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
GATE = ROOT / ".github/scripts/terraform-plan-gate.py"
WORKFLOW = ROOT / ".github/workflows/terraform-current-stack-operations.yml"
SHARED_STATE_WRITERS = (
    ROOT / ".github/workflows/fullstack-release.yml",
    ROOT / ".github/workflows/deploy-production.yml",
    ROOT / ".github/workflows/rollback-development.yml",
    WORKFLOW,
)
AWS_ENABLED_JOBS = {
    "plan": "infrastructure-plan",
    "apply": "infrastructure-apply",
    "prepare-destroy": "infrastructure-apply",
    "destroy-plan": "infrastructure-plan",
    "destroy": "infrastructure-apply",
}
EXPECTED_ACCOUNT = "123456789012"


def account_state(account_id: str) -> dict[str, object]:
    return {
        "root_module": {
            "resources": [
                {
                    "mode": "data",
                    "type": "aws_caller_identity",
                    "name": "current",
                    "values": {"account_id": account_id},
                }
            ]
        }
    }


class TerraformCurrentStackWorkflowTests(unittest.TestCase):
    def run_gate(self, mode: str, plan: dict[str, object]) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as temporary:
            plan_path = Path(temporary) / "plan.json"
            plan_path.write_text(json.dumps(plan), encoding="utf-8")
            environment = os.environ.copy()
            environment.update(
                PLAN_MODE=mode,
                PAWLOCAL_AWS_ACCOUNT_ID=EXPECTED_ACCOUNT,
                TF_STATE_KEY="pawlocal/terraform.tfstate",
                GITHUB_SHA="test-commit",
            )
            return subprocess.run(
                [sys.executable, str(GATE), str(plan_path)],
                cwd=ROOT / "infra/terraform",
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )

    def test_destroy_account_is_checked_from_prior_state(self) -> None:
        result = self.run_gate(
            "destroy",
            {
                "applyable": True,
                "complete": True,
                "errored": False,
                "planned_values": {"root_module": {}},
                "prior_state": {"values": account_state(EXPECTED_ACCOUNT)},
                "resource_changes": [],
                "output_changes": {},
            },
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(EXPECTED_ACCOUNT, result.stdout)

    def test_destroy_rejects_wrong_account_from_prior_state(self) -> None:
        result = self.run_gate(
            "destroy",
            {
                "applyable": True,
                "complete": True,
                "errored": False,
                "planned_values": {"root_module": {}},
                "prior_state": {"values": account_state("999999999999")},
                "resource_changes": [],
                "output_changes": {},
            },
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("prior Terraform state", result.stderr)

    def test_apply_account_remains_checked_from_planned_values(self) -> None:
        result = self.run_gate(
            "apply",
            {
                "applyable": True,
                "complete": True,
                "errored": False,
                "planned_values": account_state(EXPECTED_ACCOUNT),
                "prior_state": {"values": account_state("999999999999")},
                "resource_changes": [],
                "output_changes": {},
            },
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_shared_state_writers_use_one_actions_concurrency_group(self) -> None:
        for workflow_path in SHARED_STATE_WRITERS:
            with self.subTest(workflow=workflow_path.name):
                source = workflow_path.read_text(encoding="utf-8")
                self.assertIn("group: pawlocal-lightsail-deploy", source)

    def test_each_aws_job_checks_live_account_before_terraform(self) -> None:
        source = WORKFLOW.read_text(encoding="utf-8")
        for job_name, environment in AWS_ENABLED_JOBS.items():
            with self.subTest(job=job_name):
                start = source.index(f"  {job_name}:\n")
                next_job = re.search(r"(?m)^  [a-z][a-z-]+:\s*$", source[start + 1 :])
                end = start + 1 + next_job.start() if next_job else len(source)
                job = source[start:end]
                self.assertIn(f"environment: {environment}", job)
                credential_step = job.index("uses: aws-actions/configure-aws-credentials@v5")
                self.assertIn("id-token: write", job)
                expected_role = (
                    "PAWLOCAL_TERRAFORM_PLAN_ROLE_ARN"
                    if environment == "infrastructure-plan"
                    else "PAWLOCAL_TERRAFORM_APPLY_ROLE_ARN"
                )
                self.assertIn(f"role-to-assume: ${{{{ vars.{expected_role} }}}}", job)
                self.assertIn("allowed-account-ids: ${{ vars.PAWLOCAL_AWS_ACCOUNT_ID }}", job)
                account_check = job.index("steps.aws-credentials.outputs.aws-account-id")
                terraform_calls = [
                    position
                    for command in ("terraform init", "terraform plan", "terraform apply")
                    if (position := job.find(command)) >= 0
                ]
                self.assertTrue(terraform_calls, "expected an AWS-backed Terraform command")
                self.assertLess(credential_step, account_check)
                self.assertLess(account_check, min(terraform_calls))


if __name__ == "__main__":
    unittest.main()
