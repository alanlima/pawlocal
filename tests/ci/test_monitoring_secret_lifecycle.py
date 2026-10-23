"""Local-only proof for proposed #241; no production Terraform configuration.

Set PAWLOCAL_RUN_SECRET_LIFECYCLE_FIXTURE=1 after initializing the pinned
iam-bootstrap provider. All AWS API requests terminate at this loopback stub.
"""

import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from contextlib import redirect_stderr, redirect_stdout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

ROOT = Path(__file__).resolve().parents[2]
NAME = "/pawlocal/development/secrets/grafana/otlp-token"
ARN = "arn:aws:ssm:ap-southeast-2:111111111111:parameter" + NAME
FIRST = "synthetic-241-first-private-value"
SECOND = "synthetic-241-rotated-private-value"
THIRD = "synthetic-241-different-apply-value"

HCL = """
terraform {
  required_version = "= 1.14.3"
  required_providers { aws = { source = "hashicorp/aws", version = "= 6.69.1" } }
}
provider "aws" {
  region = "ap-southeast-2"
  access_key = "synthetic-not-an-aws-key"
  secret_key = "synthetic-not-an-aws-secret"
  skip_credentials_validation = true
  skip_metadata_api_check = true
  skip_region_validation = true
  skip_requesting_account_id = true
  endpoints { ssm = "ENDPOINT" }
}
variable "override_names" { type = set(string) }
variable "overrides" {
  type = map(string)
  ephemeral = true
  sensitive = true
  default = {}
  validation {
    condition = toset(keys(var.overrides)) == var.override_names && alltrue([for v in values(var.overrides) : length(trimspace(v)) > 0])
    error_message = "Exact nonempty override inputs are required."
  }
}
variable "revision" { type = number }
ephemeral "aws_ssm_parameter" "current" {
  for_each = setsubtract(toset(["token"]), var.override_names)
  arn = "ARN"
}
resource "aws_ssm_parameter" "secret" {
  name = "NAME"
  type = "SecureString"
  tier = "Standard"
  value_wo = contains(var.override_names, "token") ? var.overrides["token"] : ephemeral.aws_ssm_parameter.current["token"].value
  value_wo_version = var.revision
  lifecycle {
    prevent_destroy = true
    precondition {
      condition = contains(var.override_names, "token") ? true : length(trimspace(ephemeral.aws_ssm_parameter.current["token"].value)) > 0
      error_message = "Existing source must be nonempty."
    }
  }
}
"""


def proposed_transition_guard(before, after, override):
    """Executable contract example only; not a production setup controller."""
    if after is None or type(after.get("value_wo_version")) is not int:
        raise ValueError("Missing managed write revision")
    revision = after["value_wo_version"]
    if revision < 1 or (before is None and not override):
        raise ValueError("Explicit creation override required")
    if before is None:
        return
    previous = before["value_wo_version"]
    metadata = {
        "name",
        "type",
        "tier",
        "key_id",
        "description",
        "allowed_pattern",
        "data_type",
    }
    changed = any(before.get(key) != after.get(key) for key in metadata)
    if revision < previous or ((override or changed) and revision <= previous):
        raise ValueError("A fresh approved write revision is required")


class TransitionContract(unittest.TestCase):
    def test_stale_override_and_metadata_without_new_revision_fail_closed(self):
        before = {"value_wo_version": 2, "description": "old"}
        for after, override in [
            ({"value_wo_version": 2, "description": "old"}, True),
            ({"value_wo_version": 1, "description": "old"}, False),
            ({"value_wo_version": 2, "description": "new"}, False),
        ]:
            with (
                self.subTest(after=after, override=override),
                self.assertRaises(ValueError),
            ):
                proposed_transition_guard(before, after, override)
        proposed_transition_guard(before, before, False)
        proposed_transition_guard(
            before, {"value_wo_version": 3, "description": "new"}, False
        )

    def test_creation_needs_override_and_positive_public_revision(self):
        for after, override in [
            (None, True),
            ({"value_wo_version": 0}, True),
            ({"value_wo_version": 1}, False),
        ]:
            with (
                self.subTest(after=after, override=override),
                self.assertRaises(ValueError),
            ):
                proposed_transition_guard(None, after, override)
        proposed_transition_guard(None, {"value_wo_version": 1}, True)


def forward_checked_streams(stdout, stderr, *, private_stdout=False):
    """Preserve operational logs only after checking both complete streams."""
    stdout, stderr = stdout or b"", stderr or b""
    if any(value.encode() in stdout + stderr for value in (FIRST, SECOND, THIRD)):
        # Assertion helpers would include the forbidden bytes in their diagnostics.
        raise AssertionError("Synthetic payload detected; captured streams withheld.")
    if not private_stdout:
        sys.stdout.write(stdout.decode("utf-8", errors="replace"))
    sys.stderr.write(stderr.decode("utf-8", errors="replace"))


class FixtureLoggingContract(unittest.TestCase):
    def test_complete_success_or_failure_streams_are_forwarded_without_truncation(self):
        stdout = "stdout-start" + "x" * 6000 + "stdout-end"
        stderr = "stderr-start" + "y" * 4000 + "stderr-end"
        with (
            redirect_stdout(io.StringIO()) as out,
            redirect_stderr(io.StringIO()) as err,
        ):
            forward_checked_streams(stdout.encode(), stderr.encode())
        self.assertEqual(out.getvalue(), stdout)
        self.assertEqual(err.getvalue(), stderr)

    def test_payload_in_either_stream_withholds_both_and_failure_never_echoes_it(self):
        for stdout, stderr in (
            (FIRST.encode(), b"ordinary error"),
            (b"ordinary output", SECOND.encode()),
        ):
            with (
                redirect_stdout(io.StringIO()) as out,
                redirect_stderr(io.StringIO()) as err,
                self.assertRaisesRegex(
                    AssertionError, "captured streams withheld"
                ) as failure,
            ):
                forward_checked_streams(stdout, stderr)
            self.assertEqual(out.getvalue(), "")
            self.assertEqual(err.getvalue(), "")
            self.assertNotIn(FIRST, str(failure.exception))
            self.assertNotIn(SECOND, str(failure.exception))

    def test_programmatic_json_stdout_stays_internal_while_stderr_is_preserved(self):
        with (
            redirect_stdout(io.StringIO()) as out,
            redirect_stderr(io.StringIO()) as err,
        ):
            forward_checked_streams(
                b'{"format_version":"1.2"}', b"complete diagnostic", private_stdout=True
            )
        self.assertEqual(out.getvalue(), "")
        self.assertEqual(err.getvalue(), "complete diagnostic")
        with self.assertRaisesRegex(AssertionError, "captured streams withheld"):
            forward_checked_streams(THIRD.encode(), b"", private_stdout=True)


class SsmStub(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def do_CONNECT(self):
        self.send_error(403, "Non-loopback API access is prohibited")

    def do_POST(self):
        if self.path != "/":
            self.send_error(403)
            return
        request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        action = self.headers.get("X-Amz-Target", "").rsplit(".", 1)[-1]
        self.server.calls.append(action)
        status = 200
        result = {}
        if action == "PutParameter":
            assert request["Name"] == NAME
            assert request["Type"] == "SecureString"
            assert request["Value"]
            if self.server.value is not None and not request.get("Overwrite", False):
                status, result = (
                    400,
                    {"__type": "ParameterAlreadyExists", "message": "Collision"},
                )
            else:
                self.server.value = request["Value"]
                self.server.version += 1
                result = {"Version": self.server.version, "Tier": "Standard"}
        elif action == "GetParameter":
            assert request["Name"] in {NAME, ARN}
            assert request["WithDecryption"] is True
            if self.server.deny:
                status, result = (
                    400,
                    {"__type": "AccessDeniedException", "message": "Denied"},
                )
            elif self.server.value is None:
                status, result = (
                    400,
                    {"__type": "ParameterNotFound", "message": "Missing"},
                )
            else:
                result = {
                    "Parameter": {
                        "ARN": ARN,
                        "Name": NAME,
                        "Type": "SecureString",
                        "Value": self.server.value,
                        "Version": self.server.version,
                        "DataType": "text",
                    }
                }
        elif action == "DescribeParameters":
            result = {
                "Parameters": [
                    {
                        "Name": NAME,
                        "Type": "SecureString",
                        "Version": self.server.version,
                        "Tier": "Standard",
                        "DataType": "text",
                        "KeyId": "alias/aws/ssm",
                    }
                ]
            }
        elif action == "ListTagsForResource":
            result = {"TagList": []}
        else:
            status, result = (
                400,
                {"__type": "AccessDeniedException", "message": "Unexpected API denied"},
            )
        raw = json.dumps(result).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/x-amz-json-1.1")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


@unittest.skipUnless(
    os.getenv("PAWLOCAL_RUN_SECRET_LIFECYCLE_FIXTURE") == "1",
    "opt-in local real-provider proof",
)
class MonitoringSecretLifecycle(unittest.TestCase):
    def test_create_maintenance_rotation_and_failure_without_persisted_payload(self):
        self.assertEqual(
            subprocess.check_output(["terraform", "version", "-json"], text=True).find(
                '"1.14.3"'
            )
            >= 0,
            True,
        )
        providers = ROOT / "infra/terraform/iam-bootstrap/.terraform/providers"
        self.assertTrue(
            providers.is_dir(), "Initialize pinned iam-bootstrap provider first"
        )
        with tempfile.TemporaryDirectory(prefix="pawlocal-241-offline-") as temp:
            self.directory = Path(temp)
            self.shown = set()
            server = ThreadingHTTPServer(("127.0.0.1", 0), SsmStub)
            server.value, server.version, server.deny, server.calls = None, 0, False, []
            worker = Thread(target=server.serve_forever, daemon=True)
            worker.start()
            try:
                url = f"http://127.0.0.1:{server.server_port}"
                self.env = {
                    k: v
                    for k, v in os.environ.items()
                    if not k.startswith(("TF_", "AWS_"))
                }
                self.env.update(
                    TF_IN_AUTOMATION="true",
                    TF_INPUT="false",
                    AWS_EC2_METADATA_DISABLED="true",
                    HTTP_PROXY=url,
                    HTTPS_PROXY=url,
                    http_proxy=url,
                    https_proxy=url,
                    NO_PROXY="127.0.0.1",
                    no_proxy="127.0.0.1",
                )
                config = self.directory / "provider.tfrc"
                config.write_text(
                    "provider_installation { filesystem_mirror { path = "
                    + json.dumps(providers.as_posix())
                    + " } }",
                    encoding="utf-8",
                )
                self.env["TF_CLI_CONFIG_FILE"] = str(config)
                shutil.copyfile(
                    ROOT / "infra/terraform/iam-bootstrap/.terraform.lock.hcl",
                    self.directory / ".terraform.lock.hcl",
                )
                (self.directory / "main.tf").write_text(
                    HCL.replace("ENDPOINT", url)
                    .replace("ARN", ARN)
                    .replace("NAME", NAME),
                    encoding="utf-8",
                )
                self.run_tf("init", "-backend=false", "-lockfile=readonly")
                self.select(["token"], {"token": FIRST}, 1)
                self.run_tf("plan", "-out=create.plan")
                self.assert_no_payload()
                self.run_tf("apply", "create.plan")
                self.assertEqual(server.value, FIRST)
                self.assert_no_payload()
                self.select([], {}, 1)
                self.run_tf("plan", "-refresh-only", "-out=refresh.plan")
                self.run_tf("apply", "refresh.plan")
                before = server.calls.count("PutParameter")
                self.run_tf("plan", "-detailed-exitcode", allowed=(0,))
                self.assertEqual(server.calls.count("PutParameter"), before)
                self.assert_no_payload()
                self.select(["token"], {"token": SECOND}, 2)
                self.run_tf("plan", "-out=rotate.plan")
                self.assert_no_payload()
                self.env["TF_VAR_overrides"] = "{}"
                self.run_tf("apply", "rotate.plan", allowed=(1,))
                self.assertEqual(server.value, FIRST)
                self.env["TF_VAR_overrides"] = json.dumps({"token": SECOND})
                self.run_tf("plan", "-out=different.plan")
                self.env["TF_VAR_overrides"] = json.dumps({"token": THIRD})
                self.run_tf("apply", "different.plan")
                self.assertEqual(
                    server.value, THIRD, "Saved plan does not bind re-supplied bytes"
                )
                self.assert_no_payload()
                self.select([], {}, 2)
                server.deny = True
                before = server.calls.count("PutParameter")
                self.run_tf("plan", allowed=(1,))
                self.assertEqual(server.calls.count("PutParameter"), before)
                server.deny = False
                server.value = ""
                self.run_tf("plan", allowed=(1,))
                self.assert_no_payload()
            finally:
                server.shutdown()
                server.server_close()
                worker.join()

    def select(self, names, values, revision):
        self.env.update(
            TF_VAR_override_names=json.dumps(names),
            TF_VAR_overrides=json.dumps(values),
            TF_VAR_revision=str(revision),
        )

    def run_tf(self, *arguments, allowed=(0,)):
        private_stdout = arguments[:2] == ("show", "-json")
        try:
            result = subprocess.run(
                ["terraform", *arguments, "-no-color"],
                cwd=self.directory,
                env=self.env,
                capture_output=True,
                check=False,
                timeout=120,
            )
        except subprocess.TimeoutExpired as error:
            forward_checked_streams(
                error.stdout, error.stderr, private_stdout=private_stdout
            )
            raise
        forward_checked_streams(
            result.stdout, result.stderr, private_stdout=private_stdout
        )
        self.assertIn(
            result.returncode,
            allowed,
            "Terraform returned an unexpected exit code; complete diagnostics were emitted above.",
        )
        return result

    def assert_no_payload(self):
        for path in self.directory.iterdir():
            if not (path.name.endswith((".plan", ".tfstate", ".tfstate.backup"))):
                continue
            contents = [path.read_bytes()]
            if zipfile.is_zipfile(path):
                if path.name not in self.shown:
                    json.loads(self.run_tf("show", "-json", path.name).stdout)
                    self.shown.add(path.name)
                with zipfile.ZipFile(path) as archive:
                    contents += [archive.read(name) for name in archive.namelist()]
            for value in (FIRST, SECOND, THIRD):
                self.assertTrue(
                    all(value.encode() not in raw for raw in contents), path.name
                )
        state = self.directory / "terraform.tfstate"
        if state.exists():
            attributes = json.loads(state.read_text())["resources"][0]["instances"][0][
                "attributes"
            ]
            self.assertIn(attributes["value"], (None, ""))
            self.assertTrue(attributes["has_value_wo"])


if __name__ == "__main__":
    unittest.main()
