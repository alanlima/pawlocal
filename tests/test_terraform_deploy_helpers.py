from __future__ import annotations

import importlib.util
import json
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
recovery_oidc = load_helper("terraform-recovery-oidc-preflight")
identity_review = load_helper("terraform-identity-plan-review")
protection_review = load_helper("terraform-recovery-protection-review")
bootstrap_oac = load_helper("verify-terraform-bootstrap-oac-handoff")
bootstrap_cf_tag = load_helper("verify-terraform-bootstrap-cloudfront-tag-grant")


class BootstrapOacHandoffTests(unittest.TestCase):
    dev_arn = "arn:aws:cloudfront::123456789012:origin-access-control/EDEV123"
    prod_arn = "arn:aws:cloudfront::123456789012:origin-access-control/EPROD123"

    def policy(self, statements):
        return {"Version": "2012-10-17", "Statement": statements}

    class FakeIam:
        def __init__(self, inline_pages=None, attached_pages=None):
            self.inline_pages = inline_pages or [{"PolicyNames": [bootstrap_oac.DEV_POLICY, bootstrap_oac.DEV_SERVICE_POLICY], "IsTruncated": False}]
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
            "PolicyNames": [bootstrap_oac.DEV_POLICY, bootstrap_oac.DEV_SERVICE_POLICY, "unexpected-extra"], "IsTruncated": False,
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
            {"PolicyNames": [bootstrap_oac.DEV_SERVICE_POLICY, "late-extra"], "IsTruncated": False},
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
                {"PolicyNames": [bootstrap_oac.DEV_SERVICE_POLICY], "IsTruncated": False},
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
        self.assertEqual(iam.gets, [(bootstrap_oac.DEV_ROLE, bootstrap_oac.DEV_SERVICE_POLICY),
                                    (bootstrap_oac.DEV_ROLE, bootstrap_oac.DEV_POLICY)])

    def test_pinned_production_policy_requires_exact_arn(self):
        dev = self.policy([{
            "Effect": "Allow", "Action": sorted(bootstrap_oac.READ_ACTIONS | bootstrap_oac.MUTATE_ACTIONS), "Resource": self.dev_arn,
        }])
        prod = self.policy([{
            "Effect": "Allow", "Action": sorted(bootstrap_oac.READ_ACTIONS | bootstrap_oac.MUTATE_ACTIONS), "Resource": self.prod_arn,
        }])
        self.assertEqual(bootstrap_oac.verify_handoff(dev, prod, self.dev_arn, self.prod_arn), "existing-production-oac-pinned")

    def test_oac_handoff_ignores_other_exact_cloudfront_service_actions(self):
        dev = self.policy([
            {
                "Effect": "Allow",
                "Action": sorted(bootstrap_oac.READ_ACTIONS | bootstrap_oac.MUTATE_ACTIONS),
                "Resource": self.dev_arn,
            },
            {
                "Effect": "Allow",
                "Action": ["cloudfront:CreateDistribution", "cloudfront:TagResource"],
                "Resource": "arn:aws:cloudfront::123456789012:distribution/*",
            },
        ])
        prod = self.policy([{
            "Effect": "Allow",
            "Action": sorted(bootstrap_oac.READ_ACTIONS | {bootstrap_oac.CREATE_ACTION}),
            "Resource": "*",
        }])
        self.assertEqual(
            bootstrap_oac.verify_handoff(dev, prod, self.dev_arn, account_id="123456789012"),
            "production-oac-create-window-enabled",
        )


class BootstrapCloudFrontTagGrantTests(unittest.TestCase):
    account_id = "123456789012"

    class FakeIam:
        def __init__(self, env_policy_overrides=None, extra_names=None, attached=None):
            self.documents = {}
            self.requests = []
            self.extra_names = extra_names or {}
            self.attached = attached or {}
            for environment in bootstrap_cf_tag.ENVIRONMENTS:
                role = f"pawlocal-{environment}-terraform-apply"
                names = [f"{role}-permissions", f"pawlocal-{environment}-terraform-application-services"]
                names += self.extra_names.get(environment, [])
                self.documents[(role, names[0])] = {"Statement": []}
                self.documents[(role, names[1])] = {"Statement": [
                    bootstrap_cf_tag._expected_statement(environment, BootstrapCloudFrontTagGrantTests.account_id),
                    bootstrap_cf_tag._expected_update_statement(environment, BootstrapCloudFrontTagGrantTests.account_id),
                ]}
                for name, document in (env_policy_overrides or {}).get(environment, {}).items():
                    self.documents[(role, name)] = document

        def list_role_policies(self, RoleName, Marker=None):
            self.requests.append(("list", RoleName))
            names = [name for role, name in self.documents if role == RoleName]
            names += self.extra_names.get(RoleName.removeprefix("pawlocal-").split("-terraform-apply")[0], [])
            return {"PolicyNames": names, "IsTruncated": False}

        def list_attached_role_policies(self, RoleName, Marker=None):
            self.requests.append(("attached", RoleName))
            return {"AttachedPolicies": self.attached.get(RoleName, []), "IsTruncated": False}

        def get_role_policy(self, RoleName, PolicyName):
            self.requests.append(("get", RoleName, PolicyName))
            return {"PolicyDocument": self.documents[(RoleName, PolicyName)]}

    def test_both_roles_require_exact_account_scoped_conditioned_grant(self):
        result = bootstrap_cf_tag.verify(self.FakeIam(), self.account_id)
        self.assertIn("cross-environment retagging and configuration risk is accepted", result)

    def test_environment_check_reads_only_matching_role_and_validates_both_grants(self):
        iam = self.FakeIam()
        self.assertIn("cross-environment", bootstrap_cf_tag.verify(iam, self.account_id, "development"))
        self.assertEqual({request[1] for request in iam.requests}, {"pawlocal-development-terraform-apply"})

    def test_update_distribution_scope_and_conditions_fail_closed(self):
        for mutation in (
            lambda statement: statement.update(Resource="*"),
            lambda statement: statement.update(Resource="arn:aws:cloudfront::999999999999:distribution/*"),
            lambda statement: statement["Condition"]["StringEquals"].update({"aws:ResourceTag/project": "other"}),
            lambda statement: statement["Condition"]["StringEquals"].update({"aws:ResourceTag/environment": "production"}),
            lambda statement: statement.update(Action=[bootstrap_cf_tag.UPDATE_ACTION, "cloudfront:TagResource"]),
        ):
            update = bootstrap_cf_tag._expected_update_statement("development", self.account_id)
            mutation(update)
            iam = self.FakeIam(env_policy_overrides={
                "development": {"pawlocal-development-terraform-application-services": {"Statement": [
                    bootstrap_cf_tag._expected_statement("development", self.account_id), update,
                ]}}
            })
            with self.subTest(update=update), self.assertRaises(ValueError):
                bootstrap_cf_tag.verify(iam, self.account_id, "development")

    def test_update_distribution_in_wrong_policy_or_duplicated_is_rejected(self):
        update = bootstrap_cf_tag._expected_update_statement("development", self.account_id)
        for misplaced, duplicate in ((True, False), (False, True)):
            service_statements = [bootstrap_cf_tag._expected_statement("development", self.account_id)]
            if not misplaced:
                service_statements.append(update)
            permissions_statements = [update] if misplaced else ([{ "Sid": "Extra", **update }] if duplicate else [])
            iam = self.FakeIam(env_policy_overrides={
                "development": {
                    "pawlocal-development-terraform-application-services": {"Statement": service_statements},
                    "pawlocal-development-terraform-apply-permissions": {"Statement": permissions_statements},
                }
            })
            with self.subTest(misplaced=misplaced, duplicate=duplicate), self.assertRaises(ValueError):
                bootstrap_cf_tag.verify(iam, self.account_id, "development")

    def test_wrong_account_resource_or_tag_conditions_fail_closed(self):
        for mutation in (
            lambda s: s.update(Resource="*"),
            lambda s: s.update(Resource="arn:aws:cloudfront::999999999999:distribution/*"),
            lambda s: s["Condition"]["StringEquals"].update({"aws:RequestTag/project": "other"}),
            lambda s: s["Condition"]["StringEquals"].update({"aws:RequestTag/environment": "production"}),
            lambda s: s["Condition"]["ForAllValues:StringEquals"].update({"aws:TagKeys": ["project"]}),
        ):
            policy = bootstrap_cf_tag._expected_statement("development", self.account_id)
            mutation(policy)
            iam = self.FakeIam(env_policy_overrides={
                "development": {"pawlocal-development-terraform-application-services": {"Statement": [policy]}}
            })
            with self.subTest(policy=policy), self.assertRaises(ValueError):
                bootstrap_cf_tag.verify(iam, self.account_id)

    def test_wildcard_or_extra_tagresource_grants_fail_closed(self):
        expected = bootstrap_cf_tag._expected_statement("development", self.account_id)
        for statement in (
            {"Effect": "Allow", "Action": "*", "Resource": "*"},
            {"Effect": "Allow", "NotAction": "iam:*", "Resource": "*"},
            {"Effect": "Allow", "Action": "cloudfront:TagResource", "Resource": "*"},
        ):
            iam = self.FakeIam(env_policy_overrides={
                "development": {"pawlocal-development-terraform-apply-permissions": {"Statement": [statement]}}
            })
            with self.subTest(statement=statement), self.assertRaises(ValueError):
                bootstrap_cf_tag.verify(iam, self.account_id)
        self.assertEqual(expected["Sid"], bootstrap_cf_tag.TAG_STATEMENT_SID)

    def test_extra_inline_managed_policy_and_bad_account_fail_closed(self):
        role = "pawlocal-development-terraform-apply"
        cases = (
            (self.FakeIam(extra_names={"development": ["extra"]}), self.account_id),
            (self.FakeIam(attached={role: [{"PolicyArn": "arn:aws:iam::123456789012:policy/extra"}]}), self.account_id),
            (self.FakeIam(), "1234"),
        )
        for iam, account in cases:
            with self.subTest(account=account), self.assertRaises(ValueError):
                bootstrap_cf_tag.verify(iam, account)


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
        self.assertIn("required: false", text)
        self.assertIn("Require the applied development DSQL runtime identity", text)
        self.assertIn('if: inputs.backend_image_digest != \'\'', text)
        dev_plan_review = text.index("Publish sanitized development plan for review")
        policy_check = text.index("development-apply-policy-check:")
        dev_apply_gate = text.index("development-apply:")
        env_gate = text.index("environment: development-apply")
        self.assertLess(dev_plan_review, policy_check)
        self.assertLess(policy_check, dev_apply_gate)
        self.assertLess(policy_check, env_gate)
        self.assertIn("needs: [development-plan, development-apply-policy-check]", text)
        self.assertIn("--environment development", text)
        self.assertIn("verify-terraform-bootstrap-cloudfront-tag-grant.py", text)
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
        protection = (ROOT / ".github/workflows/terraform-recovery-dsql-protection.yml").read_text()
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
        self.assertIn("dsql_protection_run_id:", text)
        self.assertIn("terraform-recovery-dsql-protection.yml", text)
        self.assertIn("TF_VAR_recovery_disable_dsql_deletion_protection: \"true\"", text)
        self.assertLess(protection.index("Publish exact sanitized DSQL changes"), protection.index("  recovery-protection-apply:"))
        protected_apply = protection.split("  recovery-protection-apply:", 1)[1]
        self.assertIn("if: github.event_name == 'push'", protected_apply)
        self.assertIn("workflow_dispatch:", protection)
        self.assertIn("configure-aws-credentials", protected_apply)
        self.assertIn("terraform apply", protected_apply)
        self.assertIn("pending scoped policy review", protected_apply)
        self.assertIn("environment: terraform-recovery-apply", protection)
        self.assertIn("terraform-plan-object.py download", protection)
        self.assertIn("Apply exact reviewed DSQL protection plan", protection)
        self.assertIn("terraform-recovery-protection-review.py", protection)

    def test_production_handoff_and_policy_check_order_before_approval(self):
        text = (ROOT / ".github/workflows/terraform-production-promotion.yml").read_text()
        handoff = text.index("Verify local bootstrap OAC handoff")
        plan = text.index("Initialize production state and create saved plan")
        review = text.index("Publish sanitized production plan for review")
        policy_check = text.index("production-apply-policy-check:")
        apply = text.index("production-apply:")
        env_gate = text.index("environment: production-apply")
        self.assertLess(handoff, plan)
        self.assertLess(plan, review)
        self.assertLess(review, policy_check)
        self.assertLess(policy_check, apply)
        self.assertLess(policy_check, env_gate)
        self.assertIn("needs: [production-plan, production-apply-policy-check]", text)
        self.assertIn("--environment production", text)
        self.assertIn("verify-terraform-bootstrap-cloudfront-tag-grant.py", text)
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
        self.assertIn('"$GITHUB_SHA" == "$DEVELOPMENT_SHA"', text)
        self.assertIn("listJobsForWorkflowRun", text)
        self.assertIn("Verify development API and database-backed place query", text)
        self.assertIn("environment: production-apply", text)
        self.assertNotIn("environment: production-plan", text)
        self.assertIn("terraform-plan-object.py upload", text)
        self.assertIn("terraform-plan-object.py download", text)
        self.assertIn("Apply the exact reviewed production plan", text)
        self.assertIn("target_stage:", text)
        self.assertIn("production_foundation_run_id:", text)
        self.assertIn("Require the applied production frontend identity", text)
        self.assertIn("foundationRun.conclusion !== 'success'", text)
        self.assertIn("target_stage == 'foundation'", text)
        self.assertIn("target_stage == 'api'", text)
        self.assertNotIn("upload-artifact", text)

    def test_identity_stage_reads_bootstrap_state_and_applies_only_reviewed_plan(self):
        text = (ROOT / ".github/workflows/terraform-identity-deploy.yml").read_text()
        plan = text.index("  identity-plan:")
        apply = text.index("  identity-apply:")
        self.assertLess(plan, apply)
        self.assertIn('key=pawlocal/identity/terraform.tfstate', text)
        self.assertIn("terraform_remote_state", (ROOT / "infra/terraform/identity/main.tf").read_text())
        self.assertIn('key          = "pawlocal/iam-bootstrap/terraform.tfstate"', (ROOT / "infra/terraform/identity/main.tf").read_text())
        self.assertIn("identity_managed_policy_arns", (ROOT / "infra/terraform/identity/main.tf").read_text())
        identity_root = (ROOT / "infra/terraform/identity/main.tf").read_text()
        self.assertIn("data \"aws_iam_role\" \"app\"", identity_root)
        self.assertIn("identity_app_role_arns", identity_root)
        self.assertNotIn('resource "aws_iam_role"', identity_root)
        self.assertNotIn("assume_role_policy", identity_root)
        self.assertIn("aws_iam_role_policy_attachment", identity_root)
        apply_job = text.split("  identity-apply:", 1)[1]
        self.assertIn("environment: identity-apply", apply_job)
        self.assertIn("terraform-plan-object.py download", apply_job)
        self.assertIn("Apply the exact reviewed identity plan", apply_job)
        self.assertNotIn("if: false", apply_job)
        self.assertNotIn("aws iam", text.lower())

    def test_active_terraform_delivery_helpers_do_not_invoke_aws_cli(self):
        files = (
            ".github/workflows/terraform-infrastructure-deploy.yml",
            ".github/workflows/terraform-recovery.yml",
            ".github/workflows/terraform-recovery-dsql-protection.yml",
            ".github/workflows/terraform-identity-deploy.yml",
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
    def complete_plan(self):
        changes = []
        for address in sorted(recovery_review.REQUIRED_MANAGED):
            resource_type = recovery_review._resource_type_from_address(address)
            before = {}
            if resource_type == "aws_s3_bucket":
                if address == "aws_s3_bucket.site":
                    before["bucket"] = "pawlocal-frontend-1234abcd"
                else:
                    env = "development" if "development" in address else "production"
                    before["bucket"] = f"pawlocal-{env}-123abc"
            if resource_type == "aws_iam_openid_connect_provider":
                before["url"] = "https://token.actions.githubusercontent.com"
            if resource_type == "aws_dsql_cluster":
                before["deletion_protection_enabled"] = False
            changes.append({
                "address": address,
                "mode": "managed",
                "type": resource_type,
                "change": {"actions": ["delete"], "before": before},
            })
        return {"format_version": "1.2", "applyable": True, "complete": True, "errored": False,
                "resource_changes": changes}

    def test_complete_plan_shows_exact_resource_addresses_without_values(self):
        rendered = recovery_review.render(self.complete_plan(), "terraform-state-bucket")
        self.assertIn("module.fullstack.aws_cloudfront_distribution.app[\"production\"]", rendered)
        self.assertIn("aws_iam_openid_connect_provider.github[0]", rendered)
        self.assertNotIn("attribute values", rendered)
        self.assertNotIn("pawlocal-frontend-1234abcd", rendered)
        self.assertIn("Only source-declared PawLocal", rendered)

    def test_non_mutating_known_data_read_is_allowed(self):
        plan = self.complete_plan()
        plan["resource_changes"].append({
            "address": "data.aws_caller_identity.current", "mode": "data", "type": "aws_caller_identity",
            "change": {"actions": ["read"]},
        })
        self.assertIn("Non-mutating data reads: 1", recovery_review.render(plan, "terraform-state-bucket"))

    def test_missing_oidc_or_production_frontend_fails_closed(self):
        for address in (
            "aws_iam_openid_connect_provider.github[0]",
            'module.fullstack.aws_cloudfront_distribution.app["production"]',
        ):
            plan = self.complete_plan()
            plan["resource_changes"] = [c for c in plan["resource_changes"] if c["address"] != address]
            with self.subTest(address=address), self.assertRaisesRegex(ValueError, "missing|production frontend"):
                recovery_review.render(plan, "terraform-state-bucket")

    def test_audit_unknown_duplicate_or_non_delete_resources_fail_closed(self):
        for address, resource_type, actions in (
            ('module.fullstack.aws_cloudtrail.dsql_auth[0]', 'aws_cloudtrail', ["delete"]),
            ('aws_s3_bucket.unrelated', 'aws_s3_bucket', ["delete"]),
            ('aws_s3_bucket.site', 'aws_s3_bucket', ["update"]),
            ('aws_s3_bucket.site', 'aws_s3_bucket', ["delete", "create"]),
        ):
            plan = self.complete_plan()
            plan["resource_changes"].append({
                "address": address, "mode": "managed", "type": resource_type,
                "change": {"actions": actions, "before": {"bucket": "other-bucket"}},
            })
            with self.subTest(address=address, actions=actions), self.assertRaises(ValueError):
                recovery_review.render(plan, "terraform-state-bucket")

    def test_backend_and_unverifiable_frontend_bucket_are_rejected(self):
        for bucket in ("terraform-state-bucket", "pawlocal-prod-unknown"):
            plan = self.complete_plan()
            change = next(c for c in plan["resource_changes"] if c["address"] == "aws_s3_bucket.site")
            change["change"]["before"]["bucket"] = bucket
            with self.subTest(bucket=bucket), self.assertRaises(ValueError):
                recovery_review.render(plan, "terraform-state-bucket")


class RecoveryOidcPreflightTests(unittest.TestCase):
    ARN = "arn:aws:iam::123456789012:oidc-provider/token.actions.githubusercontent.com"

    class FakeIam:
        def __init__(self, roles):
            self.roles = roles

        def list_open_id_connect_providers(self, **kwargs):
            return {"OpenIDConnectProviderList": [{"Arn": RecoveryOidcPreflightTests.ARN}]}

        def get_open_id_connect_provider(self, OpenIDConnectProviderArn):
            return {"Url": "token.actions.githubusercontent.com"}

        def list_roles(self, **kwargs):
            return {"Roles": self.roles}

    def test_known_pawlocal_trust_is_allowed(self):
        role = {"RoleName": "pawlocal-frontend-github-deploy", "AssumeRolePolicyDocument": {
            "Statement": [{"Principal": {"Federated": self.ARN}}],
        }}
        self.assertEqual(recovery_oidc.verify(self.FakeIam([role]))[1], [role["RoleName"]])

    def test_unrelated_oidc_trust_fails_closed(self):
        role = {"RoleName": "other-project-github-deploy", "AssumeRolePolicyDocument": {
            "Statement": [{"Principal": {"Federated": self.ARN}}],
        }}
        with self.assertRaisesRegex(ValueError, "outside the PawLocal allowlist"):
            recovery_oidc.verify(self.FakeIam([role]))


class TerraformIdentityPlanReviewTests(unittest.TestCase):
    development_frontend = "arn:aws:iam::123456789012:policy/pawlocal-identity-development-frontend-publish"
    production_frontend = "arn:aws:iam::123456789012:policy/pawlocal-identity-production-frontend-publish"
    development_runtime = "arn:aws:iam::123456789012:policy/pawlocal-identity-development-dsql-connect"

    def policy_arns(self):
        return {"development_frontend": self.development_frontend,
                "production_frontend": self.production_frontend,
                "development_runtime": self.development_runtime}

    def plan(self, environment):
        selected = {
            "development": {
                'aws_iam_role_policy_attachment.app["development_frontend"]': ("pawlocal-development-github-deploy", self.development_frontend),
                'aws_iam_role_policy_attachment.app["development_runtime"]': ("pawlocal-development-dsql-runtime", self.development_runtime),
            },
            "production": {
                'aws_iam_role_policy_attachment.app["production_frontend"]': ("pawlocal-production-github-deploy", self.production_frontend),
            },
        }[environment]
        changes = [{"address": address, "mode": "managed", "type": "aws_iam_role_policy_attachment",
                    "change": {"actions": ["create"], "after": {"role": role, "policy_arn": policy}}}
                   for address, (role, policy) in selected.items()]
        return {"format_version": "1.2", "applyable": True, "complete": True, "errored": False,
                "resource_changes": changes}

    def test_development_identity_attaches_only_fixed_bootstrap_policies(self):
        summary = identity_review.render(self.plan("development"), "development", self.policy_arns())
        self.assertIn('aws_iam_role_policy_attachment.app["development_runtime"]', summary)
        self.assertIn("cannot create roles, change trust", summary)

    def test_identity_plan_rejects_role_creation_and_inline_policy(self):
        plan = self.plan("development")
        plan["resource_changes"].append({"address": 'aws_iam_role_policy.extra["development"]', "type": "aws_iam_role_policy",
                                         "change": {"actions": ["create"]}})
        with self.assertRaises(ValueError):
            identity_review.render(plan, "development", self.policy_arns())
        plan = self.plan("development")
        plan["resource_changes"].append({"address": 'aws_iam_role.github_deploy["production"]', "type": "aws_iam_role",
                                         "change": {"actions": ["create"]}})
        with self.assertRaisesRegex(ValueError, "only the exact approved policy attachments"):
            identity_review.render(plan, "development", self.policy_arns())

    def test_identity_plan_rejects_wrong_role_policy_or_detach(self):
        plan = self.plan("development")
        plan["resource_changes"][0]["change"]["after"]["role"] = "pawlocal-production-github-deploy"
        with self.assertRaisesRegex(ValueError, "exact bootstrap-owned role"):
            identity_review.render(plan, "development", self.policy_arns())
        plan = self.plan("development")
        plan["resource_changes"][0]["change"]["actions"] = ["delete"]
        with self.assertRaisesRegex(ValueError, "updates and detachments are blocked"):
            identity_review.render(plan, "development", self.policy_arns())


class TerraformRecoveryProtectionReviewTests(unittest.TestCase):
    def plan(self):
        changes = []
        for address in sorted(protection_review.EXPECTED):
            changes.append({"address": address, "type": "aws_dsql_cluster", "mode": "managed",
                            "change": {"actions": ["update"], "before": {"deletion_protection_enabled": True},
                                       "after": {"deletion_protection_enabled": False}}})
        return {"format_version": "1.2", "applyable": True, "complete": True, "errored": False,
                "resource_changes": changes}

    def test_only_exact_dsql_protection_changes_are_accepted(self):
        self.assertIn("development", protection_review.render(self.plan()))
        plan = self.plan()
        plan["resource_changes"][0]["change"]["after"]["deletion_protection_enabled"] = True
        with self.assertRaisesRegex(ValueError, "enabled to disabled"):
            protection_review.render(plan)


if __name__ == "__main__":
    unittest.main()
