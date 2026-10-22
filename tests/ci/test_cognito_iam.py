import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BOOTSTRAP = ROOT / "infra" / "terraform" / "iam-bootstrap"


class CognitoDelegatedIamTests(unittest.TestCase):
    def test_locked_provider_and_source_evidence_remain_version_aligned(self) -> None:
        lock = (BOOTSTRAP / ".terraform.lock.hcl").read_text(encoding="utf-8")
        design = (BOOTSTRAP / "POLICY_DESIGN.md").read_text(encoding="utf-8")

        self.assertIn('version     = "6.69.1"', lock)
        for source in (
            "internal/service/lambda/function.go",
            "internal/service/lambda/permission.go",
            "internal/service/lambda/tags_gen.go",
            "internal/service/logs/group.go",
            "internal/service/logs/tags_gen.go",
        ):
            self.assertIn(
                f"terraform-provider-aws/blob/v6.69.1/{source}",
                design,
            )

        self.assertIn("`DescribeLogGroups` with the exact `LogGroupNamePrefix`", design)
        self.assertIn("LogGroup API ARN guidance", design)
        self.assertIn("`ListVersionsByFunction`", design)
        self.assertIn("awslambda-ListVersionsByFunction", design)

    def test_bootstrap_scope_contains_no_application_resources_or_action_wildcards(self) -> None:
        source = (BOOTSTRAP / "cognito_permissions.tf").read_text(encoding="utf-8")

        self.assertNotRegex(source, r'resource\s+"aws_(?:lambda|cloudwatch_log_group|cognito)')
        self.assertNotIn('"lambda:*"', source)
        self.assertNotIn('"logs:*"', source)
        self.assertNotIn('"logs:Describe*"', source)
        self.assertNotIn('"cognito-idp:', source)
        self.assertNotIn('"s3:', source)
        self.assertEqual(1, source.count('"lambda:ListVersionsByFunction"'))

    def test_describe_log_groups_exception_is_dedicated_and_region_limited(self) -> None:
        source = (BOOTSTRAP / "cognito_permissions.tf").read_text(encoding="utf-8")
        exception_blocks = re.findall(
            r'sid\s+=\s+"DescribeRegionalLogGroupsForProviderRefresh"(?P<body>.*?)\n\s+}',
            source,
            flags=re.DOTALL,
        )

        self.assertEqual(2, len(exception_blocks))
        for block in exception_blocks:
            self.assertIn('actions   = ["logs:DescribeLogGroups"]', block)
            self.assertIn('resources = ["*"]', block)
            self.assertIn('variable = "aws:RequestedRegion"', block)

    def test_semantic_policy_test_covers_cross_environment_and_negative_actions(self) -> None:
        test_source = (
            BOOTSTRAP / "tests" / "cognito_delegated_roles.tftest.hcl"
        ).read_text(encoding="utf-8")

        self.assertIn('environment == "development" ? "production" : "development"', test_source)
        self.assertIn('"logs:DescribeLogStreams"', test_source)
        self.assertIn('"logs:GetLogEvents"', test_source)
        self.assertIn('"logs:StartLiveTail"', test_source)
        self.assertIn('action == "iam:PassRole"', test_source)
        self.assertIn('contains(flatten([statement.Action]), "lambda:ListVersionsByFunction")', test_source)
        self.assertIn("length(policy.minified_json) < local.iam_managed_policy_max_bytes", test_source)


if __name__ == "__main__":
    unittest.main()
