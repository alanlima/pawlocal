from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DIAGNOSTIC = ROOT / ".github/scripts/terraform-refresh-diagnostic.py"
WORKFLOW = ROOT / ".github/workflows/terraform-current-stack-operations.yml"


def policy(bucket: str, action: str) -> str:
    return json.dumps(
        {
            "Version": "2012-10-17",
            "Statement": [{
                "Effect": "Allow",
                "Action": action,
                "Resource": f"arn:aws:s3:::{bucket}/private-object-name",
                "Condition": {"StringEquals": {"aws:PrincipalAccount": "123456789012"}},
            }],
        }
    )


def plan(address: str, before: str, after: str) -> dict[str, object]:
    return {
        "resource_changes": [{
            "address": address,
            "mode": "managed",
            "change": {
                "actions": ["update"],
                "before": {"policy": before, "name": "private-resource-name"},
                "after": {"policy": after, "name": "private-resource-name"},
            },
        }]
    }


class TerraformRefreshDiagnosticTests(unittest.TestCase):
    def run_diagnostic(self, refresh: dict[str, object], normal: dict[str, object]) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as temporary:
            refresh_path = Path(temporary) / "refresh.json"
            normal_path = Path(temporary) / "normal.json"
            refresh_path.write_text(json.dumps(refresh), encoding="utf-8")
            normal_path.write_text(json.dumps(normal), encoding="utf-8")
            return subprocess.run(
                [sys.executable, str(DIAGNOSTIC), str(refresh_path), str(normal_path)],
                capture_output=True,
                text=True,
                check=False,
            )

    def test_reports_refresh_and_normal_changes_without_policy_values_or_identifiers(self) -> None:
        private_bucket = "pawlocal-private-bucket-123456789012"
        secret_marker = "private-object-name"
        result = self.run_diagnostic(
            plan(
                'module.fullstack.aws_s3_bucket_policy.frontend["development"]',
                policy(private_bucket, "s3:GetObject"),
                policy(private_bucket, "s3:PutObject"),
            ),
            plan(
                "aws_iam_role_policy.github_deploy",
                policy(private_bucket, "s3:GetObject"),
                policy(private_bucket, "s3:DeleteObject"),
            ),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Refresh-only state reconciliation candidates", result.stdout)
        self.assertIn("Normal plan changes after refresh", result.stdout)
        self.assertIn("module.fullstack.aws_s3_bucket_policy.frontend[*]", result.stdout)
        self.assertIn("$.policy", result.stdout)
        self.assertIn("sha256=", result.stdout)
        self.assertNotIn(private_bucket, result.stdout)
        self.assertNotIn("123456789012", result.stdout)
        self.assertNotIn("arn:aws:", result.stdout)
        self.assertNotIn(secret_marker, result.stdout)
        self.assertNotIn("s3:GetObject", result.stdout)
        self.assertNotIn("s3:PutObject", result.stdout)

    def test_workflow_runs_refresh_only_before_the_destroy_preparation_plan(self) -> None:
        source = WORKFLOW.read_text(encoding="utf-8")
        refresh_step = source.index("name: Create read-only refresh snapshot for destroy preparation")
        refresh_plan = source.index("terraform plan -refresh-only", refresh_step)
        normal_plan = source.index("terraform plan -input=false", refresh_plan)
        diagnostic = source.index("terraform-refresh-diagnostic.py", normal_plan)
        strict_guard = source.index("--destroy-prepare-guard", diagnostic)
        self.assertLess(refresh_step, refresh_plan)
        self.assertLess(refresh_plan, normal_plan)
        self.assertLess(normal_plan, diagnostic)
        self.assertLess(diagnostic, strict_guard)
        self.assertIn("if: inputs.operation == 'destroy'", source[refresh_step:refresh_plan])


if __name__ == "__main__":
    unittest.main()
