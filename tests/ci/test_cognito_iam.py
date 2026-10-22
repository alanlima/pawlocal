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
        self.assertIn("CreateFunctionInput", design)
        self.assertIn("CreateLogGroupInput", design)
        self.assertIn("Where a state-backed plan is available before merge", design)
        self.assertIn("backend-disabled plan was not run", design)
        self.assertIn(
            "no bootstrap apply may occur until a fresh state-backed saved plan",
            design,
        )

    def test_bootstrap_scope_contains_no_application_resources_or_action_wildcards(self) -> None:
        source = (BOOTSTRAP / "cognito_permissions.tf").read_text(encoding="utf-8")
        variables = (BOOTSTRAP / "variables.tf").read_text(encoding="utf-8")
        provider = (BOOTSTRAP / "versions.tf").read_text(encoding="utf-8")
        terraform_sources = "\n".join(
            path.read_text(encoding="utf-8")
            for path in BOOTSTRAP.glob("*.tf")
        )

        self.assertNotRegex(source, r'resource\s+"aws_(?:lambda|cloudwatch_log_group|cognito)')
        self.assertNotIn('"lambda:*"', source)
        self.assertNotIn('"logs:*"', source)
        self.assertNotIn('"logs:Describe*"', source)
        self.assertNotIn('"cognito-idp:', source)
        self.assertNotIn('"s3:', source)
        self.assertEqual(1, source.count('"lambda:ListVersionsByFunction"'))
        self.assertNotRegex(source, r'project\s*=\s*"pawlocal"')
        self.assertNotRegex(source, r'values\s*=\s*\["pawlocal"\]')
        self.assertRegex(
            variables,
            r'variable\s+"project_name"\s*\{[\s\S]*?default\s*=\s*"pawlocal"',
        )
        self.assertIn("length(var.project_name) <= 8", variables)
        self.assertIn('regex("^[A-Za-z0-9._-]+$", var.project_name)', variables)
        self.assertRegex(
            provider,
            r'default_tags\s*\{\s*tags\s*=\s*\{\s*project\s*=\s*var\.project_name\s*managedby\s*=\s*"terraform"',
        )
        self.assertNotRegex(terraform_sources, r'values\s*=\s*\["pawlocal"\]')
        for path in BOOTSTRAP.glob("*.tf"):
            if path.name == "versions.tf":
                continue
            module_source = path.read_text(encoding="utf-8")
            self.assertNotRegex(
                module_source,
                r'(?m)^\s+tags\s*=\s*\{[^}]*\b(?:project|managedby)\s*=',
                msg=f"{path.name} must inherit shared resource tags from provider default_tags",
            )

    def test_project_name_propagates_through_application_roots_and_module(self) -> None:
        module = ROOT / "infra" / "terraform" / "modules" / "pawlocal-environment"
        module_sources = "\n".join(
            path.read_text(encoding="utf-8") for path in module.glob("*.tf")
        )

        self.assertRegex(
            (module / "variables.tf").read_text(encoding="utf-8"),
            r'variable\s+"project_name"\s*\{[\s\S]*?default\s*=\s*"pawlocal"',
        )
        self.assertIn(
            "length(var.project_name) <= 8",
            (module / "variables.tf").read_text(encoding="utf-8"),
        )
        self.assertIn(
            'regex("^[A-Za-z0-9._-]+$", var.project_name)',
            (module / "variables.tf").read_text(encoding="utf-8"),
        )
        self.assertIn("project     = var.project_name", module_sources)
        self.assertNotRegex(module_sources, r'values\s*=\s*\["pawlocal"\]')

        for environment in ("development", "production"):
            root = ROOT / "infra" / "terraform" / "environments" / environment
            variables = (root / "variables.tf").read_text(encoding="utf-8")
            versions = (root / "versions.tf").read_text(encoding="utf-8")
            main = (root / "main.tf").read_text(encoding="utf-8")

            self.assertRegex(
                variables,
                r'variable\s+"project_name"\s*\{[\s\S]*?default\s*=\s*"pawlocal"',
            )
            self.assertIn("length(var.project_name) <= 8", variables)
            self.assertIn('regex("^[A-Za-z0-9._-]+$", var.project_name)', variables)
            self.assertIn("project     = var.project_name", versions)
            self.assertIn("project_name                = var.project_name", main)

        semantic_test = (
            module / "tests" / "tagged_create_permissions.tftest.hcl"
        ).read_text(encoding="utf-8")
        self.assertIn('project_name               = "pawhub"', semantic_test)
        self.assertIn('local.common_tags.project == "pawhub"', semantic_test)
        self.assertIn('local.common_tags.project == "pawlocal"', semantic_test)
        self.assertIn('project_name               = "pawlocalx"', semantic_test)
        self.assertIn("expect_failures = [var.project_name]", semantic_test)

    def test_create_time_tagging_cannot_adopt_unowned_exact_name_resources(self) -> None:
        source = (BOOTSTRAP / "cognito_permissions.tf").read_text(encoding="utf-8")
        semantic_test = (
            BOOTSTRAP / "tests" / "cognito_delegated_roles.tftest.hcl"
        ).read_text(encoding="utf-8")

        body = source.split(
            'sid       = "CreateLambda"', 1
        )[1].split('sid       = "ManageLambda"', 1)[0]
        self.assertIn('variable = "aws:ResourceTag/project"', body)
        self.assertIn('variable = "aws:ResourceTag/environment"', body)
        self.assertIn('statement.Sid == "CreateLambda"', semantic_test)
        self.assertIn('statement.Sid == "TagNewLogGroup"', semantic_test)

    def test_add_permission_is_limited_to_cognito_principal(self) -> None:
        source = (BOOTSTRAP / "cognito_permissions.tf").read_text(encoding="utf-8")
        semantic_test = (
            BOOTSTRAP / "tests" / "cognito_delegated_roles.tftest.hcl"
        ).read_text(encoding="utf-8")

        self.assertEqual(1, source.count('"lambda:AddPermission"'))
        self.assertIn('variable = "lambda:Principal"', source)
        self.assertIn('values   = ["cognito-idp.amazonaws.com"]', source)
        self.assertIn('statement.Sid == "GrantCognitoInvoke"', semantic_test)
        self.assertIn('statement.Condition.StringEquals["lambda:Principal"]', semantic_test)

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
        self.assertIn('project_name                = "pawhub"', test_source)
        self.assertIn('["aws:RequestTag/project", "aws:ResourceTag/project"]', test_source)
        self.assertIn("length(policy.minified_json) < local.iam_managed_policy_max_bytes", test_source)


if __name__ == "__main__":
    unittest.main()
