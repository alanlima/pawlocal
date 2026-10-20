from __future__ import annotations

import importlib.util
import re
import unittest
from argparse import Namespace
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_helper(name: str):
    path = ROOT / "ops" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


plan_review = load_helper("terraform-plan-review")
plan_object = load_helper("terraform-plan-object")
recovery_review = load_helper("terraform-recovery-plan-review")
bootstrap_oac = load_helper("verify-terraform-bootstrap-oac-handoff")


class BootstrapOacHandoffTests(unittest.TestCase):
    dev_arn = "arn:aws:cloudfront::123456789012:origin-access-control/EDEV123"
    prod_arn = "arn:aws:cloudfront::123456789012:origin-access-control/EPROD123"

    def policy(self, statements):
        return {"Version": "2012-10-17", "Statement": statements}

    class FakeIam:
        def __init__(self, inline_pages=None, attached_pages=None):
            self.inline_pages = inline_pages or [{"PolicyNames": [bootstrap_oac.DEV_POLICY], "IsTruncated": False}]
            self.attached_pages = attached_pages or [{"AttachedPolicies": [], "IsTruncated": False}]
            self.gets = []

        def list_role_policies(self, RoleName, Marker=None):
            return self.inline_pages[0 if Marker is None else 1]

        def list_attached_role_policies(self, RoleName, Marker=None):
            return self.attached_pages[0 if Marker is None else 1]

        def get_role_policy(self, RoleName, PolicyName):
            self.gets.append((RoleName, PolicyName))
            return {"PolicyDocument": {"Statement": []}}

    def test_initial_production_create_window_requires_exact_dev_pin(self):
        dev = self.policy([{
            "Effect": "Allow",
            "Action": sorted(bootstrap_oac.READ_ACTIONS | bootstrap_oac.MUTATE_ACTIONS),
            "Resource": self.dev_arn,
        }])
        prod = self.policy([{
            "Effect": "Allow",
            "Action": sorted(bootstrap_oac.READ_ACTIONS | {bootstrap_oac.CREATE_ACTION}),
            "Resource": "*",
        }])
        self.assertEqual(
            bootstrap_oac.verify_handoff(dev, prod, self.dev_arn),
            "production-oac-create-window-enabled",
        )
        with self.assertRaisesRegex(ValueError, "exact development ARN"):
            bootstrap_oac.verify_handoff(
                self.policy([{"Effect": "Allow", "Action": sorted(bootstrap_oac.READ_ACTIONS | bootstrap_oac.MUTATE_ACTIONS), "Resource": "*"}]),
                prod,
                self.dev_arn,
            )

    def test_production_create_window_rejects_mutation_and_list(self):
        dev = self.policy([{
            "Effect": "Allow", "Action": sorted(bootstrap_oac.READ_ACTIONS | bootstrap_oac.MUTATE_ACTIONS), "Resource": self.dev_arn,
        }])
        for action in (bootstrap_oac.LIST_ACTION, "cloudfront:UpdateOriginAccessControl"):
            prod = self.policy([{
                "Effect": "Allow", "Action": sorted(bootstrap_oac.READ_ACTIONS | {bootstrap_oac.CREATE_ACTION, action}), "Resource": "*",
            }])
            with self.subTest(action=action), self.assertRaises(ValueError):
                bootstrap_oac.verify_handoff(dev, prod, self.dev_arn)

    def test_wildcard_action_and_notaction_allow_statements_are_rejected(self):
        for statement in (
            {"Effect": "Allow", "Action": "*", "Resource": "*"},
            {"Effect": "Allow", "Action": "cloudfront:*", "Resource": "*"},
            {"Effect": "Allow", "NotAction": "iam:*", "Resource": "*"},
            {"Effect": "Allow", "Action": "cloudfront:GetOriginAccessControl", "NotResource": "arn:aws:cloudfront::*:origin-access-control/*"},
        ):
            with self.subTest(statement=statement), self.assertRaises(ValueError):
                bootstrap_oac.allowed_cloudfront(self.policy([statement]))

    def test_extra_inline_policy_fails_closed(self):
        iam = self.FakeIam(inline_pages=[{
            "PolicyNames": [bootstrap_oac.DEV_POLICY, "unexpected-extra"], "IsTruncated": False,
        }])
        with self.assertRaisesRegex(ValueError, "additional inline policies"):
            bootstrap_oac.fetch_exact_inline_policy(iam, bootstrap_oac.DEV_ROLE, bootstrap_oac.DEV_POLICY)
        self.assertEqual(iam.gets, [])

    def test_attached_managed_policy_fails_closed(self):
        iam = self.FakeIam(attached_pages=[{
            "AttachedPolicies": [{"PolicyName": "unexpected", "PolicyArn": "arn:aws:iam::123456789012:policy/unexpected"}],
            "IsTruncated": False,
        }])
        with self.assertRaisesRegex(ValueError, "managed policy"):
            bootstrap_oac.fetch_exact_inline_policy(iam, bootstrap_oac.DEV_ROLE, bootstrap_oac.DEV_POLICY)
        self.assertEqual(iam.gets, [])

    def test_extra_policy_on_later_page_fails_closed(self):
        inline = self.FakeIam(inline_pages=[
            {"PolicyNames": [bootstrap_oac.DEV_POLICY], "IsTruncated": True, "Marker": "next-inline"},
            {"PolicyNames": ["late-extra"], "IsTruncated": False},
        ])
        with self.assertRaisesRegex(ValueError, "additional inline policies"):
            bootstrap_oac.fetch_exact_inline_policy(inline, bootstrap_oac.DEV_ROLE, bootstrap_oac.DEV_POLICY)
        managed = self.FakeIam(attached_pages=[
            {"AttachedPolicies": [], "IsTruncated": True, "Marker": "next-managed"},
            {"AttachedPolicies": [{"PolicyName": "late-extra", "PolicyArn": "arn:aws:iam::123456789012:policy/late-extra"}], "IsTruncated": False},
        ])
        with self.assertRaisesRegex(ValueError, "managed policy"):
            bootstrap_oac.fetch_exact_inline_policy(managed, bootstrap_oac.DEV_ROLE, bootstrap_oac.DEV_POLICY)

    def test_inline_and_attached_policy_enumeration_is_paginated(self):
        iam = self.FakeIam(
            inline_pages=[
                {"PolicyNames": [bootstrap_oac.DEV_POLICY], "IsTruncated": True, "Marker": "next-inline"},
                {"PolicyNames": [], "IsTruncated": False},
            ],
            attached_pages=[
                {"AttachedPolicies": [], "IsTruncated": True, "Marker": "next-managed"},
                {"AttachedPolicies": [], "IsTruncated": False},
            ],
        )
        self.assertEqual(
            bootstrap_oac.fetch_exact_inline_policy(iam, bootstrap_oac.DEV_ROLE, bootstrap_oac.DEV_POLICY),
            {"Statement": []},
        )
        self.assertEqual(iam.gets, [(bootstrap_oac.DEV_ROLE, bootstrap_oac.DEV_POLICY)])

    def test_pinned_production_policy_requires_exact_arn(self):
        dev = self.policy([{
            "Effect": "Allow", "Action": sorted(bootstrap_oac.READ_ACTIONS | bootstrap_oac.MUTATE_ACTIONS), "Resource": self.dev_arn,
        }])
        prod = self.policy([{
            "Effect": "Allow", "Action": sorted(bootstrap_oac.READ_ACTIONS | bootstrap_oac.MUTATE_ACTIONS), "Resource": self.prod_arn,
        }])
        self.assertEqual(bootstrap_oac.verify_handoff(dev, prod, self.dev_arn, self.prod_arn), "existing-production-oac-pinned")


class TerraformPlanReviewTests(unittest.TestCase):
    def plan(self, resource_type="aws_s3_bucket", address="aws_s3_bucket.assets", actions=None):
        return {
            "format_version": "1.2",
            "applyable": True,
            "complete": True,
            "errored": False,
            "output_changes": {},
            "deferred_changes": [],
            "resource_changes": [{
                "address": address,
                "type": resource_type,
                "change": {
                    "actions": actions or ["update"],
                    "before": {"name": "old", "password": "old-secret"},
                    "after": {"name": "new", "password": "new-secret"},
                    "before_sensitive": {"password": True},
                    "after_sensitive": {"password": True},
                },
            }],
        }

    def test_sensitive_markers_and_credential_names_are_redacted(self):
        output = plan_review.build_review(self.plan(), "development")
        self.assertNotIn("old-secret", output)
        self.assertNotIn("new-secret", output)
        self.assertNotIn("password", output)
        self.assertNotIn('"old"', output)
        self.assertNotIn('"new"', output)
        self.assertIn("no Terraform attribute values", output)

    def test_cross_environment_address_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "production"):
            plan_review.build_review(
                self.plan(address="module.production.aws_s3_bucket.assets"), "development"
            )

    def test_unknown_resource_type_and_action_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "unsupported resource"):
            plan_review.build_review(self.plan(resource_type="aws_unknown_resource"), "development")
        with self.assertRaisesRegex(ValueError, "actions"):
            plan_review.build_review(self.plan(actions=["replace"]), "development")

    def test_delete_and_replacement_are_rejected(self):
        for actions in (["delete"], ["delete", "create"], ["create", "delete"]):
            with self.subTest(actions=actions), self.assertRaisesRegex(ValueError, "replacement"):
                plan_review.build_review(self.plan(actions=actions), "development")

    def test_cloudfront_oac_update_requires_permission_refresh(self):
        with self.assertRaisesRegex(ValueError, "origin access control"):
            plan_review.build_review(
                self.plan(resource_type="aws_cloudfront_origin_access_control", actions=["update"]),
                "development",
            )

    def test_plan_must_be_applyable_complete_and_error_free(self):
        for field, value in (("applyable", False), ("complete", False), ("errored", True)):
            plan = self.plan()
            plan[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                plan_review.build_review(plan, "development")

    def test_output_and_deferred_changes_are_explicitly_handled(self):
        plan = self.plan()
        plan["output_changes"] = {
            "api_url": {"actions": ["update"], "before": "old", "after": "new", "sensitive": False}
        }
        rendered = plan_review.build_review(plan, "development")
        self.assertIn("Output changes: 1", rendered)
        self.assertNotIn("old", rendered)
        self.assertNotIn("new", rendered)
        plan["deferred_changes"] = [{"reason": "unknown"}]
        with self.assertRaisesRegex(ValueError, "deferred changes"):
            plan_review.build_review(plan, "development")


class TerraformPlanObjectTests(unittest.TestCase):
    def test_plan_prefix_is_environment_scoped_and_traversal_blocked(self):
        plan_object.scoped_key("private-plans", "plans/development/123/1/tfplan", "development")
        for key in ("plans/production/123/1/tfplan", "plans/development/../tfplan", "tfplan"):
            with self.subTest(key=key), self.assertRaises(ValueError):
                plan_object.scoped_key("private-plans", key, "development")

    def test_metadata_binds_environment_state_commit_repo_and_run(self):
        args = Namespace(
            environment="development",
            state_key="pawlocal/development/terraform.tfstate",
            commit="a" * 40,
            repository_id="123456",
            run_id="445566",
            run_attempt="2",
            sha256="b" * 64,
        )
        expected = plan_object.expected_metadata(args)
        plan_object.verify_metadata(dict(expected), expected)
        for field, other in (("repository_id", "999"), ("run_attempt", "1"), ("commit", "c" * 40)):
            wrong = dict(expected)
            wrong[field] = other
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "does not match"):
                plan_object.verify_metadata(wrong, expected)

    def test_invalid_digest_and_state_key_are_rejected(self):
        args = Namespace(
            environment="development",
            state_key="pawlocal/production/terraform.tfstate",
            commit="a" * 40,
            repository_id="123456",
            run_id="445566",
            run_attempt="1",
            sha256="not-a-digest",
        )
        with self.assertRaisesRegex(ValueError, "state key"):
            plan_object.expected_metadata(args)
        args.state_key = "pawlocal/development/terraform.tfstate"
        with self.assertRaisesRegex(ValueError, "digest"):
            plan_object.expected_metadata(args)

    def test_recovery_metadata_uses_legacy_shared_state_key(self):
        args = Namespace(
            environment="recovery",
            state_key="pawlocal/terraform.tfstate",
            commit="a" * 40,
            repository_id="123456",
            run_id="445566",
            run_attempt="1",
            sha256="b" * 64,
        )
        self.assertEqual(plan_object.expected_metadata(args)["state_key"], "pawlocal/terraform.tfstate")


class TerraformWorkflowContractTests(unittest.TestCase):
    def test_development_workflow_approves_exact_plan_and_verifies_database(self):
        text = (ROOT / ".github/workflows/terraform-infrastructure-deploy.yml").read_text()
        validate = text.index("  validate-ref:")
        dev_plan = text.index("  development-plan:")
        dev_apply = text.index("  development-apply:")
        self.assertLess(validate, dev_plan)
        self.assertLess(dev_plan, dev_apply)
        self.assertIn("environment: development-apply", text)
        self.assertNotIn("environment: development-plan", text)
        self.assertIn("apply -input=false -lock-timeout=5m -auto-approve tfplan", text)
        self.assertIn("plans/development/${{ github.run_id }}/${{ github.run_attempt }}/tfplan", text)
        self.assertIn("PAWLOCAL_TF_PLAN_BUCKET", text)
        self.assertIn("--repository-id \"$GITHUB_REPOSITORY_ID\"", text)
        self.assertIn("Development database-backed place", text)
        self.assertNotIn("production-plan:", text)
        self.assertIn("pawlocal-infrastructure", text)
        self.assertNotIn("upload-artifact", text)
        self.assertNotIn('[[ "${{ inputs.backend_image_digest }}"', text)
        self.assertIsNone(re.search(r"^\s*terraform\s+[^\n]*\s-target(?:\s|=)", text, re.MULTILINE))

    def test_plan_is_private_and_review_output_is_sanitized(self):
        text = (ROOT / ".github/workflows/terraform-infrastructure-deploy.yml").read_text()
        self.assertNotIn("terraform show tfplan", text)
        self.assertIn("terraform show -json tfplan", text)
        self.assertIn("terraform-plan-review.py", text)
        self.assertIn("raw output was withheld", text)
        self.assertIn("terraform-plan-object.py upload", text)
        self.assertIn("terraform-plan-object.py download", text)
        self.assertIn("plan_sha256", text)
        production = (ROOT / ".github/workflows/terraform-production-promotion.yml").read_text()
        self.assertIn("terraform show -json tfplan", production)
        self.assertIn("terraform-plan-review.py", production)
        self.assertIn("plans/production/${{ github.run_id }}/${{ github.run_attempt }}/tfplan", production)
        self.assertIn("verify-terraform-bootstrap-oac-handoff.py", production)

    def test_recovery_is_fail_closed_until_scoped_policy_review(self):
        text = (ROOT / ".github/workflows/terraform-recovery.yml").read_text()
        self.assertIn("terraform plan -destroy", text)
        self.assertNotIn("environment: terraform-recovery-plan", text)
        self.assertIn("pawlocal/terraform.tfstate", text)
        self.assertIn("terraform-recovery-plan-review.py", text)
        self.assertIn("terraform-plan-object.py upload", text)
        self.assertIn("Recovery apply is intentionally blocked", text)
        self.assertNotIn("terraform apply", text)
        apply_job = text.split("  recovery-apply:", 1)[1]
        self.assertNotIn("configure-aws-credentials", apply_job)
        self.assertNotIn("terraform-plan-object.py download", apply_job)
        self.assertNotIn("manage_github_oidc_provider=true", text)
        self.assertIn("pawlocal-infrastructure", text)
        self.assertNotIn("upload-artifact", text)

    def test_production_handoff_check_runs_before_plan_and_digest_is_not_shell_interpolated(self):
        text = (ROOT / ".github/workflows/terraform-production-promotion.yml").read_text()
        handoff = text.index("Verify local bootstrap OAC handoff")
        plan = text.index("Initialize production state and create saved plan")
        self.assertLess(handoff, plan)
        self.assertIn("--development-oac-arn \"$PAWLOCAL_DEVELOPMENT_OAC_ARN\"", text)
        self.assertIn("list_role_policies", (ROOT / "ops/verify-terraform-bootstrap-oac-handoff.py").read_text())
        self.assertIn("list_attached_role_policies", (ROOT / "ops/verify-terraform-bootstrap-oac-handoff.py").read_text())
        self.assertNotRegex(text, r'\[\[\s*"\$\{\{\s*inputs\.backend_image_digest')
        self.assertNotIn("-target ", text)

    def test_isolated_roots_have_environment_scoped_outputs_and_state_keys(self):
        for environment in ("development", "production"):
            root = ROOT / "infra/terraform/environments" / environment
            output = (root / "outputs.tf").read_text()
            self.assertIn('output "oac_id"', output)
            self.assertIn('output "oac_arn"', output)
            self.assertIn(environment, (root / "main.tf").read_text())
        workflow = (ROOT / ".github/workflows/terraform-infrastructure-deploy.yml").read_text()
        production = (ROOT / ".github/workflows/terraform-production-promotion.yml").read_text()
        self.assertEqual(workflow.count("PAWLOCAL_OAC_ARN: ${{ vars.PAWLOCAL_DEVELOPMENT_OAC_ARN }}"), 2)
        self.assertEqual(production.count("PAWLOCAL_OAC_ARN: ${{ vars.PAWLOCAL_PRODUCTION_OAC_ARN }}"), 2)
        self.assertIn("Publish OAC identifier for bootstrap policy refresh", workflow)
        self.assertIn("development oac arn for the separate bootstrap policy", workflow.casefold())
        self.assertIn("production oac arn for the separate bootstrap policy", production.casefold())
        self.assertIn("pawlocal/development/terraform.tfstate", workflow)

    def test_production_promotion_requires_successful_development_run_before_plan(self):
        text = (ROOT / ".github/workflows/terraform-production-promotion.yml").read_text()
        preflight = text.index("  validate-development:")
        plan = text.index("  production-plan:")
        apply = text.index("  production-apply:")
        self.assertLess(preflight, plan)
        self.assertLess(plan, apply)
        self.assertIn("run.conclusion !== 'success'", text)
        self.assertIn("run.head_branch !== 'main'", text)
        self.assertIn("run.display_title !== expectedTitle", text)
        self.assertIn("listJobsForWorkflowRun", text)
        self.assertIn("Verify development API and database-backed place query", text)
        self.assertIn("environment: production-apply", text)
        self.assertNotIn("environment: production-plan", text)
        self.assertIn("terraform-plan-object.py upload", text)
        self.assertIn("terraform-plan-object.py download", text)
        self.assertIn("Apply the exact reviewed production plan", text)
        self.assertNotIn("upload-artifact", text)

    def test_active_terraform_delivery_helpers_do_not_invoke_aws_cli(self):
        files = (
            ".github/workflows/terraform-infrastructure-deploy.yml",
            ".github/workflows/terraform-recovery.yml",
            ".github/workflows/fullstack-release.yml",
            ".github/workflows/deploy-production.yml",
            ".github/workflows/rollback-development.yml",
            "ops/terraform-lightsail-container-deploy.sh",
            "ops/deployment-adapters/lightsail-dsql.sh",
            "ops/publish-frontend-artifact.py",
            "ops/verify-lightsail-container-deployment.py",
        )
        aws_cli = re.compile(r"(?:^|\s)aws\s+(?:s3|sts|cloudfront|lightsail|iam|dsql)\s", re.MULTILINE)
        for name in files:
            with self.subTest(file=name):
                self.assertIsNone(aws_cli.search((ROOT / name).read_text()))


class TerraformRecoveryReviewTests(unittest.TestCase):
    def test_non_mutating_data_source_reads_and_noops_are_allowed(self):
        plan = {
            "format_version": "1.2",
            "resource_changes": [
                {
                    "address": "data.aws_caller_identity.current",
                    "mode": "data",
                    "type": "aws_caller_identity",
                    "change": {"actions": ["read"]},
                },
                {
                    "address": "aws_s3_bucket.site",
                    "mode": "managed",
                    "type": "aws_s3_bucket",
                    "change": {"actions": ["no-op"]},
                },
            ],
        }
        rendered = recovery_review.render(plan, "terraform-state-bucket")
        self.assertIn("Resources to delete: 0", rendered)
        self.assertIn("Non-mutating reads/no-ops: 2", rendered)

    def test_only_deletes_are_allowed_and_backend_bucket_is_protected(self):
        safe = {
            "format_version": "1.2",
            "resource_changes": [{
                "address": "aws_s3_bucket.site",
                "type": "aws_s3_bucket",
                "change": {"actions": ["delete"], "before": {"bucket": "pawlocal-frontend-old", "secret": "hidden"}},
            }],
        }
        rendered = recovery_review.render(safe, "terraform-state-bucket")
        self.assertNotIn("hidden", rendered)
        self.assertIn("aws_s3_bucket", rendered)
        self.assertNotIn("aws_s3_bucket.site", rendered)
        backend = {
            "format_version": "1.2",
            "resource_changes": [{
                "address": "aws_s3_bucket.state",
                "type": "aws_s3_bucket",
                "change": {"actions": ["delete"], "before": {"bucket": "terraform-state-bucket"}},
            }],
        }
        with self.assertRaisesRegex(ValueError, "backend bucket"):
            recovery_review.render(backend, "terraform-state-bucket")

    def test_rejects_update_replace_and_unknown_resources(self):
        for resource_type, actions in (
            ("aws_s3_bucket", ["update"]),
            ("aws_s3_bucket", ["delete", "create"]),
            ("aws_unknown_resource", ["delete"]),
        ):
            plan = {
                "format_version": "1.2",
                "resource_changes": [{
                    "address": "aws_s3_bucket.site",
                    "type": resource_type,
                    "change": {"actions": actions, "before": {"bucket": "app-bucket"}},
                }],
            }
            with self.subTest(resource_type=resource_type, actions=actions), self.assertRaises(ValueError):
                recovery_review.render(plan, "terraform-state-bucket")


if __name__ == "__main__":
    unittest.main()
