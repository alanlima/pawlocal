from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DIAGNOSTIC = ROOT / ".github/scripts/terraform-plan-diagnostic.py"
WORKFLOW = ROOT / ".github/workflows/terraform-environment.yml"


class TerraformDiagnosticTests(unittest.TestCase):
    def run_diagnostic(self, enabled: str | None, phase: str = "apply") -> subprocess.CompletedProcess[str]:
        account_id = "1" * 12
        digest = "a" * 64
        host_id = "c2VjcmV0" * 8
        diagnostic = f"""\
Error: creating S3 Bucket (private-project-development-abc123): operation error S3: CreateBucket, https response error StatusCode: 403, RequestID: request-private, HostID: {host_id}, api error AccessDenied: User: arn:aws:sts::{account_id}:assumed-role/private-role/session is not authorized for arn:aws:s3:::private-project-development-abc123
  with module.pawlocal.aws_s3_bucket.frontend,
  on ../../modules/pawlocal-environment/main.tf line 10, in resource "aws_s3_bucket" "frontend":
certificate=12345678-1234-4123-8123-123456789abc domain=private.example.invalid plan=plans/development/123/1 sha256:{digest} password=do-not-print
token=short-token api_key=short-api-key Authorization=Bearer-short unknown_field=unrecognized-value
"""
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "terraform.log"
            log.write_text(diagnostic, encoding="utf-8")
            env = os.environ.copy()
            if enabled is None:
                env.pop("PAWLOCAL_TERRAFORM_DIAGNOSTIC_LOGS", None)
            else:
                env["PAWLOCAL_TERRAFORM_DIAGNOSTIC_LOGS"] = enabled
            return subprocess.run(
                [sys.executable, str(DIAGNOSTIC), "--phase", phase, str(log)],
                check=True,
                capture_output=True,
                text=True,
                env=env,
            )

    def test_diagnostics_are_fully_withheld_when_disabled_or_absent(self) -> None:
        expected = "Terraform apply failed; raw provider output was withheld.\n"
        self.assertEqual(self.run_diagnostic(None).stdout, expected)
        self.assertEqual(self.run_diagnostic("false").stdout, expected)
        self.assertEqual(self.run_diagnostic("TRUE").stdout, expected)

    def test_enabled_diagnostics_preserve_only_actionable_generic_details(self) -> None:
        output = self.run_diagnostic("true").stdout
        self.assertIn("Terraform apply failed; raw provider output was withheld.", output)
        self.assertIn("AWS operation: S3 CreateBucket", output)
        self.assertIn("AWS error code: AccessDenied", output)
        self.assertIn("HTTP status: 403", output)
        self.assertIn("The provider request was not authorized.", output)
        self.assertIn("Configuration file: main.tf:10", output)
        self.assertNotIn("Diagnostic 1:", output)
        for sensitive in (
            "1" * 12,
            "private-project-development-abc123",
            "private-role",
            "private.example.invalid",
            "12345678-1234-4123-8123-123456789abc",
            "plans/development/123/1",
            "a" * 64,
            "do-not-print",
            "request-private",
            "c2VjcmV0" * 8,
            "short-token",
            "short-api-key",
            "Bearer-short",
            "unrecognized-value",
        ):
            with self.subTest(sensitive=sensitive):
                self.assertNotIn(sensitive, output)

    def test_enabled_diagnostics_withhold_unrecognized_fields(self) -> None:
        diagnostic = """\
Error: token=raw-short api_key=other-short Authorization=Bearer-private arbitrary=unrecognized
operation error SecretService: RevealValue, StatusCode: 299, api error SecretCode
  on token.tf line 7, in resource "unknown" "private":
"""
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "terraform.log"
            log.write_text(diagnostic, encoding="utf-8")
            env = os.environ.copy()
            env["PAWLOCAL_TERRAFORM_DIAGNOSTIC_LOGS"] = "true"
            result = subprocess.run(
                [sys.executable, str(DIAGNOSTIC), "--phase", "plan", str(log)],
                check=True,
                capture_output=True,
                text=True,
                env=env,
            )
        self.assertEqual(
            result.stdout,
            "Terraform planning failed; raw provider output was withheld.\n"
            "No allowlisted diagnostic fields were found; provider details were withheld.\n",
        )

    def test_lock_timeout_option_does_not_misclassify_local_exec_import_failure(self) -> None:
        diagnostic = """\
Run terraform apply -input=false -lock-timeout=5m
Error: local-exec provisioner error
Error running command 'python -m pawlocal.dsql_post_apply_setup': exit status 1.
Output: Aurora DSQL protected setup failed (environment=development, phase=connection, class=ModuleNotFoundError).
"""
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "terraform.log"
            log.write_text(diagnostic, encoding="utf-8")
            env = os.environ.copy()
            env["PAWLOCAL_TERRAFORM_DIAGNOSTIC_LOGS"] = "true"
            result = subprocess.run(
                [sys.executable, str(DIAGNOSTIC), "--phase", "apply", str(log)],
                check=True,
                capture_output=True,
                text=True,
                env=env,
            )
        self.assertEqual(
            result.stdout,
            "Terraform apply failed; raw provider output was withheld.\n"
            "No allowlisted diagnostic fields were found; provider details were withheld.\n",
        )

    def test_standalone_timeout_failure_keeps_sanitized_timeout_class(self) -> None:
        diagnostic = "Error: timeout while waiting for the provider operation\n"
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "terraform.log"
            log.write_text(diagnostic, encoding="utf-8")
            env = os.environ.copy()
            env["PAWLOCAL_TERRAFORM_DIAGNOSTIC_LOGS"] = "true"
            result = subprocess.run(
                [sys.executable, str(DIAGNOSTIC), "--phase", "apply", str(log)],
                check=True,
                capture_output=True,
                text=True,
                env=env,
            )
        self.assertEqual(
            result.stdout,
            "Terraform apply failed; raw provider output was withheld.\n"
            "Explanation: Terraform timed out while waiting for the resource operation.\n",
        )

    def test_workflow_gates_both_plan_and_apply_diagnostics(self) -> None:
        workflow = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn(
            "PAWLOCAL_TERRAFORM_DIAGNOSTIC_LOGS: ${{ vars.PAWLOCAL_TERRAFORM_DIAGNOSTIC_LOGS }}",
            workflow,
        )
        self.assertEqual(workflow.count("terraform-plan-diagnostic.py"), 2)
        self.assertIn('--phase plan "$RUNNER_TEMP/terraform-plan.log"', workflow)
        self.assertIn('--phase apply "$RUNNER_TEMP/terraform-apply.log"', workflow)
        self.assertIn('> "$RUNNER_TEMP/terraform-plan.log" 2>&1', workflow)
        self.assertIn('--log "$RUNNER_TEMP/terraform-apply.log"', workflow)


if __name__ == "__main__":
    unittest.main()
