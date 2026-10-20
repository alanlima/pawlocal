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
FULLSTACK_RELEASE_WORKFLOW = ROOT / ".github/workflows/fullstack-release.yml"
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
    def run_gate(
        self,
        mode: str,
        plan: dict[str, object],
        *,
        stage: str | None = None,
        destroy_prepare_guard: bool = False,
    ) -> subprocess.CompletedProcess[str]:
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
            if stage is not None:
                environment["PLAN_STAGE"] = stage
            command = [sys.executable, str(GATE), str(plan_path)]
            if destroy_prepare_guard:
                command.append("--destroy-prepare-guard")
            return subprocess.run(
                command,
                cwd=ROOT / "infra/terraform",
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )

    def run_destroy_prepare_guard(
        self,
        changes: list[dict[str, object]],
    ) -> subprocess.CompletedProcess[str]:
        return self.run_gate(
            "apply",
            {
                "applyable": True,
                "complete": True,
                "errored": False,
                "planned_values": {"root_module": {}},
                "prior_state": {"values": account_state(EXPECTED_ACCOUNT)},
                "resource_changes": changes,
                "output_changes": {},
            },
            stage="destroy-prepare",
            destroy_prepare_guard=True,
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

    def test_destroy_preparation_allows_only_dsql_force_destroy_and_computed_encryption(self) -> None:
        for environment in ("development", "production"):
            with self.subTest(environment=environment):
                result = self.run_destroy_prepare_guard([
                    {
                        "address": f'module.fullstack.aws_dsql_cluster.app["{environment}"]',
                        "mode": "managed",
                        "change": {
                            "actions": ["update"],
                            "before": {
                                "force_destroy": False,
                                "kms_encryption_key": "AWS_OWNED_KMS_KEY",
                                "encryption_details": [{
                                    "encryption_status": "ENABLED",
                                    "encryption_type": "AWS_OWNED_KMS_KEY",
                                }],
                            },
                            "after": {
                                "force_destroy": True,
                                "kms_encryption_key": "AWS_OWNED_KMS_KEY",
                                "encryption_details": None,
                            },
                            "after_unknown": {
                                "encryption_details": [{"encryption_status": True, "encryption_type": True}],
                            },
                        },
                    },
                ])
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_destroy_preparation_still_rejects_dsql_configuration_change(self) -> None:
        result = self.run_destroy_prepare_guard([
            {
                "address": 'module.fullstack.aws_dsql_cluster.app["development"]',
                "mode": "managed",
                "change": {
                    "actions": ["update"],
                    "before": {
                        "force_destroy": False,
                        "kms_encryption_key": "AWS_OWNED_KMS_KEY",
                        "encryption_details": [{"encryption_type": "AWS_OWNED_KMS_KEY"}],
                    },
                    "after": {
                        "force_destroy": True,
                        "kms_encryption_key": "different-key-setting",
                        "encryption_details": None,
                    },
                    "after_unknown": {"encryption_details": [{"encryption_type": True}]},
                },
            },
        ])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("$.kms_encryption_key", result.stderr)

    def test_destroy_preparation_rejects_known_dsql_encryption_change(self) -> None:
        result = self.run_destroy_prepare_guard([
            {
                "address": 'module.fullstack.aws_dsql_cluster.app["development"]',
                "mode": "managed",
                "change": {
                    "actions": ["update"],
                    "before": {
                        "force_destroy": False,
                        "kms_encryption_key": "AWS_OWNED_KMS_KEY",
                        "encryption_details": [{"encryption_type": "AWS_OWNED_KMS_KEY"}],
                    },
                    "after": {
                        "force_destroy": True,
                        "kms_encryption_key": "AWS_OWNED_KMS_KEY",
                        "encryption_details": [{"encryption_type": "CUSTOMER_MANAGED_KMS_KEY"}],
                    },
                    "after_unknown": {"encryption_details": False},
                },
            },
        ])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("$.encryption_details", result.stderr)

    def test_destroy_preparation_rejects_known_sibling_with_unknown_dsql_encryption_field(self) -> None:
        result = self.run_destroy_prepare_guard([
            {
                "address": 'module.fullstack.aws_dsql_cluster.app["development"]',
                "mode": "managed",
                "change": {
                    "actions": ["update"],
                    "before": {
                        "force_destroy": False,
                        "kms_encryption_key": "AWS_OWNED_KMS_KEY",
                        "encryption_details": [{
                            "encryption_type": "AWS_OWNED_KMS_KEY",
                            "encryption_status": "ENABLED",
                        }],
                    },
                    "after": {
                        "force_destroy": True,
                        "kms_encryption_key": "AWS_OWNED_KMS_KEY",
                        "encryption_details": [{
                            "encryption_type": "CUSTOMER_MANAGED_KMS_KEY",
                            "encryption_status": None,
                        }],
                    },
                    "after_unknown": {
                        "encryption_details": [{
                            "encryption_type": False,
                            "encryption_status": True,
                        }],
                    },
                },
            },
        ])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("$.encryption_details", result.stderr)

    def test_destroy_preparation_rejects_unknown_dsql_kms_key_even_when_null(self) -> None:
        result = self.run_destroy_prepare_guard([
            {
                "address": 'module.fullstack.aws_dsql_cluster.app["development"]',
                "mode": "managed",
                "change": {
                    "actions": ["update"],
                    "before": {
                        "force_destroy": False,
                        "kms_encryption_key": None,
                        "encryption_details": None,
                    },
                    "after": {
                        "force_destroy": True,
                        "kms_encryption_key": None,
                        "encryption_details": None,
                    },
                    "after_unknown": {
                        "kms_encryption_key": True,
                        "encryption_details": [{"encryption_status": True}],
                    },
                },
            },
        ])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Teardown preparation plan includes changes beyond force_destroy settings", result.stderr)

    def test_destroy_preparation_rejects_sensitive_dsql_configuration_metadata(self) -> None:
        result = self.run_destroy_prepare_guard([
            {
                "address": 'module.fullstack.aws_dsql_cluster.app["development"]',
                "mode": "managed",
                "change": {
                    "actions": ["update"],
                    "before": {"force_destroy": False, "kms_encryption_key": None},
                    "after": {"force_destroy": True, "kms_encryption_key": None},
                    "after_unknown": {},
                    "after_sensitive": {"kms_encryption_key": True},
                },
            },
        ])
        self.assertNotEqual(result.returncode, 0)

    def test_destroy_preparation_still_rejects_policy_changes_and_role_forget(self) -> None:
        policy_addresses = [
            "aws_iam_role_policy.github_deploy",
            "aws_s3_bucket_policy.site",
            'module.fullstack.aws_dsql_cluster_policy.api_connect["development"]',
            'module.fullstack.aws_iam_role_policy.github_deploy["development"]',
            'module.fullstack.aws_iam_role_policy.github_terraform_deploy["development"]',
            'module.fullstack.aws_iam_role_policy.github_terraform_deploy["production"]',
            'module.fullstack.aws_s3_bucket_policy.frontend["development"]',
        ]
        policy_updates = [
            {
                "address": address,
                "mode": "managed",
                "change": {"actions": ["update"], "before": {"policy": "before"}, "after": {"policy": "after"}},
            }
            for address in policy_addresses
        ]
        role_forget = {
            "address": 'module.fullstack.aws_iam_role.github_deploy["development"]',
            "mode": "managed",
            "change": {"actions": ["forget"], "before": {"name": "pawlocal-development-github-deploy"}, "after": None},
        }
        result = self.run_destroy_prepare_guard(policy_updates + [role_forget])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Teardown preparation plan includes changes beyond force_destroy settings", result.stderr)
        for address in policy_addresses:
            with self.subTest(address=address):
                self.assertIn(address, result.stderr)
        self.assertIn("actions=forget", result.stderr)

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
                self.assertIn(f"TERRAFORM_ROLE_ARN: ${{{{ vars.{expected_role} }}}}", job)
                self.assertIn(f"TERRAFORM_ROLE_VARIABLE_NAME: {expected_role}", job)
                self.assertIn("role-to-assume: ${{ env.TERRAFORM_ROLE_ARN }}", job)
                self.assertIn('test -n "$PLAN_TRANSFER_BUCKET"', job)
                self.assertIn('[[ -z "${!name}" ]]', job)
                for required_variable in (
                    "AWS_REGION", "PAWLOCAL_AWS_ACCOUNT_ID", "PAWLOCAL_TF_STATE_BUCKET",
                    "PAWLOCAL_DOMAIN_NAME", "PAWLOCAL_CERTIFICATE_ARN",
                ):
                    self.assertIn(required_variable, job)
                self.assertIn("allowed-account-ids: ${{ vars.PAWLOCAL_AWS_ACCOUNT_ID }}", job)
                account_check = job.index("steps.aws-credentials.outputs.aws-account-id")
                role_validation = job.index("${TERRAFORM_ROLE_VARIABLE_NAME} must belong")
                terraform_calls = [
                    position
                    for command in ("terraform init", "terraform plan", "terraform apply")
                    if (position := job.find(command)) >= 0
                ]
                self.assertTrue(terraform_calls, "expected an AWS-backed Terraform command")
                self.assertLess(role_validation, credential_step)
                self.assertLess(credential_step, account_check)
                self.assertLess(account_check, min(terraform_calls))

    def test_destroy_preparation_exception_is_opt_in_typed_and_destroy_only(self) -> None:
        source = WORKFLOW.read_text(encoding="utf-8")
        dispatch_inputs = source.split("    inputs:\n", 1)[1].split("\npermissions:", 1)[0]
        self.assertIn("allow_expected_destroy_preparation_changes:", dispatch_inputs)
        self.assertIn("default: false", dispatch_inputs)
        self.assertIn("type: boolean", dispatch_inputs)
        self.assertIn("destroy_preparation_change_confirmation:", dispatch_inputs)
        self.assertIn("ACCEPT EXPECTED TEARDOWN PREPARATION CHANGES", dispatch_inputs)
        self.assertIn("ALLOW_EXPECTED_DESTROY_PREPARATION_CHANGES", source)
        self.assertIn("The teardown-preparation exception is available only for destroy.", source)
        self.assertIn("The teardown-preparation exception requires its exact typed confirmation.", source)

    def test_exception_skips_only_preparation_guard_and_documents_deferred_iam(self) -> None:
        source = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn(
            "python ../../.github/scripts/terraform-plan-gate.py \"$RUNNER_TEMP/terraform-plan.json\" >> \"$GITHUB_STEP_SUMMARY\"",
            source,
        )
        self.assertIn(
            "if: steps.plan.outputs.plan_stage == 'destroy-prepare' && inputs.allow_expected_destroy_preparation_changes != true",
            source,
        )
        self.assertIn(
            "if: inputs.operation == 'destroy'",
            source,
        )
        self.assertIn("Note deferred IAM bootstrap ownership work", source)
        self.assertIn("IAM/bootstrap ownership deferred until recreation", source)
        self.assertIn("destroy = false` lifecycle block leaves the development GitHub publisher role in AWS", source)
        self.assertIn("this destroy does not remove that role", source)
        self.assertIn("handled by the full destroy plan", source)
        for job_name in ("prepare-destroy", "destroy"):
            start = source.index(f"  {job_name}:\n")
            next_job = re.search(r"(?m)^  [a-z][a-z-]+:\s*$", source[start + 1 :])
            end = start + 1 + next_job.start() if next_job else len(source)
            self.assertIn("environment: infrastructure-apply", source[start:end])

    def test_fullstack_release_ignores_current_stack_operations_only_changes(self) -> None:
        source = FULLSTACK_RELEASE_WORKFLOW.read_text(encoding="utf-8")
        pull_request_paths = source.split("  pull_request:\n", 1)[1].split("  push:\n", 1)[0]
        push_paths = source.split("  push:\n", 1)[1].split("  workflow_dispatch:", 1)[0]
        operations_workflow = '"!.github/workflows/terraform-current-stack-operations.yml"'
        self.assertIn(operations_workflow, pull_request_paths)
        self.assertIn(operations_workflow, push_paths)
        self.assertIn('"!.github/workflows/fullstack-release.yml"', push_paths)
        self.assertNotIn('"!.github/workflows/fullstack-release.yml"', pull_request_paths)


if __name__ == "__main__":
    unittest.main()
