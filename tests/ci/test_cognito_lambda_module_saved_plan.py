from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import unittest
import zipfile


MODULE_VERSION = "8.12.0"
PLANNED_SOURCE = "export const marker = 'reviewed-plan';\n"
CHANGED_SOURCE = "export const marker = 'changed-source';\n"
STS_ENDPOINT = ""


class StubStsHandler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        response = b"""<?xml version="1.0" encoding="UTF-8"?>
<GetCallerIdentityResponse xmlns="https://sts.amazonaws.com/doc/2011-06-15/">
  <GetCallerIdentityResult>
    <Arn>arn:aws:iam::111111111111:user/terraform-package-test</Arn>
    <UserId>AIDATESTUSER</UserId>
    <Account>111111111111</Account>
  </GetCallerIdentityResult>
  <ResponseMetadata><RequestId>00000000-0000-0000-0000-000000000000</RequestId></ResponseMetadata>
</GetCallerIdentityResponse>
"""
        self.send_response(200)
        self.send_header("Content-Type", "text/xml")
        self.send_header("Content-Length", str(len(response)))
        self.end_headers()
        self.wfile.write(response)

    def log_message(self, format: str, *args: object) -> None:
        return

TERRAFORM_CONFIGURATION = f"""
terraform {{
  required_version = "= 1.14.3"
}}

provider "aws" {{
  region                      = "ap-southeast-2"
  access_key                  = "test"
  secret_key                  = "test"
  skip_credentials_validation = true
  skip_metadata_api_check     = true
  skip_region_validation      = true
  skip_requesting_account_id  = true
}}

variable "create_consumer" {{
  type    = bool
  default = false
}}

variable "package_build_id" {{
  type = string
}}

variable "teardown_enabled" {{
  type    = bool
  default = false
}}

module "lambda_package" {{
  source  = "terraform-aws-modules/lambda/aws"
  version = "= {MODULE_VERSION}"

  create_function          = false
  create_role              = false
  source_path              = "${{path.root}}/index.mjs"
  artifacts_dir            = "${{path.root}}/.terraform/lambda-builds"
  recreate_missing_package = true
  trigger_on_package_timestamp = false
  hash_extra               = var.package_build_id
}}

resource "terraform_data" "lambda_consumer" {{
  count = var.create_consumer ? 1 : 0
  input = module.lambda_package.local_filename

  provisioner "local-exec" {{
    interpreter = ["python", "-c"]
    command     = "import pathlib,sys; sys.exit(0 if pathlib.Path(r'${{module.lambda_package.local_filename}}').is_file() else 23)"
  }}

  depends_on = [module.lambda_package]
}}

resource "terraform_data" "teardown_control" {{
  input = var.teardown_enabled
}}

output "package_filename" {{
  value = module.lambda_package.local_filename
}}
""".lstrip()


def run_terraform(
    directory: Path, *arguments: str, check: bool = True
) -> subprocess.CompletedProcess[str]:
    terraform_environment = {
        **os.environ,
        "AWS_ACCESS_KEY_ID": "test",
        "AWS_SECRET_ACCESS_KEY": "test",
        "AWS_SESSION_TOKEN": "test",
        "AWS_REGION": "ap-southeast-2",
        "AWS_EC2_METADATA_DISABLED": "true",
        "AWS_ENDPOINT_URL_STS": STS_ENDPOINT,
        "TF_IN_AUTOMATION": "true",
    }
    result = subprocess.run(
        ["terraform", *arguments],
        cwd=directory,
        check=False,
        capture_output=True,
        text=True,
        env=terraform_environment,
    )
    if check and result.returncode != 0:
        raise AssertionError(
            f"terraform {' '.join(arguments)} failed in {directory}\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    return result


def write_configuration(directory: Path, source: str = PLANNED_SOURCE) -> None:
    (directory / "main.tf").write_text(TERRAFORM_CONFIGURATION, encoding="utf-8")
    (directory / "index.mjs").write_text(source, encoding="utf-8", newline="")


def initialize(directory: Path, *, readonly: bool = False) -> None:
    arguments = ["init", "-backend=false", "-input=false"]
    if readonly:
        arguments.append("-lockfile=readonly")
    run_terraform(directory, *arguments)


def copy_saved_plan_workspace(
    plan_workspace: Path,
    apply_workspace: Path,
    plan_name: str,
    *,
    source: str,
    include_state: bool,
) -> None:
    apply_workspace.mkdir()
    write_configuration(apply_workspace, source)
    shutil.copy2(plan_workspace / ".terraform.lock.hcl", apply_workspace)
    shutil.copy2(plan_workspace / plan_name, apply_workspace)
    if include_state:
        shutil.copy2(plan_workspace / "terraform.tfstate", apply_workspace)
    initialize(apply_workspace, readonly=True)


def package_path(workspace: Path) -> Path:
    value = run_terraform(workspace, "output", "-raw", "package_filename").stdout.strip()
    path = Path(value)
    return path if path.is_absolute() else workspace / path


def assert_package(test: unittest.TestCase, path: Path, expected_source: str) -> None:
    test.assertTrue(path.is_file(), f"expected Lambda package at {path}")
    with zipfile.ZipFile(path) as package:
        test.assertEqual(package.read("index.mjs").decode(), expected_source)


@unittest.skipUnless(
    os.environ.get("PAWLOCAL_RUN_TERRAFORM_LAMBDA_MODULE_INTEGRATION") == "1",
    "set PAWLOCAL_RUN_TERRAFORM_LAMBDA_MODULE_INTEGRATION=1 to run Terraform integration",
)
class CognitoLambdaModuleSavedPlanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        global STS_ENDPOINT
        cls.sts_server = ThreadingHTTPServer(("127.0.0.1", 0), StubStsHandler)
        cls.sts_thread = threading.Thread(target=cls.sts_server.serve_forever, daemon=True)
        cls.sts_thread.start()
        host, port = cls.sts_server.server_address
        STS_ENDPOINT = f"http://{host}:{port}"

    @classmethod
    def tearDownClass(cls) -> None:
        cls.sts_server.shutdown()
        cls.sts_server.server_close()
        cls.sts_thread.join()

    def setUp(self) -> None:
        if shutil.which("terraform") is None:
            self.skipTest("terraform is required for the saved-plan integration test")

    def temporary_directory(self, prefix: str) -> tempfile.TemporaryDirectory[str]:
        root = os.environ.get("PAWLOCAL_TEST_TEMP_DIR")
        if root:
            Path(root).mkdir(parents=True, exist_ok=True)
        return tempfile.TemporaryDirectory(prefix=prefix, dir=root)

    def test_initial_saved_plan_builds_package_on_fresh_apply_runner(self) -> None:
        with self.temporary_directory("pawlocal-lambda-module-initial-") as temporary:
            root = Path(temporary)
            plan_workspace = root / "plan"
            apply_workspace = root / "apply"
            plan_workspace.mkdir()
            write_configuration(plan_workspace)
            initialize(plan_workspace)
            run_terraform(
                plan_workspace,
                "plan",
                "-input=false",
                "-var=create_consumer=true",
                "-var=package_build_id=initial-plan",
                "-out=tfplan",
            )

            copy_saved_plan_workspace(
                plan_workspace,
                apply_workspace,
                "tfplan",
                source=PLANNED_SOURCE,
                include_state=False,
            )
            self.assertEqual(list((apply_workspace / ".terraform/lambda-builds").glob("*.zip")), [])
            run_terraform(apply_workspace, "apply", "-input=false", "-auto-approve", "tfplan")
            assert_package(self, package_path(apply_workspace), PLANNED_SOURCE)

    def test_missing_unchanged_package_is_rebuilt_before_pending_consumer(self) -> None:
        with self.temporary_directory("pawlocal-lambda-module-retry-") as temporary:
            root = Path(temporary)
            plan_workspace = root / "plan"
            apply_workspace = root / "apply"
            plan_workspace.mkdir()
            write_configuration(plan_workspace)
            initialize(plan_workspace)
            run_terraform(
                plan_workspace,
                "apply",
                "-input=false",
                "-auto-approve",
                "-var=package_build_id=initial-state",
            )
            shutil.rmtree(plan_workspace / ".terraform/lambda-builds")

            run_terraform(
                plan_workspace,
                "plan",
                "-input=false",
                "-var=create_consumer=true",
                "-var=package_build_id=retry-plan",
                "-out=retry.tfplan",
            )
            copy_saved_plan_workspace(
                plan_workspace,
                apply_workspace,
                "retry.tfplan",
                source=PLANNED_SOURCE,
                include_state=True,
            )
            self.assertEqual(list((apply_workspace / ".terraform/lambda-builds").glob("*.zip")), [])
            run_terraform(
                apply_workspace,
                "apply",
                "-input=false",
                "-auto-approve",
                "retry.tfplan",
            )
            assert_package(self, package_path(apply_workspace), PLANNED_SOURCE)

    def test_source_change_gets_a_new_package_identity_and_scoped_cleanup(self) -> None:
        with self.temporary_directory("pawlocal-lambda-module-source-") as temporary:
            root = Path(temporary)
            plan_workspace = root / "plan"
            apply_workspace = root / "apply"
            plan_workspace.mkdir()
            write_configuration(plan_workspace)
            initialize(plan_workspace)
            run_terraform(
                plan_workspace,
                "apply",
                "-input=false",
                "-auto-approve",
                "-var=package_build_id=source-one",
            )
            original_package = package_path(plan_workspace)
            assert_package(self, original_package, PLANNED_SOURCE)

            (plan_workspace / "index.mjs").write_text(
                CHANGED_SOURCE, encoding="utf-8", newline=""
            )
            run_terraform(
                plan_workspace,
                "plan",
                "-input=false",
                "-var=package_build_id=source-two",
                "-out=source.tfplan",
            )
            copy_saved_plan_workspace(
                plan_workspace,
                apply_workspace,
                "source.tfplan",
                source=CHANGED_SOURCE,
                include_state=True,
            )
            run_terraform(
                apply_workspace,
                "apply",
                "-input=false",
                "-auto-approve",
                "source.tfplan",
            )
            changed_package = package_path(apply_workspace)
            self.assertNotEqual(original_package.name, changed_package.name)
            assert_package(self, changed_package, CHANGED_SOURCE)

            build_directory = apply_workspace / ".terraform/lambda-builds"
            shutil.rmtree(build_directory)
            self.assertFalse(build_directory.exists())
            self.assertEqual(
                (apply_workspace / "index.mjs").read_text(encoding="utf-8"),
                CHANGED_SOURCE,
            )

    def test_teardown_preparation_reuses_state_build_id_without_package_work(self) -> None:
        with self.temporary_directory("pawlocal-lambda-module-prepare-") as temporary:
            root = Path(temporary)
            plan_workspace = root / "plan"
            apply_workspace = root / "apply"
            plan_workspace.mkdir()
            write_configuration(plan_workspace)
            initialize(plan_workspace)
            run_terraform(
                plan_workspace,
                "apply",
                "-input=false",
                "-auto-approve",
                "-var=package_build_id=applied-build",
            )
            shutil.rmtree(plan_workspace / ".terraform/lambda-builds")

            run_terraform(
                plan_workspace,
                "plan",
                "-input=false",
                "-var=package_build_id=applied-build",
                "-var=teardown_enabled=true",
                "-out=prepare.tfplan",
            )
            plan = json.loads(
                run_terraform(plan_workspace, "show", "-json", "prepare.tfplan").stdout
            )
            changed = {
                change["address"]: change["change"]["actions"]
                for change in plan.get("resource_changes", [])
                if change["change"]["actions"] != ["no-op"]
            }
            self.assertEqual(
                changed,
                {"terraform_data.teardown_control": ["update"]},
            )

            copy_saved_plan_workspace(
                plan_workspace,
                apply_workspace,
                "prepare.tfplan",
                source=PLANNED_SOURCE,
                include_state=True,
            )
            self.assertFalse((apply_workspace / ".terraform/lambda-builds").exists())
            run_terraform(
                apply_workspace,
                "apply",
                "-input=false",
                "-auto-approve",
                "prepare.tfplan",
            )
            self.assertFalse((apply_workspace / ".terraform/lambda-builds").exists())

    def test_final_destroy_saved_plan_needs_no_package_on_fresh_runner(self) -> None:
        with self.temporary_directory("pawlocal-lambda-module-destroy-") as temporary:
            root = Path(temporary)
            plan_workspace = root / "plan"
            apply_workspace = root / "apply"
            plan_workspace.mkdir()
            write_configuration(plan_workspace)
            initialize(plan_workspace)
            run_terraform(
                plan_workspace,
                "apply",
                "-input=false",
                "-auto-approve",
                "-var=create_consumer=true",
                "-var=package_build_id=destroy-state",
            )
            shutil.rmtree(plan_workspace / ".terraform/lambda-builds")
            run_terraform(
                plan_workspace,
                "plan",
                "-destroy",
                "-input=false",
                "-var=package_build_id=destroy-plan",
                "-out=destroy.tfplan",
            )

            copy_saved_plan_workspace(
                plan_workspace,
                apply_workspace,
                "destroy.tfplan",
                source=PLANNED_SOURCE,
                include_state=True,
            )
            self.assertEqual(list((apply_workspace / ".terraform/lambda-builds").glob("*")), [])
            run_terraform(
                apply_workspace,
                "apply",
                "-input=false",
                "-auto-approve",
                "destroy.tfplan",
            )
            self.assertEqual(list((apply_workspace / ".terraform/lambda-builds").glob("*")), [])


if __name__ == "__main__":
    unittest.main()
