"""Policy tests for the supported production destroy and clean-redeploy lifecycle."""

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / ".github/scripts/terraform-production-lifecycle.py"


def load_module():
    spec = importlib.util.spec_from_file_location("terraform_production_lifecycle", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def plan_header() -> dict:
    return {
        "applyable": True,
        "complete": True,
        "errored": False,
        "deferred_changes": [],
        "variables": {
            "teardown_enabled": {"value": True},
        },
        "prior_state": {
            "values": {
                "outputs": {"environment_targets": {"value": {"environment": "production"}}}
            }
        },
        "planned_values": {
            "root_module": {
                "child_modules": [
                    {
                        "resources": [
                            {
                                "address": "module.pawlocal.aws_s3_bucket.frontend",
                                "values": {"force_destroy": True},
                            },
                            {
                                "address": "module.pawlocal.aws_dsql_cluster.application",
                                "values": {
                                    "force_destroy": True,
                                    "deletion_protection_enabled": False,
                                },
                            },
                            {
                                "address": "module.pawlocal.aws_iam_policy.frontend_teardown[0]",
                                "values": {},
                            },
                            {
                                "address": "module.pawlocal.aws_iam_role_policy_attachment.frontend_teardown[0]",
                                "values": {},
                            },
                        ]
                    }
                ]
            }
        },
    }


class TerraformProductionLifecycleTests(unittest.TestCase):
    def test_teardown_is_default_off_and_only_production_root_can_enable_it(self) -> None:
        module_variables = (
            ROOT / "infra/terraform/modules/pawlocal-environment/variables.tf"
        ).read_text(encoding="utf-8")
        module_main = (ROOT / "infra/terraform/modules/pawlocal-environment/main.tf").read_text(
            encoding="utf-8"
        )
        production = (ROOT / "infra/terraform/environments/production/main.tf").read_text(
            encoding="utf-8"
        )
        development = (ROOT / "infra/terraform/environments/development/main.tf").read_text(
            encoding="utf-8"
        )
        bootstrap = (ROOT / "infra/terraform/iam-bootstrap/main.tf").read_text(encoding="utf-8")
        self.assertIn('variable "teardown_enabled"', module_variables)
        teardown_block = module_variables.split('variable "teardown_enabled"', 1)[1].split("}", 1)[0]
        self.assertIn("default     = false", teardown_block)
        self.assertIn("force_destroy = var.teardown_enabled", module_main)
        self.assertIn("deletion_protection_enabled = !var.teardown_enabled", module_main)
        bucket_block = module_main.split('resource "aws_s3_bucket" "frontend"', 1)[1].split(
            'resource "aws_s3_bucket_ownership_controls"', 1
        )[0]
        self.assertIn("aws_iam_role_policy_attachment.frontend_teardown", bucket_block)
        self.assertIn("teardown_enabled            = var.teardown_enabled", production)
        self.assertNotIn("teardown_enabled", development)
        attach_block = bootstrap.split("AttachOnlyMatchingApplicationPolicyToApplyRole", 1)[1].split(
            "AttachOnlyMatchingPublishPolicyToPublishRole", 1
        )[0]
        self.assertIn('each.value.environment == "production"', attach_block)
        self.assertIn("[4]", attach_block)

    def test_preparation_guard_accepts_only_complete_teardown_transition(self) -> None:
        module = load_module()
        plan = plan_header()
        plan["resource_changes"] = [
            {
                "address": "module.pawlocal.aws_s3_bucket.frontend",
                "type": "aws_s3_bucket",
                "change": {
                    "actions": ["update"],
                    "before": {"force_destroy": False, "bucket": "example"},
                    "after": {"force_destroy": True, "bucket": "example"},
                },
            },
            {
                "address": "module.pawlocal.aws_dsql_cluster.application",
                "type": "aws_dsql_cluster",
                "change": {
                    "actions": ["update"],
                    "before": {
                        "force_destroy": False,
                        "deletion_protection_enabled": True,
                        "encryption_details": [{"status": "enabled"}],
                    },
                    "after": {
                        "force_destroy": True,
                        "deletion_protection_enabled": False,
                        "encryption_details": None,
                    },
                },
            },
            {
                "address": "module.pawlocal.aws_iam_policy.frontend_teardown[0]",
                "type": "aws_iam_policy",
                "change": {
                    "actions": ["create"],
                    "before": None,
                    "after": {
                        "name": "pawlocal-production-frontend-teardown",
                        "policy": json.dumps(
                            {
                                "Version": "2012-10-17",
                                "Statement": [
                                    {
                                        "Effect": "Allow",
                                        "Action": "s3:DeleteObject",
                                        "Resource": "arn:aws:s3:::pawlocal-production-*/*",
                                    }
                                ],
                            }
                        ),
                    },
                },
            },
            {
                "address": "module.pawlocal.aws_iam_role_policy_attachment.frontend_teardown[0]",
                "type": "aws_iam_role_policy_attachment",
                "change": {
                    "actions": ["create"],
                    "before": None,
                    "after": {
                        "role": "pawlocal-production-terraform-apply",
                        "policy_arn": "arn:aws:iam::000000000000:policy/pawlocal-production-frontend-teardown",
                    },
                },
            },
        ]
        module.validate_preparation(plan)
        # A normal rerun after the preparation apply can be a complete no-op.
        plan["resource_changes"] = []
        plan["applyable"] = False
        module.validate_preparation(plan)

        # A partial prior apply is retried only through the remaining allowed
        # teardown controls, while the full planned configuration stays ready.
        plan["applyable"] = True
        plan["resource_changes"] = [
            {
                "address": "module.pawlocal.aws_s3_bucket.frontend",
                "type": "aws_s3_bucket",
                "change": {
                    "actions": ["update"],
                    "before": {"force_destroy": False},
                    "after": {"force_destroy": True},
                },
            }
        ]
        module.validate_preparation(plan)

        plan["resource_changes"] = [
            {
                "address": "module.pawlocal.aws_s3_bucket.frontend",
                "type": "aws_s3_bucket",
                "change": {
                    "actions": ["update"],
                    "before": {"force_destroy": False, "bucket": "example"},
                    "after": {"force_destroy": True, "bucket": "changed"},
                },
            }
        ]
        with self.assertRaises(SystemExit):
            module.validate_preparation(plan)

    def test_destroy_guard_requires_every_prior_managed_resource_and_only_deletes(self) -> None:
        module = load_module()
        plan = plan_header()
        plan["prior_state"] = {
            "values": {
                "outputs": {"environment_targets": {"value": {"environment": "production"}}},
                "root_module": {
                    "child_modules": [
                        {
                            "resources": [
                                {
                                    "address": "module.pawlocal.aws_s3_bucket.frontend",
                                    "mode": "managed",
                                    "type": "aws_s3_bucket",
                                },
                                {
                                    "address": "module.pawlocal.aws_dsql_cluster.application",
                                    "mode": "managed",
                                    "type": "aws_dsql_cluster",
                                },
                            ]
                        }
                    ]
                }
            }
        }
        plan["resource_changes"] = [
            {
                "address": "module.pawlocal.aws_s3_bucket.frontend",
                "mode": "managed",
                "type": "aws_s3_bucket",
                "change": {"actions": ["delete"]},
            },
            {
                "address": "module.pawlocal.aws_dsql_cluster.application",
                "mode": "managed",
                "type": "aws_dsql_cluster",
                "change": {"actions": ["delete"]},
            },
        ]
        module.validate_destroy(plan)
        plan["resource_changes"].pop()
        with self.assertRaises(SystemExit):
            module.validate_destroy(plan)

    def test_empty_state_verification_rejects_missing_and_nonempty_state(self) -> None:
        module = load_module()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = root / "state.json"
            with self.assertRaises(SystemExit):
                module.verify_empty(state)
            state.write_text(
                json.dumps({"resources": [{"type": "aws_s3_bucket"}], "outputs": {}}),
                encoding="utf-8",
            )
            with self.assertRaises(SystemExit):
                module.verify_empty(state)
            state.write_text(
                json.dumps({"resources": [], "outputs": {}}),
                encoding="utf-8",
            )
            module.verify_empty(state)

    def test_workflow_has_two_approvals_shared_concurrency_and_empty_state_proof(self) -> None:
        workflow = (ROOT / ".github/workflows/terraform-environment-destroy.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("group: pawlocal-terraform-${{ inputs.environment }}", workflow)
        self.assertIn("environment: production-destroy-prepare", workflow)
        self.assertIn("environment: production-destroy", workflow)
        self.assertEqual(workflow.count("terraform-plan-metadata.py create"), 2)
        self.assertEqual(workflow.count("terraform-plan-metadata.py verify"), 2)
        self.assertIn("verify-empty-state", workflow)
        self.assertNotIn("reconcile-environment-outputs.py", workflow)
        self.assertNotIn("invalidate-environment-outputs.yml", workflow)
        self.assertNotIn("force-unlock", workflow)
        self.assertNotIn("terraform import", workflow)

    def test_environment_workflow_exposes_explicit_safe_phases(self) -> None:
        workflow = (ROOT / ".github/workflows/terraform-environment.yml").read_text(encoding="utf-8")
        self.assertIn("phase:", workflow)
        self.assertIn("options: [foundation, converge, release]", workflow)
        self.assertIn("inputs.phase == 'foundation'", workflow)
        self.assertIn("phase: release", (ROOT / ".github/workflows/deploy-production.yml").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
