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
        self.assertIn('resource_categories={"s3": 1}', result.stdout)
        self.assertIn('"read": 1', result.stdout)
        self.assertIn('"write": 1', result.stdout)
        self.assertNotIn(private_bucket, result.stdout)
        self.assertNotIn("123456789012", result.stdout)
        self.assertNotIn("arn:aws:", result.stdout)
        self.assertNotIn(secret_marker, result.stdout)
        self.assertNotIn("s3:GetObject", result.stdout)
        self.assertNotIn("s3:PutObject", result.stdout)

    def test_encryption_details_show_only_allowlisted_enums_and_fingerprint(self) -> None:
        sensitive_value = "kms-key-arn-with-private-id"
        refresh = {"resource_changes": []}
        normal = {
            "resource_changes": [{
                "address": 'module.fullstack.aws_dsql_cluster.app["development"]',
                "mode": "managed",
                "change": {
                    "actions": ["update"],
                    "before": {"encryption_details": {"encryption_status": "ENABLED", "encryption_type": "AWS_OWNED_KMS_KEY"}},
                    "after": {"encryption_details": {"encryption_status": "ENABLED", "encryption_type": "CUSTOMER_MANAGED_KMS_KEY", "kms_key_arn": sensitive_value}},
                },
            }]
        }
        result = self.run_diagnostic(refresh, normal)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("encryption_status=ENABLED", result.stdout)
        self.assertIn("encryption_type=CUSTOMER_MANAGED_KMS_KEY", result.stdout)
        self.assertNotIn(sensitive_value, result.stdout)
        self.assertNotIn("kms_key_arn", result.stdout)
        alternate = self.run_diagnostic(
            refresh,
            {
                "resource_changes": [{
                    "address": 'module.fullstack.aws_dsql_cluster.app["development"]',
                    "mode": "managed",
                    "change": {
                        "actions": ["update"],
                        "before": {"encryption_details": {"encryption_status": "ENABLED", "encryption_type": "AWS_OWNED_KMS_KEY"}},
                        "after": {"encryption_details": {"encryption_status": "ENABLED", "encryption_type": "CUSTOMER_MANAGED_KMS_KEY", "kms_key_arn": "different-private-key-id"}},
                    },
                }]
            },
        )
        after_summary = next(line for line in result.stdout.splitlines() if "after[present;" in line)
        alternate_summary = next(line for line in alternate.stdout.splitlines() if "after[present;" in line)
        self.assertEqual(after_summary.split("after[", 1)[1].split("]", 1)[0], alternate_summary.split("after[", 1)[1].split("]", 1)[0])

    def test_policy_summary_distinguishes_absent_unknown_sensitive_and_present(self) -> None:
        secret_marker = "private-policy-body-marker"
        cases = [
            ("absent", {"policy": None}, {}, "after[absent]"),
            (
                "unknown",
                {"policy": None},
                {"after_unknown": {"policy": True}},
                "after[unknown/computed]",
            ),
            (
                "sensitive",
                {"policy": secret_marker},
                {"after_sensitive": {"policy": True}},
                "after[sensitive]",
            ),
            (
                "present",
                {"policy": policy("private-bucket", "s3:GetObject")},
                {},
                "after[present; aggregate_sha256=",
            ),
        ]
        for label, after, metadata, expected in cases:
            with self.subTest(label=label):
                change = {
                    "actions": ["update"],
                    "before": {"policy": policy("private-bucket", "s3:PutObject")},
                    "after": after,
                    **metadata,
                }
                result = self.run_diagnostic(
                    {"resource_changes": []},
                    {"resource_changes": [{
                        "address": "aws_iam_role_policy.example",
                        "mode": "managed",
                        "change": change,
                    }]},
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn(expected, result.stdout)
                self.assertNotIn(secret_marker, result.stdout)
                self.assertNotIn("arn:aws:", result.stdout)
                if label in {"unknown", "sensitive", "absent"}:
                    after_summary = next(line for line in result.stdout.splitlines() if "after[" in line)
                    self.assertNotIn("aggregate_sha256=", after_summary.split("after[", 1)[1])

    def test_policy_fingerprint_uses_aggregate_shape_not_policy_identifiers(self) -> None:
        def result_for(bucket: str) -> str:
            result = self.run_diagnostic(
                {"resource_changes": []},
                plan("aws_iam_role_policy.example", policy("old-private-bucket", "s3:GetObject"), policy(bucket, "s3:GetObject")),
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            return next(line for line in result.stdout.splitlines() if "after[present;" in line).split("after[", 1)[1].split("]", 1)[0]

        first = result_for("private-bucket-one")
        second = result_for("private-bucket-two")
        self.assertEqual(first, second)
        self.assertNotIn("private-bucket", first)

    def test_unknown_metadata_triggers_policy_and_nested_encryption_summaries(self) -> None:
        plan_with_unknowns = {
            "resource_changes": [
                {
                    "address": "aws_iam_role_policy.example",
                    "mode": "managed",
                    "change": {
                        "actions": ["update"],
                        "before": {"policy": None},
                        "after": {"policy": None},
                        "after_unknown": {"policy": True},
                    },
                },
                {
                    "address": 'module.fullstack.aws_dsql_cluster.app["development"]',
                    "mode": "managed",
                    "change": {
                        "actions": ["update"],
                        "before": {"encryption_details": None},
                        "after": {"encryption_details": None},
                        "after_unknown": {"encryption_details": {"kms_key_arn": True}},
                    },
                },
            ]
        }
        result = self.run_diagnostic({"resource_changes": []}, plan_with_unknowns)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("aws_iam_role_policy.example", result.stdout)
        self.assertIn("after[unknown/computed]", result.stdout)
        self.assertIn("module.fullstack.aws_dsql_cluster.app[*]", result.stdout)
        self.assertIn("before[absent]; after[unknown/computed]", result.stdout)
        self.assertNotIn("kms_key_arn", result.stdout)

    def test_oidc_provider_stays_app_root_owned_until_later_transfer(self) -> None:
        source = (ROOT / "infra/terraform/main.tf").read_text(encoding="utf-8")
        variables = (ROOT / "infra/terraform/variables.tf").read_text(encoding="utf-8")
        policy_design = (ROOT / "infra/terraform/iam-bootstrap/POLICY_DESIGN.md").read_text(encoding="utf-8")
        self.assertIn('resource "aws_iam_openid_connect_provider" "github"', source)
        resource_start = source.index('resource "aws_iam_openid_connect_provider" "github"')
        resource_end = source.index("locals {", resource_start)
        self.assertNotIn("count", source[resource_start:resource_end])
        self.assertIn("aws_iam_openid_connect_provider.github.arn", source)
        self.assertNotIn("removed {\n  from = aws_iam_openid_connect_provider.github", source)
        self.assertNotIn('variable "manage_github_oidc_provider"', variables)
        self.assertIn("After the bootstrap has imported the publisher roles", policy_design)

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
