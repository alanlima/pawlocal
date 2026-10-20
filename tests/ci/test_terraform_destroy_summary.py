from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SUMMARY = ROOT / ".github/scripts/terraform-destroy-summary.py"


class TerraformDestroySummaryTests(unittest.TestCase):
    def run_summary(self, plan: dict) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as directory:
            plan_path = Path(directory) / "plan.json"
            plan_path.write_text(json.dumps(plan), encoding="utf-8")
            return subprocess.run(
                [sys.executable, str(SUMMARY), str(plan_path)],
                capture_output=True,
                text=True,
                check=False,
            )

    def test_prints_actions_without_values_or_identifiers_and_never_validates(self) -> None:
        result = self.run_summary(
            {
                "resource_changes": [
                    {
                        "address": 'module.fullstack.aws_iam_role_policy.github_deploy["development"]',
                        "change": {
                            "actions": ["delete"],
                            "before": {
                                "policy": "private-policy-body-marker",
                                "role": "private-role-arn-marker",
                                "id": "private-id-marker",
                            },
                        },
                    },
                    {
                        "address": "aws_iam_openid_connect_provider.github",
                        "change": {"actions": ["forget"], "before": {"arn": "private-oidc-arn-marker"}},
                    },
                    {
                        "address": 'module.fullstack.aws_s3_bucket.frontend["unexpected-sensitive-key"]',
                        "change": {"actions": ["delete"], "before": {"id": "private-bucket-marker"}},
                    },
                ],
                "applyable": False,
                "complete": False,
            }
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('module.fullstack.aws_iam_role_policy.github_deploy["development"]', result.stdout)
        self.assertIn("aws_iam_openid_connect_provider.github", result.stdout)
        self.assertIn("<unlisted resource>", result.stdout)
        for private_value in (
            "private-policy-body-marker",
            "private-role-arn-marker",
            "private-id-marker",
            "private-oidc-arn-marker",
            "private-bucket-marker",
            "unexpected-sensitive-key",
        ):
            self.assertNotIn(private_value, result.stdout)
        self.assertIn("Delete 2", result.stdout)
        self.assertIn("Forget 1", result.stdout)

    def test_summarizes_replacement_and_unexpected_actions_without_failing(self) -> None:
        result = self.run_summary(
            {
                "resource_changes": [
                    {"address": "aws_s3_bucket.site", "change": {"actions": ["delete", "create"]}},
                    {"address": "aws_s3_bucket.odd", "change": {"actions": ["mystery-action"]}},
                ]
            }
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Replace 1", result.stdout)
        self.assertIn("Other 1", result.stdout)
        self.assertIn("<other>", result.stdout)


if __name__ == "__main__":
    unittest.main()
