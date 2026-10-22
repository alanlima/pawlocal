from __future__ import annotations

import os
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[2]
CONFIGURE_SCRIPT = ROOT / ".github/scripts/configure-cognito-terraform-profile.sh"
CLEANUP_SCRIPT = ROOT / ".github/scripts/cleanup-cognito-terraform-profile.sh"
ENVIRONMENT_WORKFLOW = ROOT / ".github/workflows/terraform-environment.yml"
DESTROY_WORKFLOW = ROOT / ".github/workflows/terraform-environment-destroy.yml"
TERRAFORM_CI_WORKFLOW = ROOT / ".github/workflows/terraform-ci.yml"


class CognitoTerraformProfileTests(unittest.TestCase):
    def setUp(self) -> None:
        if os.name == "nt":
            self.skipTest("The delegated-profile shell contract runs on the Linux GitHub runner.")
        if shutil.which("bash") is None:
            self.skipTest("bash is required for the delegated-profile shell contract.")

    def _run_profile(
        self,
        environment: str,
        purpose: str,
        *,
        account_id: str = "111111111111",
        partition: str = "aws",
        caller_account: str | None = None,
        caller_role_name: str | None = None,
        project_name: str = "pawlocal",
        extra_env: dict[str, str] | None = None,
    ) -> tuple[subprocess.CompletedProcess[str], Path, Path]:
        temporary = Path(tempfile.mkdtemp(prefix="pawlocal-cognito-profile-"))
        fake_bin = temporary / "bin"
        fake_bin.mkdir()
        fake_aws = fake_bin / "aws"
        fake_aws.write_text(
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n"
            "[[ \"$*\" == \"sts get-caller-identity --profile ${TF_VAR_project_name}-cognito-deployment --query [Account,Arn] --output text\" ]]\n"
            "printf '%s\\t%s\\n' \"$FAKE_CALLER_ACCOUNT\" \"$FAKE_CALLER_ARN\"\n",
            encoding="utf-8",
        )
        fake_aws.chmod(fake_aws.stat().st_mode | stat.S_IXUSR)

        job = f"{purpose}-{environment}"
        config_file = temporary / f"{project_name}-cognito-deployment-{job}.config"
        github_env = temporary / "github-env"
        role_name = caller_role_name or f"pawlocal-{environment}-cognito-terraform-{purpose}"
        session_name = f"pawlocal-{environment}-cognito-{purpose}"
        caller_arn = f"arn:{partition}:sts::{caller_account or account_id}:assumed-role/{role_name}/{session_name}"
        env = {
            **os.environ,
            "PATH": f"{fake_bin}{os.pathsep}{os.environ.get('PATH', '')}",
            "AWS_ACCESS_KEY_ID": "test",
            "AWS_SECRET_ACCESS_KEY": "test",
            "AWS_SESSION_TOKEN": "test",
            "AWS_CONFIG_FILE": str(config_file),
            "AWS_PARTITION": partition,
            "AWS_REGION": "ap-southeast-2",
            "COGNITO_TERRAFORM_PURPOSE": purpose,
            "FAKE_CALLER_ACCOUNT": caller_account or account_id,
            "FAKE_CALLER_ARN": caller_arn,
            "GITHUB_ENV": str(github_env),
            "GITHUB_JOB": job,
            "PAWLOCAL_AWS_ACCOUNT_ID": account_id,
            "PAWLOCAL_ENVIRONMENT": environment,
            "RUNNER_TEMP": str(temporary),
            "TF_VAR_project_name": project_name,
        }
        env.pop("AWS_PROFILE", None)
        if extra_env:
            env.update(extra_env)

        result = subprocess.run(
            ["bash", str(CONFIGURE_SCRIPT)],
            cwd=ROOT,
            env=env,
            check=False,
            capture_output=True,
            text=True,
        )
        return result, config_file, github_env

    def test_development_plan_profile_is_exact_and_one_hour(self) -> None:
        result, config_file, github_env = self._run_profile("development", "plan")
        self.assertEqual(result.returncode, 0, result.stderr)
        config = config_file.read_text(encoding="utf-8")
        self.assertEqual(
            config,
            "[profile pawlocal-cognito-deployment]\n"
            "role_arn = arn:aws:iam::111111111111:role/pawlocal-development-cognito-terraform-plan\n"
            "credential_source = Environment\n"
            "role_session_name = pawlocal-development-cognito-plan\n"
            "duration_seconds = 3600\n"
            "region = ap-southeast-2\n",
        )
        self.assertIn("::add-mask::arn:aws:iam::111111111111:role/", result.stdout)
        self.assertIn(
            "::add-mask::arn:aws:sts::111111111111:assumed-role/",
            result.stdout,
        )
        github_environment = github_env.read_text(encoding="utf-8")
        self.assertIn(f"AWS_CONFIG_FILE={config_file}\n", github_environment)
        self.assertIn(
            "COGNITO_DEPLOYMENT_PROFILE=pawlocal-cognito-deployment\n",
            github_environment,
        )
        self.assertIn("COGNITO_DELEGATED_ROLE_ARN=arn:aws:iam::111111111111:role/", github_environment)
        self.assertEqual(stat.S_IMODE(config_file.stat().st_mode), 0o600)

    def test_production_apply_profile_is_exact(self) -> None:
        result, config_file, _ = self._run_profile("production", "apply")
        self.assertEqual(result.returncode, 0, result.stderr)
        config = config_file.read_text(encoding="utf-8")
        self.assertIn("role/pawlocal-production-cognito-terraform-apply", config)
        self.assertIn("role_session_name = pawlocal-production-cognito-apply", config)

    def test_non_default_project_name_changes_only_the_profile(self) -> None:
        result, config_file, github_env = self._run_profile(
            "development", "plan", project_name="dogapp"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        config = config_file.read_text(encoding="utf-8")
        self.assertIn("[profile dogapp-cognito-deployment]", config)
        self.assertIn(
            "role/pawlocal-development-cognito-terraform-plan", config
        )
        self.assertIn(
            "COGNITO_DEPLOYMENT_PROFILE=dogapp-cognito-deployment\n",
            github_env.read_text(encoding="utf-8"),
        )

    def test_invalid_inputs_and_global_profile_fail_closed(self) -> None:
        cases = (
            {"environment": "staging", "purpose": "plan"},
            {"environment": "development", "purpose": "destroy"},
            {"environment": "development", "purpose": "plan", "account_id": "123"},
            {"environment": "development", "purpose": "plan", "partition": "aws-us-gov"},
            {"environment": "development", "purpose": "plan", "project_name": "too-long-name"},
            {
                "environment": "development",
                "purpose": "plan",
                "extra_env": {"AWS_PROFILE": "must-not-be-global"},
            },
        )
        for case in cases:
            with self.subTest(case=case):
                result, config_file, _ = self._run_profile(**case)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(config_file.exists())

    def test_wrong_delegated_caller_fails_closed(self) -> None:
        result, _, _ = self._run_profile(
            "development",
            "plan",
            caller_role_name="pawlocal-production-cognito-terraform-plan",
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unexpected caller identity", result.stderr)

    def test_cleanup_removes_only_the_workflow_owned_config(self) -> None:
        result, config_file, _ = self._run_profile(
            "production", "apply", project_name="dogapp"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        env = {
            **os.environ,
            "AWS_CONFIG_FILE": str(config_file),
            "RUNNER_TEMP": str(config_file.parent),
            "TF_VAR_project_name": "dogapp",
        }
        cleanup = subprocess.run(
            ["bash", str(CLEANUP_SCRIPT)],
            cwd=ROOT,
            env=env,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(cleanup.returncode, 0, cleanup.stderr)
        self.assertFalse(config_file.exists())

        mismatched = config_file.parent / "pawlocal-cognito-deployment-other.config"
        mismatched.write_text("preserve", encoding="utf-8")
        rejected = subprocess.run(
            ["bash", str(CLEANUP_SCRIPT)],
            cwd=ROOT,
            env={**env, "AWS_CONFIG_FILE": str(mismatched)},
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(rejected.returncode, 0)
        self.assertTrue(mismatched.exists())


class CognitoTerraformWorkflowTests(unittest.TestCase):
    @staticmethod
    def _load(path: Path) -> dict:
        return yaml.safe_load(path.read_text(encoding="utf-8"))

    def test_all_six_jobs_use_exact_purpose_and_profile_lifecycle(self) -> None:
        expected = {
            ENVIRONMENT_WORKFLOW: {"plan": "plan", "apply": "apply"},
            DESTROY_WORKFLOW: {
                "prepare-plan": "plan",
                "prepare-apply": "apply",
                "destroy-plan": "plan",
                "destroy-apply": "apply",
            },
        }
        for workflow_path, jobs in expected.items():
            workflow = self._load(workflow_path)
            for job_name, purpose in jobs.items():
                with self.subTest(workflow=workflow_path.name, job=job_name):
                    job = workflow["jobs"][job_name]
                    self.assertEqual(job["timeout-minutes"], 60)
                    self.assertEqual(job["env"]["AWS_PARTITION"], "aws")
                    self.assertNotIn("COGNITO_DEPLOYMENT_PROFILE", job["env"])
                    self.assertEqual(job["env"]["COGNITO_TERRAFORM_PURPOSE"], purpose)
                    self.assertNotIn("AWS_CONFIG_FILE", job["env"])
                    self.assertNotIn("AWS_PROFILE", job["env"])
                    steps = job["steps"]
                    configure_indexes = [
                        index
                        for index, step in enumerate(steps)
                        if step.get("run") == "bash .github/scripts/configure-cognito-terraform-profile.sh"
                    ]
                    cleanup_steps = [
                        step
                        for step in steps
                        if step.get("run") == "bash .github/scripts/cleanup-cognito-terraform-profile.sh"
                    ]
                    self.assertEqual(len(configure_indexes), 1)
                    self.assertEqual(len(cleanup_steps), 1)
                    self.assertEqual(cleanup_steps[0].get("if"), "always()")
                    credential_index = next(
                        index
                        for index, step in enumerate(steps)
                        if step.get("uses", "").startswith("aws-actions/configure-aws-credentials@")
                    )
                    self.assertGreater(configure_indexes[0], credential_index)

                    terraform_indexes = [
                        index
                        for index, step in enumerate(steps)
                        if "terraform " in step.get("run", "")
                    ]
                    self.assertTrue(terraform_indexes)
                    self.assertLess(configure_indexes[0], min(terraform_indexes))

    def test_workflows_construct_roles_without_new_runtime_inputs(self) -> None:
        source = ENVIRONMENT_WORKFLOW.read_text(encoding="utf-8") + DESTROY_WORKFLOW.read_text(encoding="utf-8")
        self.assertNotIn("PAWLOCAL_COGNITO_", source)
        self.assertNotIn("TF_VAR_cognito_pre_sign_up_role_arn", source)
        self.assertNotIn("AWS_PROFILE:", source)
        self.assertEqual(source.count("TF_VAR_project_name: pawlocal"), 2)
        self.assertEqual(source.count("COGNITO_TERRAFORM_PURPOSE: plan"), 3)
        self.assertEqual(source.count("COGNITO_TERRAFORM_PURPOSE: apply"), 3)

    def test_each_attempt_requires_a_fresh_plan_and_delegated_session(self) -> None:
        environment_source = ENVIRONMENT_WORKFLOW.read_text(encoding="utf-8")
        destroy_source = DESTROY_WORKFLOW.read_text(encoding="utf-8")
        self.assertIn(
            "PLAN_PREFIX: plans/${{ inputs.environment }}/${{ github.run_id }}/${{ github.run_attempt }}",
            environment_source,
        )
        self.assertIn("needs: plan", environment_source)
        self.assertEqual(destroy_source.count("${{ github.run_attempt }}"), 4)

        helper_source = CONFIGURE_SCRIPT.read_text(encoding="utf-8")
        self.assertIn("duration_seconds = 3600", helper_source)
        self.assertIn("aws sts get-caller-identity --profile", helper_source)

    def test_cognito_resources_use_only_the_delegated_provider_contract(self) -> None:
        module = (
            ROOT / "infra/terraform/modules/pawlocal-environment/main.tf"
        ).read_text(encoding="utf-8")
        self.assertEqual(module.count("provider          = aws.cognito_deployment"), 1)
        self.assertEqual(module.count("provider         = aws.cognito_deployment"), 1)
        self.assertEqual(module.count("provider       = aws.cognito_deployment"), 1)

        pool_start = module.index('resource "aws_cognito_user_pool" "application"')
        pool_end = module.index('resource "aws_lambda_permission"', pool_start)
        self.assertNotIn("provider", module[pool_start:pool_end])

        self.assertIn('data "archive_file" "cognito_pre_sign_up"', module)
        self.assertNotIn('resource "archive_file" "cognito_pre_sign_up"', module)
        self.assertIn(
            'source_file      = "${path.module}/lambda/cognito-pre-signup/index.mjs"',
            module,
        )
        self.assertIn('output_file_mode = "0666"', module)
        self.assertIn(
            'output_path      = "${path.root}/.terraform/${local.cognito_pre_sign_up_name}.zip"',
            module,
        )
        self.assertIn("filename         = data.archive_file.cognito_pre_sign_up.output_path", module)
        self.assertIn("source_code_hash = data.archive_file.cognito_pre_sign_up.output_base64sha256", module)

        versions = (
            ROOT / "infra/terraform/modules/pawlocal-environment/versions.tf"
        ).read_text(encoding="utf-8")
        self.assertIn('version = "= 2.8.1"', versions)
        for environment in ("development", "production"):
            lock = (
                ROOT
                / f"infra/terraform/environments/{environment}/.terraform.lock.hcl"
            ).read_text(encoding="utf-8")
            archive_lock = lock.split(
                'provider "registry.terraform.io/hashicorp/archive"', 1
            )[1].split("}", 1)[0]
            self.assertIn('version     = "2.8.1"', archive_lock)

    def test_ci_runs_the_cross_workspace_saved_plan_archive_contract(self) -> None:
        workflow = self._load(TERRAFORM_CI_WORKFLOW)
        steps = workflow["jobs"]["terraform"]["steps"]
        archive_step = next(
            step
            for step in steps
            if step.get("name") == "Test Cognito archive across saved-plan runners"
        )
        self.assertEqual(
            archive_step["if"], "matrix.root == 'modules/pawlocal-environment'"
        )
        self.assertEqual(
            archive_step["env"]["PAWLOCAL_RUN_TERRAFORM_ARCHIVE_INTEGRATION"],
            "1",
        )
        self.assertEqual(
            archive_step["run"],
            "python ../../../../tests/ci/test_cognito_archive_saved_plan.py -v",
        )

        source = TERRAFORM_CI_WORKFLOW.read_text(encoding="utf-8")
        self.assertEqual(source.count('"tests/ci/test_cognito_archive_saved_plan.py"'), 2)
        self.assertEqual(
            source.count(
                '".github/scripts/verify-cognito-archive-provider-contract.py"'
            ),
            2,
        )
        self.assertEqual(
            source.count('".github/scripts/terraform-cognito-archive.py"'), 2
        )
        self.assertEqual(
            source.count('".github/scripts/terraform-plan-transfer.py"'), 2
        )

    def test_archive_is_bound_transferred_restored_and_cleaned_for_apply_paths(
        self,
    ) -> None:
        workflow = self._load(ENVIRONMENT_WORKFLOW)
        plan_steps = {step.get("name"): step for step in workflow["jobs"]["plan"]["steps"]}
        apply_steps = {
            step.get("name"): step for step in workflow["jobs"]["apply"]["steps"]
        }
        self.assertIn("--archive", plan_steps["Bind exact plan metadata"]["run"])
        self.assertIn("--archive", plan_steps["Upload opaque plan to the private transfer bucket"]["run"])
        self.assertEqual(plan_steps["Remove plan-runner Cognito package"]["if"], "always()")
        self.assertIn("--archive", apply_steps["Download the exact saved plan"]["run"])
        self.assertIn("--archive", apply_steps["Verify exact saved plan metadata and digest"]["run"])
        self.assertIn(
            "terraform-cognito-archive.py restore",
            apply_steps["Initialize matching state and apply only the reviewed plan"]["run"],
        )
        self.assertEqual(apply_steps["Remove transferred Cognito package"]["if"], "always()")

        destroy_workflow = self._load(DESTROY_WORKFLOW)
        preparation_plan = {
            step.get("name"): step
            for step in destroy_workflow["jobs"]["prepare-plan"]["steps"]
        }
        preparation_apply = {
            step.get("name"): step
            for step in destroy_workflow["jobs"]["prepare-apply"]["steps"]
        }
        self.assertIn("--archive", preparation_plan["Bind preparation plan to state and workflow identity"]["run"])
        self.assertIn("--archive", preparation_plan["Upload opaque preparation plan to private transfer storage"]["run"])
        self.assertEqual(preparation_plan["Remove preparation-plan Cognito package"]["if"], "always()")
        self.assertIn("--archive", preparation_apply["Download exact preparation plan"]["run"])
        self.assertIn("--archive", preparation_apply["Initialize and verify preparation plan against current state"]["run"])
        self.assertIn("terraform-cognito-archive.py restore", preparation_apply["Initialize and verify preparation plan against current state"]["run"])
        self.assertEqual(preparation_apply["Remove transferred preparation Cognito package"]["if"], "always()")

    def test_final_destroy_does_not_transfer_or_restore_the_unused_archive(self) -> None:
        workflow = self._load(DESTROY_WORKFLOW)
        destroy_plan = {
            step.get("name"): step
            for step in workflow["jobs"]["destroy-plan"]["steps"]
        }
        destroy_apply = {
            step.get("name"): step
            for step in workflow["jobs"]["destroy-apply"]["steps"]
        }
        self.assertNotIn("--archive", destroy_plan["Bind destroy plan to state and workflow identity"]["run"])
        self.assertNotIn("--archive", destroy_plan["Upload opaque destroy plan to private transfer storage"]["run"])
        self.assertEqual(destroy_plan["Remove destroy-plan Cognito package"]["if"], "always()")
        self.assertNotIn("--archive", destroy_apply["Download, initialize, and verify exact destroy plan"]["run"])
        self.assertNotIn("terraform-cognito-archive.py restore", destroy_apply["Download, initialize, and verify exact destroy plan"]["run"])

    def test_environment_roots_pass_only_the_four_approved_policy_values(self) -> None:
        expected = {
            "development": ("8", "false", "false", "false"),
            "production": ("12", "true", "true", "true"),
        }
        for environment, values in expected.items():
            source = (
                ROOT / f"infra/terraform/environments/{environment}/main.tf"
            ).read_text(encoding="utf-8")
            block = source.split("cognito_password_policy = {", 1)[1].split("}", 1)[0]
            self.assertIn(f"minimum_length    = {values[0]}", block)
            self.assertIn(f"require_lowercase = {values[1]}", block)
            self.assertIn(f"require_uppercase = {values[2]}", block)
            self.assertIn(f"require_numbers   = {values[3]}", block)
            self.assertNotIn("require_symbols", block)

    def test_plan_diagnostics_blank_the_delegated_profile_context(self) -> None:
        workflow = self._load(ENVIRONMENT_WORKFLOW)
        diagnostic_steps = [
            step
            for step in workflow["jobs"]["plan"]["steps"]
            if step.get("name") in {
                "Print sanitized saved-plan diagnostics",
                "Print raw saved plan for diagnosis",
            }
        ]
        self.assertEqual(len(diagnostic_steps), 2)
        for step in diagnostic_steps:
            for name in (
                "AWS_CONFIG_FILE",
                "COGNITO_DELEGATED_ROLE_ARN",
                "COGNITO_DEPLOYMENT_PROFILE",
                "COGNITO_TERRAFORM_PURPOSE",
            ):
                self.assertEqual(step["env"].get(name), "")

    def test_provider_alias_uses_project_profile_and_default_provider_has_no_profile(self) -> None:
        for environment in ("development", "production"):
            versions = (
                ROOT / f"infra/terraform/environments/{environment}/versions.tf"
            ).read_text(encoding="utf-8")
            default_provider = versions.split('provider "aws" {', 2)[1]
            aliased_provider = versions.split('provider "aws" {', 2)[2]
            self.assertNotIn("profile", default_provider)
            self.assertIn('alias   = "cognito_deployment"', aliased_provider)
            self.assertIn(
                'profile = "${var.project_name}-cognito-deployment"',
                aliased_provider,
            )
            self.assertIn("project     = var.project_name", aliased_provider)


if __name__ == "__main__":
    unittest.main()
