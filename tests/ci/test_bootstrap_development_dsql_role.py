import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "ops" / "bootstrap-development-dsql-role.ps1"
ACCOUNT = "111111111111"
LIGHTSAIL_ACCOUNT = "222222222222"
REGION = "ap-southeast-2"
CLUSTER_ID = "abcdefghijklmnopqrstuvwx12"
RUNTIME_ROLE = f"arn:aws:iam::{ACCOUNT}:role/pawlocal-development-dsql-runtime"
CLUSTER_ARN = f"arn:aws:dsql:{REGION}:{ACCOUNT}:cluster/{CLUSTER_ID}"
ENDPOINT = f"{CLUSTER_ID}.dsql.{REGION}.on.aws"
LIGHTSAIL_PRINCIPAL = (
    f"arn:aws:iam::{LIGHTSAIL_ACCOUNT}:role/lightsail-runtime-principal"
)


class DevelopmentDsqlBootstrapScriptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.pwsh = shutil.which("pwsh")

    def setUp(self) -> None:
        if self.pwsh is None:
            self.skipTest("PowerShell is required to exercise the operator helper")
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp = Path(self.temp_dir.name)
        self.bootstrap_root = self.temp / "iam-bootstrap"
        self.development_root = self.temp / "development"
        self.bootstrap_root.mkdir()
        self.development_root.mkdir()
        self.invocation_log = self.temp / "python-invocations.jsonl"
        self.fake_terraform = self._write_command(
            "fake-terraform",
            """
import os
import sys

args = sys.argv[1:]
if len(args) != 3 or args[:2] != ["output", "-json"]:
    print("unexpected terraform arguments", file=sys.stderr)
    raise SystemExit(2)
name = args[2]
if os.environ.get("TEST_TERRAFORM_FAIL_OUTPUT") == name:
    print(os.environ.get("TEST_PRIVATE_DIAGNOSTIC", "private"), file=sys.stderr)
    raise SystemExit(1)
cwd = os.path.normcase(os.path.abspath(os.getcwd()))
if cwd == os.path.normcase(os.environ["TEST_BOOTSTRAP_ROOT"]):
    if name == "identity_app_role_arns":
        sys.stdout.write(os.environ["TEST_BOOTSTRAP_ROLES_JSON"])
        raise SystemExit(0)
    if name == "aws_account_id":
        sys.stdout.write(os.environ["TEST_BOOTSTRAP_ACCOUNT_JSON"])
        raise SystemExit(0)
if cwd == os.path.normcase(os.environ["TEST_DEVELOPMENT_ROOT"]) and name == "environment_targets":
    sys.stdout.write(os.environ["TEST_DEVELOPMENT_TARGETS_JSON"])
    raise SystemExit(0)
print("unexpected terraform root or output", file=sys.stderr)
raise SystemExit(2)
""",
        )
        self.fake_aws = self._write_command(
            "fake-aws",
            """
import os
import sys

if os.environ.get("TEST_AWS_FAIL") == "true":
    print(os.environ.get("TEST_PRIVATE_DIAGNOSTIC", "private"), file=sys.stderr)
    raise SystemExit(1)
args = sys.argv[1:]
if len(args) != 6 or args[:2] != ["sts", "get-caller-identity"]:
    print("unexpected aws arguments", file=sys.stderr)
    raise SystemExit(2)
sys.stdout.write(os.environ["TEST_OPERATOR_ACCOUNT"])
""",
        )
        self.fake_python = self._write_command(
            "fake-python",
            """
import json
import os
from pathlib import Path
import sys

with Path(os.environ["TEST_INVOCATION_LOG"]).open("a", encoding="utf-8") as handle:
    handle.write(json.dumps({"arguments": sys.argv[1:]}) + "\\n")
if os.environ.get("TEST_PYTHON_STDOUT"):
    print(os.environ["TEST_PYTHON_STDOUT"])
if os.environ.get("TEST_PYTHON_STDERR"):
    print(os.environ["TEST_PYTHON_STDERR"], file=sys.stderr)
raise SystemExit(int(os.environ.get("TEST_PYTHON_EXIT", "0")))
""",
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _write_command(self, name: str, source: str) -> Path:
        python_path = self.temp / f"{name}.py"
        python_path.write_text(source.strip() + "\n", encoding="utf-8")
        if os.name == "nt":
            command_path = self.temp / f"{name}.cmd"
            command_path.write_text(
                f'@echo off\r\n"{sys.executable}" "{python_path}" %*\r\n',
                encoding="utf-8",
            )
        else:
            command_path = self.temp / name
            command_path.write_text(
                f"#!{sys.executable}\n" + python_path.read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            command_path.chmod(0o755)
        return command_path

    @staticmethod
    def _bootstrap_roles(runtime_role: object = RUNTIME_ROLE) -> dict[str, object]:
        return {
            "development_frontend": (
                f"arn:aws:iam::{ACCOUNT}:role/pawlocal-development-github-deploy"
            ),
            "development_runtime": runtime_role,
            "production_frontend": None,
            "production_runtime": None,
        }

    @staticmethod
    def _development_targets() -> dict[str, object]:
        return {
            "environment": "development",
            "aws_account_id": ACCOUNT,
            "aws_region": REGION,
            "dsql_cluster_arn": CLUSTER_ARN,
            "dsql_endpoint": ENDPOINT,
            "dsql_database_role": "pawlocal_development_app",
            "runtime_role_arn": RUNTIME_ROLE,
            "lightsail_principal_arn": LIGHTSAIL_PRINCIPAL,
        }

    def _run(
        self,
        *,
        bootstrap_roles: dict[str, object] | None = None,
        bootstrap_account: object = ACCOUNT,
        development_targets: dict[str, object] | None = None,
        operator_account: str = ACCOUNT,
        extra_env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env.update(
            {
                "TEST_BOOTSTRAP_ROOT": str(self.bootstrap_root.resolve()),
                "TEST_DEVELOPMENT_ROOT": str(self.development_root.resolve()),
                "TEST_BOOTSTRAP_ROLES_JSON": json.dumps(
                    bootstrap_roles
                    if bootstrap_roles is not None
                    else self._bootstrap_roles()
                ),
                "TEST_BOOTSTRAP_ACCOUNT_JSON": json.dumps(bootstrap_account),
                "TEST_DEVELOPMENT_TARGETS_JSON": json.dumps(
                    development_targets
                    if development_targets is not None
                    else self._development_targets()
                ),
                "TEST_OPERATOR_ACCOUNT": operator_account,
                "TEST_INVOCATION_LOG": str(self.invocation_log),
            }
        )
        env.update(extra_env or {})
        return subprocess.run(
            [
                self.pwsh,
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(SCRIPT),
                "-BootstrapTerraformRoot",
                str(self.bootstrap_root),
                "-DevelopmentTerraformRoot",
                str(self.development_root),
                "-PythonPath",
                str(self.fake_python),
                "-TerraformCommand",
                str(self.fake_terraform),
                "-AwsCommand",
                str(self.fake_aws),
            ],
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )

    def _invocations(self) -> list[list[str]]:
        if not self.invocation_log.exists():
            return []
        return [
            json.loads(line)["arguments"]
            for line in self.invocation_log.read_text(encoding="utf-8").splitlines()
        ]

    def test_split_state_outputs_invoke_only_the_audited_bootstrap(self) -> None:
        result = self._run()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.strip(),
            "Development DSQL application-role bootstrap completed.",
        )
        self.assertEqual(result.stderr, "")
        self.assertEqual(
            self._invocations(),
            [
                [
                    "-m",
                    "pawlocal.dsql_role_bootstrap",
                    "--endpoint",
                    ENDPOINT,
                    "--region",
                    REGION,
                    "--database-role",
                    "pawlocal_development_app",
                    "--iam-principal-arn",
                    RUNTIME_ROLE,
                    "--legacy-iam-user-arn",
                    f"arn:aws:iam::{ACCOUNT}:user/pawlocal/pawlocal-development-dsql-app",
                    "--legacy-iam-principal-arn",
                    LIGHTSAIL_PRINCIPAL,
                ]
            ],
        )

    def test_repeated_runs_keep_the_same_idempotent_invocation_contract(self) -> None:
        first = self._run()
        second = self._run(extra_env={"TEST_PYTHON_STDOUT": "no changes required"})

        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(
            second.stdout.strip(),
            "Development DSQL application-role bootstrap completed.",
        )
        invocations = self._invocations()
        self.assertEqual(len(invocations), 2)
        self.assertEqual(invocations[0], invocations[1])

    def test_runtime_role_handoff_mismatch_fails_before_bootstrap(self) -> None:
        targets = self._development_targets()
        targets["runtime_role_arn"] = (
            f"arn:aws:iam::{ACCOUNT}:role/pawlocal-development-dsql-runtime-other"
        )

        result = self._run(development_targets=targets)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("runtime-role handoff does not match", result.stderr)
        self.assertEqual(self._invocations(), [])

    def test_missing_or_null_required_output_fails_closed(self) -> None:
        cases = []
        targets = self._development_targets()
        targets.pop("dsql_endpoint")
        cases.append((self._bootstrap_roles(), targets))
        cases.append((self._bootstrap_roles(runtime_role=None), self._development_targets()))

        for roles, development in cases:
            with self.subTest(roles=roles, development=development):
                if self.invocation_log.exists():
                    self.invocation_log.unlink()
                result = self._run(
                    bootstrap_roles=roles,
                    development_targets=development,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("missing or invalid", result.stderr)
                self.assertEqual(self._invocations(), [])

    def test_cross_environment_state_is_rejected(self) -> None:
        targets = self._development_targets()
        targets.update(
            {
                "environment": "production",
                "dsql_database_role": "pawlocal_production_app",
            }
        )

        result = self._run(development_targets=targets)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("selected environment state is not development", result.stderr)
        self.assertEqual(self._invocations(), [])

    def test_account_mismatch_is_rejected(self) -> None:
        targets = self._development_targets()
        targets["aws_account_id"] = "333333333333"

        result = self._run(development_targets=targets)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("do not identify the same AWS account", result.stderr)
        self.assertEqual(self._invocations(), [])

    def test_non_development_region_is_rejected(self) -> None:
        targets = self._development_targets()
        targets.update(
            {
                "aws_region": "us-east-1",
                "dsql_cluster_arn": (
                    f"arn:aws:dsql:us-east-1:{ACCOUNT}:cluster/{CLUSTER_ID}"
                ),
                "dsql_endpoint": f"{CLUSTER_ID}.dsql.us-east-1.on.aws",
            }
        )

        result = self._run(development_targets=targets)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("does not identify the approved AWS region", result.stderr)
        self.assertEqual(self._invocations(), [])

    def test_provider_and_bootstrap_diagnostics_are_redacted(self) -> None:
        private_marker = "PRIVATE_PROVIDER_DETAIL_TOKEN_123"
        result = self._run(
            extra_env={
                "TEST_PYTHON_STDOUT": f"identifier {RUNTIME_ROLE}",
                "TEST_PYTHON_STDERR": private_marker,
                "TEST_PYTHON_EXIT": "1",
            }
        )

        self.assertNotEqual(result.returncode, 0)
        combined = result.stdout + result.stderr
        self.assertNotIn(private_marker, combined)
        self.assertNotIn(RUNTIME_ROLE, combined)
        self.assertNotIn(CLUSTER_ID, combined)
        self.assertIn("application-role bootstrap failed", combined)

        terraform_failure = self._run(
            extra_env={
                "TEST_TERRAFORM_FAIL_OUTPUT": "identity_app_role_arns",
                "TEST_PRIVATE_DIAGNOSTIC": private_marker,
            }
        )
        self.assertNotEqual(terraform_failure.returncode, 0)
        combined = terraform_failure.stdout + terraform_failure.stderr
        self.assertNotIn(private_marker, combined)
        self.assertIn("IAM bootstrap Terraform state", combined)


if __name__ == "__main__":
    unittest.main()
