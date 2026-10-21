from __future__ import annotations

import importlib.util
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / ".github/scripts/terraform-command-output.py"
WORKFLOW = ROOT / ".github/workflows/terraform-environment.yml"


def load_helper():
    spec = importlib.util.spec_from_file_location("terraform_command_output", HELPER)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load Terraform command helper")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TerraformCommandOutputTests(unittest.TestCase):
    def test_disabled_or_absent_control_captures_output_and_preserves_exit_status(self) -> None:
        helper = load_helper()
        for value in (None, "false", "TRUE"):
            with self.subTest(value=value), tempfile.TemporaryDirectory() as directory:
                log = Path(directory) / "terraform.log"
                environment = os.environ.copy()
                if value is None:
                    environment.pop("PAWLOCAL_TERRAFORM_DIAGNOSTIC_LOGS", None)
                else:
                    environment["PAWLOCAL_TERRAFORM_DIAGNOSTIC_LOGS"] = value
                completed = mock.Mock(returncode=17)
                with mock.patch.dict(os.environ, environment, clear=True), mock.patch.object(
                    helper.subprocess, "run", return_value=completed
                ) as run:
                    self.assertEqual(helper.run_command(log, ["terraform", "init"]), 17)
                arguments, keywords = run.call_args
                self.assertEqual(arguments[0], ["terraform", "init"])
                self.assertIs(keywords["stderr"], subprocess.STDOUT)
                self.assertIn("stdout", keywords)
                self.assertEqual(keywords["check"], False)

    def test_enabled_control_streams_through_color_preserving_pseudo_terminal(self) -> None:
        helper = load_helper()
        command = ["terraform", "-chdir=infra/terraform/environments/development", "apply", "saved-plan/tfplan"]
        completed = mock.Mock(returncode=23)
        with tempfile.TemporaryDirectory() as directory, mock.patch.dict(
            os.environ, {"PAWLOCAL_TERRAFORM_DIAGNOSTIC_LOGS": "true"}, clear=True
        ), mock.patch.object(helper.subprocess, "run", return_value=completed) as run:
            log = Path(directory) / "terraform.log"
            self.assertEqual(helper.run_command(log, command), 23)
        arguments, keywords = run.call_args
        invocation = arguments[0]
        self.assertEqual(invocation[:3], ["script", "--quiet", "--return"])
        self.assertTrue(invocation[3].startswith("--command=terraform "))
        self.assertIn("apply", invocation[3])
        self.assertIn("saved-plan/tfplan", invocation[3])
        self.assertNotIn("-no-color", invocation[3])
        self.assertEqual(invocation[4], str(log))
        self.assertNotIn("stdout", keywords)
        self.assertNotIn("stderr", keywords)
        self.assertEqual(keywords["check"], False)

    def test_workflow_routes_both_inits_and_exact_plan_apply_through_helper(self) -> None:
        workflow = WORKFLOW.read_text(encoding="utf-8")
        helper_call = "python .github/scripts/terraform-command-output.py --log"
        self.assertEqual(workflow.count(helper_call), 3)

        plan_init = workflow[workflow.index("      - name: Initialize the matching clean state") : workflow.index("      - name: Create saved plan")]
        apply = workflow[workflow.index("      - name: Initialize matching state and apply only the reviewed plan") :]
        self.assertIn(helper_call, plan_init)
        self.assertIn('terraform -chdir="$TF_ROOT" init', plan_init)
        self.assertNotIn('> "$RUNNER_TEMP/terraform-init.log"', plan_init)
        self.assertIn(helper_call, apply)
        self.assertEqual(apply.count('terraform -chdir="$TF_ROOT" init'), 1)
        self.assertNotIn('> "$RUNNER_TEMP/terraform-init.log"', apply)
        self.assertNotIn('> "$RUNNER_TEMP/terraform-apply.log"', apply)
        self.assertIn('apply_command=(terraform -chdir="$TF_ROOT" apply -input=false -lock-timeout=5m)', apply)
        self.assertIn('apply_command+=("$RUNNER_TEMP/saved-plan/tfplan")', apply)
        self.assertIn('if [[ "${PAWLOCAL_TERRAFORM_DIAGNOSTIC_LOGS:-}" != \'true\' ]]', apply)
        self.assertIn("apply_command+=(-no-color)", apply)
        self.assertIn('"${apply_command[@]}"', apply)
        self.assertIn('exit "$status"', plan_init)
        self.assertGreaterEqual(apply.count('exit "$status"'), 2)


if __name__ == "__main__":
    unittest.main()
