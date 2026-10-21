import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / "infra" / "terraform" / "modules" / "dsql-post-apply-setup"
TERRAFORM = shutil.which("terraform")
SETUP_ADDRESS = "module.setup.terraform_data.setup"


def _shell_command(arguments: list[str]) -> str:
    if os.name == "nt":
        return subprocess.list2cmdline(arguments)
    return shlex.join(arguments)


@unittest.skipUnless(TERRAFORM, "Terraform CLI is required for lifecycle tests")
class DSQLSetupTerraformLifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory(
            prefix=".dsql-lifecycle-", dir=MODULE.parent
        )
        self.directory = Path(self.temporary_directory.name)
        self.setup_log = self.directory / "setup.log"
        self.deployment_log = self.directory / "deployment.log"
        self.variables_file = self.directory / "test.auto.tfvars.json"
        self.probe = self.directory / "probe.py"
        self.probe.write_text(
            """import argparse
import time
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--log", required=True)
parser.add_argument("--event", required=True)
parser.add_argument("--mode", choices=("success", "fail", "sleep"), required=True)
arguments = parser.parse_args()

with Path(arguments.log).open("a", encoding="utf-8") as stream:
    stream.write(arguments.event + "\\n")
    stream.flush()

if arguments.mode == "sleep":
    time.sleep(2)
elif arguments.mode == "fail":
    raise SystemExit(23)
""",
            encoding="utf-8",
        )
        module_source = "../dsql-post-apply-setup"
        self.directory.joinpath("main.tf").write_text(
            f"""terraform {{
  required_version = "= 1.14.3"
}}

variable "cluster_identity" {{ type = string }}
variable "runtime_identity" {{ type = string }}
variable "setup_revision" {{ type = string }}
variable "setup_command" {{ type = string }}
variable "deployment_command" {{ type = string }}

module "setup" {{
  source            = {json.dumps(module_source)}
  cluster_identity  = var.cluster_identity
  runtime_identity  = var.runtime_identity
  setup_revision    = var.setup_revision
  command           = var.setup_command
  working_directory = {json.dumps(self.directory.as_posix())}
}}

resource "terraform_data" "deployment" {{
  input = module.setup.completion_id

  provisioner "local-exec" {{
    command     = var.deployment_command
    quiet       = true
    working_dir = {json.dumps(self.directory.as_posix())}
  }}

  depends_on = [module.setup]
}}
""",
            encoding="utf-8",
        )
        initialized = self._terraform("init", "-input=false", "-no-color")
        self.assertEqual(initialized.returncode, 0, initialized.stderr)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def _command(self, event: str, mode: str, log: Path) -> str:
        return _shell_command(
            [
                sys.executable,
                str(self.probe),
                "--log",
                str(log),
                "--event",
                event,
                "--mode",
                mode,
            ]
        )

    def _write_variables(self, *, setup_mode: str, revision: str) -> None:
        self.variables_file.write_text(
            json.dumps(
                {
                    "cluster_identity": "test-cluster",
                    "runtime_identity": "test-runtime-role",
                    "setup_revision": revision,
                    "setup_command": self._command(
                        f"setup-{setup_mode}-{revision}", setup_mode, self.setup_log
                    ),
                    "deployment_command": self._command(
                        "deployment", "success", self.deployment_log
                    ),
                }
            ),
            encoding="utf-8",
        )

    def _terraform(
        self, *arguments: str, timeout: int = 30
    ) -> subprocess.CompletedProcess:
        environment = {
            **os.environ,
            "CHECKPOINT_DISABLE": "1",
            "TF_IN_AUTOMATION": "1",
        }
        return subprocess.run(
            [TERRAFORM, *arguments],
            cwd=self.directory,
            env=environment,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )

    def _apply(self, *, timeout: int = 30) -> subprocess.CompletedProcess:
        return self._terraform(
            "apply",
            "-auto-approve",
            "-input=false",
            "-no-color",
            "-lock-timeout=10s",
            timeout=timeout,
        )

    def _events(self, path: Path) -> list[str]:
        if not path.exists():
            return []
        return path.read_text(encoding="utf-8").splitlines()

    def _planned_actions(self, address: str) -> list[str]:
        plan = self.directory / "retry.tfplan"
        result = self._terraform(
            "plan",
            "-input=false",
            "-no-color",
            "-lock-timeout=10s",
            "-out",
            str(plan),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        shown = self._terraform("show", "-json", str(plan))
        self.assertEqual(shown.returncode, 0, shown.stderr)
        changes = json.loads(shown.stdout)["resource_changes"]
        return next(
            change["change"]["actions"]
            for change in changes
            if change["address"] == address
        )

    def test_failure_is_retryable_and_revision_controls_rerun(self) -> None:
        self._write_variables(setup_mode="fail", revision="revision-1")
        failed = self._apply()

        self.assertNotEqual(failed.returncode, 0)
        self.assertEqual(self._events(self.setup_log), ["setup-fail-revision-1"])
        self.assertEqual(self._events(self.deployment_log), [])

        self._write_variables(setup_mode="success", revision="revision-1")
        self.assertEqual(
            self._planned_actions(SETUP_ADDRESS),
            ["delete", "create"],
            "a failed creation provisioner must leave the setup resource retryable",
        )
        retried = self._apply()
        self.assertEqual(retried.returncode, 0, retried.stderr)
        self.assertEqual(
            self._events(self.setup_log),
            ["setup-fail-revision-1", "setup-success-revision-1"],
        )
        self.assertEqual(self._events(self.deployment_log), ["deployment"])

        unchanged = self._apply()
        self.assertEqual(unchanged.returncode, 0, unchanged.stderr)
        self.assertEqual(len(self._events(self.setup_log)), 2)
        self.assertEqual(self._events(self.deployment_log), ["deployment"])

        self._write_variables(setup_mode="success", revision="revision-2")
        self.assertEqual(self._planned_actions(SETUP_ADDRESS), ["delete", "create"])
        rerun = self._apply()
        self.assertEqual(rerun.returncode, 0, rerun.stderr)
        self.assertEqual(self._events(self.setup_log)[-1], "setup-success-revision-2")

        state = self._terraform("state", "list")
        self.assertEqual(state.returncode, 0, state.stderr)
        self.assertIn(SETUP_ADDRESS, state.stdout.splitlines())
        self.assertIn("terraform_data.deployment", state.stdout.splitlines())

    def test_same_state_serializes_concurrent_applies(self) -> None:
        self._write_variables(setup_mode="sleep", revision="revision-1")
        environment = {
            **os.environ,
            "CHECKPOINT_DISABLE": "1",
            "TF_IN_AUTOMATION": "1",
        }
        command = [
            TERRAFORM,
            "apply",
            "-auto-approve",
            "-input=false",
            "-no-color",
            "-lock-timeout=10s",
        ]
        first = subprocess.Popen(
            command,
            cwd=self.directory,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        deadline = time.monotonic() + 10
        while not self.setup_log.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertTrue(self.setup_log.exists(), "first setup did not start")

        second = subprocess.run(
            command,
            cwd=self.directory,
            env=environment,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        first_stdout, first_stderr = first.communicate(timeout=20)

        self.assertEqual(first.returncode, 0, first_stderr or first_stdout)
        if second.returncode != 0:
            self.assertIn(
                "Error acquiring the state lock",
                second.stderr or second.stdout,
                "a concurrent apply may only fail closed on the state lock",
            )
            after_lock = self._apply()
            self.assertEqual(after_lock.returncode, 0, after_lock.stderr)
        self.assertEqual(
            self._events(self.setup_log),
            ["setup-sleep-revision-1"],
            "a competing apply must never execute the setup concurrently",
        )
        self.assertEqual(self._events(self.deployment_log), ["deployment"])


if __name__ == "__main__":
    unittest.main()
