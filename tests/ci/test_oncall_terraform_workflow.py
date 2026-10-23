import importlib.util
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / ".github/scripts/configure-oncall-terraform-profile.sh"
spec = importlib.util.spec_from_file_location("oncall_configuration", ROOT / ".github/scripts/validate-oncall-configuration.py")
configuration = importlib.util.module_from_spec(spec)
spec.loader.exec_module(configuration)


class OncallConfigurationTests(unittest.TestCase):
    def fixture(self):
        return {"app_id": "1", "installation_id": "2", "repository_id": "3", "repository": "alanlima/pawlocal", "allowed_services": ["pawlocal-api"], "allowed_alerts": ["search-failure"]}

    def test_default_null_and_narrow_public_object(self):
        configuration.validate("null", "111111111111", "ap-southeast-2")
        configuration.validate(json.dumps(self.fixture()), "111111111111", "ap-southeast-2")

    def test_unknown_secret_fields_and_unbounded_inputs_fail_before_terraform(self):
        for fields in ({"private_key": "PRIVATE_PEM"}, {"repository_id": "9007199254740993"},
                       {"repository": "https://github.com/example/repo"}, {"repository": "example/.."},
                       {"allowed_alerts": ["search-failure"] * 2}, {"kms_key_arn": "arn:aws:kms:us-east-1:222222222222:key/11111111-1111-1111-1111-111111111111"}):
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                configuration.validate(json.dumps(self.fixture() | fields), "111111111111", "ap-southeast-2")
        with self.assertRaises(ValueError):
            configuration.validate('{"app_id":"1","app_id":"2"}', "111111111111", "ap-southeast-2")


class OncallWorkflowTests(unittest.TestCase):
    def test_profiles_follow_existing_setup_and_cleanup_in_every_lifecycle_job(self):
        for filename, names in (
            ("terraform-environment.yml", ("plan", "apply")),
            ("terraform-environment-destroy.yml", ("prepare-plan", "prepare-apply", "destroy-plan", "destroy-apply")),
        ):
            workflow = yaml.safe_load((ROOT / ".github/workflows" / filename).read_text())
            for name in names:
                with self.subTest(workflow=filename, job=name):
                    job = workflow["jobs"][name]
                    runs = [step.get("run", "") for step in job["steps"]]
                    previous = runs.index("bash .github/scripts/configure-cognito-terraform-profile.sh")
                    current = runs.index("bash .github/scripts/configure-oncall-terraform-profile.sh")
                    cleanup = runs.index("bash .github/scripts/cleanup-cognito-terraform-profile.sh")
                    self.assertLess(previous, current)
                    self.assertLess(current, cleanup)
                    self.assertEqual(job["steps"][cleanup]["if"], "always()")
                    if job["env"]["COGNITO_TERRAFORM_PURPOSE"] == "plan":
                        self.assertEqual(job["env"]["TF_VAR_oncall_receiver"], "${{ vars.PAWLOCAL_ONCALL_RECEIVER_CONFIG || 'null' }}")
                    else:
                        self.assertNotIn("TF_VAR_oncall_receiver", job["env"])

    def test_handler_tests_are_wired_to_applicable_ci(self):
        workflow = yaml.safe_load((ROOT / ".github/workflows/terraform-ci.yml").read_text())
        steps = workflow["jobs"]["terraform"]["steps"]
        receiver = [step for step in steps if "incident_receiver.test.mjs" in step.get("run", "")]
        self.assertEqual(len(receiver), 1)
        self.assertEqual(receiver[0]["if"], "matrix.root == 'modules/pawlocal-environment'")
        self.assertTrue(any(str(step.get("with", {}).get("node-version")) == "24" for step in steps))
        triggers = workflow.get("on", workflow.get(True))
        self.assertIn("tests/ci/incident_receiver.test.mjs", triggers["pull_request"]["paths"])

    def test_enabled_package_sidecars_are_planned_but_not_rebuilt_for_teardown(self):
        normal = (ROOT / ".github/workflows/terraform-environment.yml").read_text()
        destroy = (ROOT / ".github/workflows/terraform-environment-destroy.yml").read_text()
        self.assertIn('if [[ "$TF_VAR_oncall_receiver" != \'null\' ]]', normal)
        for suffix in ("local_file.archive_plan[0]", "null_resource.archive[0]"):
            address = f"module.pawlocal.module.oncall_receiver[0].{suffix}"
            self.assertIn(address, normal)
            self.assertNotIn(address, destroy)


@unittest.skipUnless(os.name != "nt" and shutil.which("bash"), "Native Bash required; functional profile tests run in Ubuntu CI")
class OncallProfileTests(unittest.TestCase):
    def run_fixture(self, overrides=None):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "pawlocal-cognito-deployment-fixture.config"
            config.write_text("[profile existing-cognito]\nregion = ap-southeast-2\n")
            environment = {
                **os.environ, "AWS_PARTITION": "aws", "AWS_REGION": "ap-southeast-2",
                "PAWLOCAL_AWS_ACCOUNT_ID": "111111111111", "PAWLOCAL_ENVIRONMENT": "development",
                "COGNITO_TERRAFORM_PURPOSE": "plan", "TF_VAR_project_name": "pawlocal",
                "TF_VAR_oncall_receiver": "null", "RUNNER_TEMP": directory, "GITHUB_JOB": "fixture", "AWS_CONFIG_FILE": str(config), "AWS_PROFILE": "",
                **(overrides or {}),
            }
            result = subprocess.run([shutil.which("bash"), str(SCRIPT)], env=environment, capture_output=True, text=True, check=False)
            return result, config.read_text()

    def test_default_profile_preparation_needs_no_aws_cli_or_credentials(self):
        result, content = self.run_fixture()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("[profile existing-cognito]", content)
        self.assertIn("[profile pawlocal-oncall-deployment]", content)
        self.assertIn("role/pawlocal-development-oncall-terraform-plan", content)
        self.assertIn("credential_source = Environment", content)
        self.assertIn("duration_seconds = 3600", content)

    def test_production_apply_uses_only_matching_identity(self):
        result, content = self.run_fixture({"PAWLOCAL_ENVIRONMENT": "production", "COGNITO_TERRAFORM_PURPOSE": "apply"})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("role/pawlocal-production-oncall-terraform-apply", content)
        self.assertNotIn("role/pawlocal-development", content)

    def test_invalid_inputs_do_not_change_config(self):
        for key, value in (("AWS_PROFILE", "admin"), ("AWS_CONFIG_FILE", "/tmp/unowned"),
                           ("PAWLOCAL_ENVIRONMENT", "staging"), ("COGNITO_TERRAFORM_PURPOSE", "destroy"),
                           ("PAWLOCAL_AWS_ACCOUNT_ID", "invalid"), ("TF_VAR_project_name", "../escape")):
            with self.subTest(key=key):
                result, content = self.run_fixture({key: value})
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn("oncall-deployment", content)


if __name__ == "__main__":
    unittest.main()
