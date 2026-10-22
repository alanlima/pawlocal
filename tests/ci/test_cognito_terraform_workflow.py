from __future__ import annotations

import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[2]
CONFIGURE_SCRIPT = ROOT / ".github/scripts/configure-cognito-terraform-profile.sh"
CLEANUP_SCRIPT = ROOT / ".github/scripts/cleanup-cognito-terraform-profile.sh"
ENVIRONMENT_WORKFLOW = ROOT / ".github/workflows/terraform-environment.yml"
DESTROY_WORKFLOW = ROOT / ".github/workflows/terraform-environment-destroy.yml"
TERRAFORM_CI_WORKFLOW = ROOT / ".github/workflows/terraform-ci.yml"
VERIFY_SOURCE_SCRIPT = ROOT / ".github/scripts/verify-terraform-source-checkout.py"


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
        self.assertEqual(module.count("aws = aws.cognito_deployment"), 1)
        self.assertEqual(module.count("provider       = aws.cognito_deployment"), 1)

        pool_start = module.index('resource "aws_cognito_user_pool" "application"')
        pool_end = module.index('resource "aws_lambda_permission"', pool_start)
        self.assertNotIn("provider", module[pool_start:pool_end])

        self.assertIn('source  = "terraform-aws-modules/lambda/aws"', module)
        self.assertIn('version = "= 8.12.0"', module)
        self.assertIn("aws = aws.cognito_deployment", module)
        self.assertIn("create_role = false", module)
        self.assertIn("lambda_role = local.cognito_pre_sign_up_role_arn", module)
        self.assertIn(
            'source_path                  = "${path.module}/lambda/cognito-pre-signup/index.mjs"',
            module,
        )
        self.assertIn('artifacts_dir                = "${path.root}/.terraform/lambda-builds"', module)
        self.assertIn("recreate_missing_package     = true", module)
        self.assertIn("trigger_on_package_timestamp = false", module)
        self.assertIn("hash_extra                   = var.cognito_package_build_id", module)
        self.assertIn("cloudwatch_logs_retention_in_days = 30", module)
        self.assertIn("allowed_triggers                  = {}", module)

        for environment in ("development", "production"):
            lock = (
                ROOT
                / f"infra/terraform/environments/{environment}/.terraform.lock.hcl"
            ).read_text(encoding="utf-8")
            providers = {
                line.split('"')[1]
                for line in lock.splitlines()
                if line.startswith('provider "registry.terraform.io/hashicorp/')
            }
            self.assertEqual(
                providers,
                {
                    "registry.terraform.io/hashicorp/aws",
                    "registry.terraform.io/hashicorp/external",
                    "registry.terraform.io/hashicorp/local",
                    "registry.terraform.io/hashicorp/null",
                    "registry.terraform.io/hashicorp/random",
                    "registry.terraform.io/hashicorp/time",
                },
            )
            for provider in providers:
                provider_block = lock.split(f'provider "{provider}" {{', 1)[1].split(
                    "\n}", 1
                )[0]
                self.assertEqual(
                    provider_block.count('"h1:'),
                    2,
                    f"{environment} must lock Windows and Linux packages for {provider}",
                )

    def test_ci_runs_the_cross_workspace_lambda_module_contract(self) -> None:
        workflow = self._load(TERRAFORM_CI_WORKFLOW)
        steps = workflow["jobs"]["terraform"]["steps"]
        integration_step = next(
            step
            for step in steps
            if step.get("name") == "Test pinned Lambda module across saved-plan runners"
        )
        self.assertEqual(
            integration_step["if"], "matrix.root == 'modules/pawlocal-environment'"
        )
        self.assertEqual(
            integration_step["env"]["PAWLOCAL_RUN_TERRAFORM_LAMBDA_MODULE_INTEGRATION"],
            "1",
        )
        self.assertEqual(
            integration_step["run"],
            "python ../../../../tests/ci/test_cognito_lambda_module_saved_plan.py -v",
        )

        source = TERRAFORM_CI_WORKFLOW.read_text(encoding="utf-8")
        self.assertEqual(
            source.count('"tests/ci/test_cognito_lambda_module_saved_plan.py"'), 2
        )
        self.assertEqual(
            source.count('".github/scripts/verify-terraform-source-checkout.py"'), 2
        )

    def test_normal_plans_use_fresh_build_ids_and_teardown_reuses_state(self) -> None:
        environment = ENVIRONMENT_WORKFLOW.read_text(encoding="utf-8")
        destroy = self._load(DESTROY_WORKFLOW)
        self.assertIn(
            "TF_VAR_cognito_package_build_id: ${{ github.run_id }}-${{ github.run_attempt }}-${{ inputs.environment }}-${{ inputs.phase }}",
            environment,
        )

        destroy_source = DESTROY_WORKFLOW.read_text(encoding="utf-8")
        self.assertNotIn("production-teardown", destroy_source)
        preparation_steps = {
            step.get("name"): step for step in destroy["jobs"]["prepare-plan"]["steps"]
        }
        reuse = preparation_steps["Reuse the applied configuration build identifier"]["run"]
        self.assertIn("terraform -chdir=\"$TF_ROOT\" output -raw cognito_package_build_id", reuse)
        self.assertIn("TF_VAR_cognito_package_build_id=$build_id", reuse)
        for job_name in ("prepare-apply", "destroy-plan", "destroy-apply"):
            job = destroy["jobs"][job_name]
            self.assertNotIn("TF_VAR_cognito_package_build_id", job.get("env", {}))
            self.assertNotIn("cognito_package_build_id", str(job))

    def test_all_environment_inits_enforce_readonly_lockfiles(self) -> None:
        environment = ENVIRONMENT_WORKFLOW.read_text(encoding="utf-8")
        destroy = DESTROY_WORKFLOW.read_text(encoding="utf-8")
        self.assertEqual(environment.count("terraform -chdir=\"$TF_ROOT\" init"), 2)
        self.assertEqual(environment.count("-lockfile=readonly"), 2)
        self.assertEqual(destroy.count("terraform -chdir=\"$TF_ROOT\" init"), 4)
        self.assertEqual(destroy.count("-lockfile=readonly"), 4)

        workflow = self._load(TERRAFORM_CI_WORKFLOW)
        steps = workflow["jobs"]["terraform"]["steps"]
        locked = next(
            step for step in steps if step.get("name") == "Initialize locked environment providers without configuring the backend"
        )
        self.assertEqual(locked["if"], "startsWith(matrix.root, 'environments/')")
        self.assertIn("-lockfile=readonly", locked["run"])

    def test_exact_commit_and_tracked_tree_are_checked_immediately_before_plan_and_apply(self) -> None:
        for workflow_path, expected in (
            (ENVIRONMENT_WORKFLOW, {"plan": "plan", "apply": "apply"}),
            (
                DESTROY_WORKFLOW,
                {
                    "prepare-plan": "plan",
                    "prepare-apply": "apply",
                    "destroy-plan": "plan",
                    "destroy-apply": "apply",
                },
            ),
        ):
            workflow = self._load(workflow_path)
            for job_name, command in expected.items():
                runs = "\n".join(
                    step.get("run", "") for step in workflow["jobs"][job_name]["steps"]
                )
                guard = "python .github/scripts/verify-terraform-source-checkout.py"
                command_index = runs.rfind(f"terraform -chdir=\"$TF_ROOT\" {command}")
                guard_index = runs.rfind(guard, 0, command_index)
                self.assertGreater(command_index, guard_index, job_name)
                self.assertNotIn("terraform -chdir=", runs[guard_index + len(guard):command_index])

    def test_source_checkout_guard_rejects_lambda_source_tampering(self) -> None:
        with tempfile.TemporaryDirectory(prefix="pawlocal-source-guard-") as temporary:
            repository = Path(temporary)
            subprocess.run(["git", "init", "-q"], cwd=repository, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=repository, check=True)
            subprocess.run(["git", "config", "user.name", "PawLocal test"], cwd=repository, check=True)
            source = repository / "index.mjs"
            source.write_text("export const handler = async () => {};\n", encoding="utf-8")
            subprocess.run(["git", "add", "index.mjs"], cwd=repository, check=True)
            subprocess.run(["git", "commit", "-qm", "fixture"], cwd=repository, check=True)
            head = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=repository, check=True, capture_output=True, text=True
            ).stdout.strip()
            env = {**os.environ, "GITHUB_SHA": head}
            clean = subprocess.run(
                [sys.executable, str(VERIFY_SOURCE_SCRIPT)], cwd=repository, env=env, check=False
            )
            self.assertEqual(clean.returncode, 0)
            source.write_text("export const handler = async () => ({ tampered: true });\n", encoding="utf-8")
            tampered = subprocess.run(
                [sys.executable, str(VERIFY_SOURCE_SCRIPT)], cwd=repository, env=env, check=False
            )
            self.assertNotEqual(tampered.returncode, 0)

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
