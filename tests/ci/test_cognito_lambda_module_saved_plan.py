from __future__ import annotations

import base64
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
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
    function: dict = {}
    code_updates = 0

    def respond(self, payload: dict, status: int = 200) -> None:
        response = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        if status == 404:
            self.send_header("x-amzn-errortype", "ResourceNotFoundException")
        self.send_header("Content-Length", str(len(response)))
        self.end_headers()
        self.wfile.write(response)

    def do_GET(self) -> None:
        if not self.function:
            self.respond({"Type": "User", "message": "Not found"}, 404)
        elif "/versions" in self.path:
            self.respond({"Versions": [self.function]})
        elif self.path.endswith("/code-signing-config"):
            self.respond({})
        elif "/tags/" in self.path:
            self.respond({"Tags": {}})
        elif self.path.endswith("/configuration"):
            self.respond(self.function)
        else:
            self.respond({"Configuration": self.function, "Code": {}, "Tags": {}})

    def do_PUT(self) -> None:
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
        if self.path.endswith("/code"):
            type(self).code_updates += 1
            code = base64.b64decode(body["ZipFile"])
            self.function["CodeSha256"] = base64.b64encode(hashlib.sha256(code).digest()).decode()
        else:
            self.function.update(body)
        self.respond(self.function)

    def do_DELETE(self) -> None:
        type(self).function = {}
        self.respond({})

    def do_POST(self) -> None:
        if "Logs_" in self.headers.get("X-Amz-Target", ""):
            self.rfile.read(int(self.headers.get("Content-Length", "0")))
            self.respond({"logGroups": [{
                "logGroupName": "/aws/lambda/package-test",
                "arn": "arn:aws:logs:ap-southeast-2:111111111111:log-group:/aws/lambda/package-test:*",
            }]})
            return
        if self.path.startswith("/2015-03-31/functions"):
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
            code = base64.b64decode(body.pop("Code")["ZipFile"])
            type(self).function = {
                **body,
                "FunctionArn": "arn:aws:lambda:ap-southeast-2:111111111111:function:package-test",
                "CodeSha256": base64.b64encode(hashlib.sha256(code).digest()).decode(),
                "CodeSize": len(code), "Version": "$LATEST", "State": "Active",
                "LastUpdateStatus": "Successful", "LastModified": "2026-01-01T00:00:00.000+0000",
                "RevisionId": "00000000-0000-0000-0000-000000000000",
            }
            self.respond(self.function, 201)
            return
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

variable "teardown_enabled" {{
  type    = bool
  default = false
}}

variable "function_timeout" {{
  type    = number
  default = 3
}}

module "lambda_package" {{
  source  = "terraform-aws-modules/lambda/aws"
  version = "= {MODULE_VERSION}"

  create_function          = true
  create_role              = false
  use_existing_cloudwatch_log_group = true
  function_name            = "package-test"
  lambda_role              = "arn:aws:iam::111111111111:role/package-test"
  runtime                  = "nodejs22.x"
  handler                  = "index.handler"
  timeout                  = var.function_timeout
  source_path              = "${{path.root}}/index.mjs"
  artifacts_dir            = "${{path.root}}/.terraform/lambda-builds"
  recreate_missing_package = true
  trigger_on_package_timestamp = false
  ignore_source_code_hash  = true
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
        "AWS_ENDPOINT_URL_LAMBDA": STS_ENDPOINT,
        "AWS_ENDPOINT_URL_CLOUDWATCH_LOGS": STS_ENDPOINT,
        "TF_IN_AUTOMATION": "true",
    }
    # Rebuild only module-local sidecars for normal saved plans, not teardown.
    if arguments and arguments[0] == "plan" and "-destroy" not in arguments and not any(
        "teardown_enabled=true" in argument for argument in arguments
    ):
        arguments = (*arguments,
            "-replace=module.lambda_package.local_file.archive_plan[0]",
            "-replace=module.lambda_package.null_resource.archive[0]",
        )
    result = subprocess.run(
        ["terraform", *arguments],
        cwd=directory,
        check=False,
        capture_output=True,
        text=True,
        env=terraform_environment,
        timeout=300,
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


def lambda_action(workspace: Path, plan_name: str) -> list[str]:
    plan = json.loads(run_terraform(workspace, "show", "-json", plan_name).stdout)
    return next(
        change["change"]["actions"] for change in plan["resource_changes"]
        if change["address"] == "module.lambda_package.aws_lambda_function.this[0]"
    )


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
        StubStsHandler.function = {}
        StubStsHandler.code_updates = 0
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
            )
            shutil.rmtree(plan_workspace / ".terraform/lambda-builds")

            run_terraform(
                plan_workspace,
                "plan",
                "-input=false",
                "-var=create_consumer=true",
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

    def test_unchanged_lambda_is_noop_on_fresh_runners_but_configuration_updates(self) -> None:
        with self.temporary_directory("pawlocal-lambda-module-noop-") as temporary:
            root = Path(temporary)
            original = root / "original"
            original.mkdir()
            write_configuration(original)
            initialize(original)
            run_terraform(original, "apply", "-input=false", "-auto-approve")
            plan_workspace = root / "fresh-plan"
            plan_workspace.mkdir()
            write_configuration(plan_workspace)
            shutil.copy2(original / ".terraform.lock.hcl", plan_workspace)
            shutil.copy2(original / "terraform.tfstate", plan_workspace)
            initialize(plan_workspace, readonly=True)
            run_terraform(plan_workspace, "plan", "-input=false", "-out=unchanged.tfplan")
            self.assertEqual(lambda_action(plan_workspace, "unchanged.tfplan"), ["no-op"])
            apply_workspace = root / "fresh-apply"
            copy_saved_plan_workspace(plan_workspace, apply_workspace, "unchanged.tfplan",
                source=PLANNED_SOURCE, include_state=True)
            run_terraform(apply_workspace, "apply", "-input=false", "-auto-approve", "unchanged.tfplan")
            self.assertEqual(StubStsHandler.code_updates, 0)
            assert_package(self, package_path(apply_workspace), PLANNED_SOURCE)
            run_terraform(apply_workspace, "plan", "-input=false",
                "-var=function_timeout=4", "-out=config.tfplan")
            self.assertEqual(lambda_action(apply_workspace, "config.tfplan"), ["update"])
            run_terraform(apply_workspace, "apply", "-input=false", "-auto-approve", "config.tfplan")
            self.assertEqual(StubStsHandler.function["Timeout"], 4)
            self.assertEqual(StubStsHandler.code_updates, 0)

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
                "-out=source.tfplan",
            )
            self.assertEqual(lambda_action(plan_workspace, "source.tfplan"), ["update"])
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
            self.assertEqual(StubStsHandler.code_updates, 1)

            build_directory = apply_workspace / ".terraform/lambda-builds"
            shutil.rmtree(build_directory)
            self.assertFalse(build_directory.exists())
            self.assertEqual(
                (apply_workspace / "index.mjs").read_text(encoding="utf-8"),
                CHANGED_SOURCE,
            )

    def test_teardown_preparation_needs_no_package_work(self) -> None:
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
            )
            shutil.rmtree(plan_workspace / ".terraform/lambda-builds")

            run_terraform(
                plan_workspace,
                "plan",
                "-input=false",
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
            )
            shutil.rmtree(plan_workspace / ".terraform/lambda-builds")
            run_terraform(
                plan_workspace,
                "plan",
                "-destroy",
                "-input=false",
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
