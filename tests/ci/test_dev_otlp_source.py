"""One-source DEV boundary tests; opt-in fixture uses loopback AWS only."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import tempfile
from http.server import ThreadingHTTPServer
from threading import Thread
import unittest
from unittest.mock import patch
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[2]
def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

boundary = load("dev_otlp_boundary", ROOT / "ops/monitoring/dev_otlp_source.py")
base = load("secret_fixture", ROOT / "tests/ci/test_monitoring_secret_lifecycle.py")
WHEN = "2026-10-23T06:38:21.498Z"
CREATION = {"managed": True, "write_revision": 1, "creation": {"legacy_version": 1, "legacy_last_modified": WHEN}}
MAINTENANCE = {"managed": True, "write_revision": 1, "creation": None}
OFF = {"managed": False, "write_revision": 1, "creation": None}
ARN = "arn:aws:ssm:ap-southeast-2:111111111111:parameter" + boundary.LEGACY

class Client:
    def __init__(self):
        self.calls = []
        self.parameter = dict(ARN=ARN, Name=boundary.LEGACY, Type="String", Version=1,
                              LastModifiedDate=WHEN, Value=base.FIRST)
    def get_parameter(self, **kwargs):
        self.calls.append(kwargs)
        return {"Parameter": self.parameter.copy()}

def plan(chosen=CREATION):
    after = dict(name=boundary.TARGET, type="SecureString", tier="Standard", overwrite=None,
                 value=None, insecure_value=None, value_wo=None, value_wo_version=1,
                 description=boundary.DESCRIPTION, tags=boundary.TAGS, has_value_wo=True, version=1)
    creation = chosen["creation"] is not None
    return {"variables": {"dev_otlp_source_" + key: {"value": value} for key, value in chosen.items()},
            "resource_changes": [{"address": boundary.ADDRESS, "type": "aws_ssm_parameter", "index": 0,
                                  "change": {"before": None if creation else after.copy(), "after": after,
                                             "actions": ["create"] if creation else ["no-op"], "after_unknown": {}}}]}

class BoundaryTests(unittest.TestCase):
    def test_atomic_single_read_and_child_environment(self):
        client = Client()
        with boundary.creation_environment(client, CREATION, "111111111111", "ap-southeast-2") as env:
            self.assertEqual(env[boundary.PRIVATE_VARIABLE], base.FIRST)
            self.assertNotIn(boundary.PRIVATE_VARIABLE, os.environ)
        self.assertNotIn(boundary.PRIVATE_VARIABLE, env)
        self.assertEqual(client.calls, [{"Name": ARN, "WithDecryption": False}])

    def test_current_drift_denied_even_when_historical_version_one_exists(self):
        class HistoricalClient(Client):
            def get_parameter(self, **kwargs):
                self.calls.append(kwargs)
                response = self.parameter.copy()
                if not kwargs["Name"].endswith(":1"):
                    response["Version"] = 2
                return {"Parameter": response}
        client = HistoricalClient()
        self.assertEqual(client.get_parameter(Name=ARN + ":1")["Parameter"]["Version"], 1)
        client.calls.clear()
        with self.assertRaises(ValueError):
            with boundary.creation_environment(client, CREATION, "111111111111", "ap-southeast-2"):
                self.fail("Current version drift must not yield private input")
        self.assertEqual(client.calls, [{"Name": ARN, "WithDecryption": False}])

    def test_private_sdk_exception_and_debug_trace_are_not_exposed(self):
        client = Client()
        with patch.object(client, "get_parameter", side_effect=RuntimeError(base.FIRST)):
            with self.assertRaises(ValueError) as failure:
                with boundary.creation_environment(client, CREATION, "111111111111", "ap-southeast-2"):
                    self.fail("SDK failure must not yield an environment")
            self.assertNotIn(base.FIRST, str(failure.exception))
        with patch.dict(os.environ, {"TF_LOG": "TRACE"}), self.assertRaises(ValueError):
            with boundary.creation_environment(client, CREATION, "111111111111", "ap-southeast-2"):
                self.fail("Debug trace must not reach private input")
        self.assertEqual(client.calls, [])

    def test_source_recreated_changed_or_malformed_denied(self):
        for key, value in (("LastModifiedDate", "2026-10-23T07:00:00Z"), ("Version", 2),
                           ("Type", "SecureString"), ("ARN", ARN + "-wrong"), ("Value", "")):
            client = Client()
            client.parameter[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                with boundary.creation_environment(client, CREATION, "111111111111", "ap-southeast-2"):
                    self.fail("Rejected metadata must not yield an environment")

    def test_collision_pagination_and_maintenance_type(self):
        boundary.target_metadata({"Parameters": []}, CREATION)
        boundary.target_metadata({"Parameters": [{"Name": boundary.TARGET, "Type": "SecureString", "Version": 1}]}, MAINTENANCE)
        for response, chosen in (({"Parameters": [{"Name": boundary.TARGET}]}, CREATION),
                                 ({"Parameters": [], "NextToken": "more"}, CREATION),
                                 ({"Parameters": []}, MAINTENANCE),
                                 ({"Parameters": [{"Name": boundary.TARGET, "Type": "SecureString", "Version": 2}]}, MAINTENANCE),
                                 ({"Parameters": [{"Name": boundary.TARGET, "Type": "String"}]}, MAINTENANCE)):
            with self.subTest(response=response), self.assertRaises(ValueError):
                boundary.target_metadata(response, chosen)

    def test_selection_and_metadata_bound_to_plan(self):
        boundary.plan_guard(plan(), CREATION)
        boundary.plan_guard(plan(MAINTENANCE), MAINTENANCE)
        candidate = plan()
        candidate["variables"]["dev_otlp_source_managed"]["value"] = "true"
        candidate["variables"]["dev_otlp_source_write_revision"]["value"] = "1"
        boundary.plan_guard(candidate, CREATION)
        for field, value in (("description", "wrong"), ("tags", {}), ("name", boundary.LEGACY), ("value_wo_version", 2)):
            candidate = plan()
            candidate["resource_changes"][0]["change"]["after"][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                boundary.plan_guard(candidate, CREATION)
        candidate = plan()
        candidate["variables"]["dev_otlp_source_creation"]["value"] = None
        with self.assertRaises(ValueError):
            boundary.plan_guard(candidate, CREATION)

    def test_import_delete_replace_unknown_and_other_mutation_denied(self):
        for actions in (["delete"], ["delete", "create"], ["update"]):
            candidate = plan()
            candidate["resource_changes"][0]["change"]["actions"] = actions
            with self.subTest(actions=actions), self.assertRaises(ValueError):
                boundary.plan_guard(candidate, CREATION)
        for candidate in (plan(), plan(MAINTENANCE)):
            chosen = CREATION if candidate["resource_changes"][0]["change"]["before"] is None else MAINTENANCE
            candidate["resource_changes"][0]["change"]["after_unknown"] = {"tags": True}
            with self.assertRaises(ValueError):
                boundary.plan_guard(candidate, chosen)
        candidate = plan()
        candidate["resource_changes"][0]["change"]["importing"] = {"id": boundary.TARGET}
        with self.assertRaises(ValueError):
            boundary.plan_guard(candidate, CREATION)
        candidate = plan()
        candidate["resource_changes"].append({"address": "aws_other.new", "change": {"actions": ["create"]}})
        with self.assertRaises(ValueError):
            boundary.plan_guard(candidate, CREATION)
        with self.assertRaises(ValueError):
            boundary.plan_guard(plan(MAINTENANCE), OFF)
        candidate = plan(MAINTENANCE)
        candidate["resource_changes"][0]["change"]["after"]["version"] = 2
        candidate["resource_changes"][0]["change"]["before"]["version"] = 2
        with self.assertRaises(ValueError):
            boundary.plan_guard(candidate, MAINTENANCE)

class SsmStub(base.SsmStub):
    def do_POST(self):
        request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        action = self.headers.get("X-Amz-Target", "").rsplit(".", 1)[-1]
        self.server.calls.append((action, request.get("Name")))
        status, result = 200, {}
        if action == "PutParameter":
            assert request["Name"] == boundary.TARGET and request["Type"] == "SecureString"
            if self.server.value is not None and not request.get("Overwrite", False):
                status, result = 400, {"__type": "ParameterAlreadyExists", "message": "Collision"}
            else:
                self.server.value = request["Value"]
                self.server.version += 1
                result = {"Version": self.server.version, "Tier": "Standard"}
        elif action == "GetParameter":
            assert request["Name"] in (boundary.TARGET, ARN + "-v1", ARN)
            if request["Name"] == ARN:
                assert request["WithDecryption"] is False
                result = {"Parameter": dict(ARN=ARN, Name=boundary.LEGACY, Type="String", Version=1,
                                           Value=base.FIRST, LastModifiedDate=WHEN)}
            elif self.server.deny or self.server.value is None:
                status, result = 400, {"__type": "AccessDeniedException", "message": "Denied"}
            else:
                result = {"Parameter": dict(ARN=ARN + "-v1", Name=boundary.TARGET, Type=self.server.kind,
                          Value=self.server.value, Version=self.server.version, DataType="text")}
        elif action == "DescribeParameters":
            result = {"Parameters": [dict(Name=boundary.TARGET, Type=self.server.kind, Version=self.server.version,
                       Tier="Standard", DataType="text", KeyId="alias/aws/ssm", Description=boundary.DESCRIPTION)]}
        elif action == "ListTagsForResource":
            result = {"TagList": [{"Key": key, "Value": value} for key, value in boundary.TAGS.items()]}
        else:
            status, result = 400, {"__type": "AccessDeniedException", "message": "Unexpected API denied"}
        raw = json.dumps(result).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/x-amz-json-1.1")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

class LoopbackClient:
    def __init__(self, url):
        self.url = url

    def get_parameter(self, **kwargs):
        request = Request(self.url, data=json.dumps(kwargs).encode(),
                          headers={"X-Amz-Target": "AmazonSSM.GetParameter", "Content-Type": "application/x-amz-json-1.1"})
        with urlopen(request, timeout=5) as response:
            result = json.loads(response.read())
        # The real SDK exposes server timestamps as datetime objects.
        result["Parameter"]["LastModifiedDate"] = boundary.stamp(result["Parameter"]["LastModifiedDate"])
        return result

@unittest.skipUnless(os.getenv("PAWLOCAL_RUN_SECRET_LIFECYCLE_FIXTURE") == "1", "opt-in local real-provider proof")
class RealProvider(unittest.TestCase):
    run_tf = base.MonitoringSecretLifecycle.run_tf
    assert_no_payload = base.MonitoringSecretLifecycle.assert_no_payload

    def test_actual_module_creation_and_new_source_only_maintenance(self):
        providers = ROOT / "infra/terraform/iam-bootstrap/.terraform/providers"
        self.assertTrue(providers.is_dir())
        with tempfile.TemporaryDirectory(prefix="pawlocal-dev-otlp-") as temp:
            self.directory, self.shown = Path(temp), set()
            server = ThreadingHTTPServer(("127.0.0.1", 0), SsmStub)
            server.value, server.version, server.kind, server.deny, server.calls = None, 0, "SecureString", False, []
            worker = Thread(target=server.serve_forever, daemon=True)
            worker.start()
            try:
                url = f"http://127.0.0.1:{server.server_port}"
                self.env = {key: value for key, value in os.environ.items() if not key.startswith(("TF_", "AWS_"))}
                self.env.update(TF_IN_AUTOMATION="true", TF_INPUT="false", AWS_EC2_METADATA_DISABLED="true",
                                HTTP_PROXY=url, HTTPS_PROXY=url, http_proxy=url, https_proxy=url,
                                NO_PROXY="127.0.0.1", no_proxy="127.0.0.1")
                config = self.directory / "provider.tfrc"
                config.write_text("provider_installation { filesystem_mirror { path = " + json.dumps(providers.as_posix()) + " } }")
                self.env["TF_CLI_CONFIG_FILE"] = str(config)
                shutil.copyfile(ROOT / "infra/terraform/iam-bootstrap/.terraform.lock.hcl", self.directory / ".terraform.lock.hcl")
                hcl = base.HCL[:base.HCL.index('variable "override_names"')].replace("ENDPOINT", url)
                source = (ROOT / "infra/terraform/modules/dev-otlp-source").as_posix()
                hcl += '''
variable "dev_otlp_source_managed" { type = bool }
variable "dev_otlp_source_write_revision" { type = number }
variable "dev_otlp_source_creation" { type = object({legacy_version=number, legacy_last_modified=string}) }
variable "dev_otlp_source_creation_value" {
 type = string
 sensitive = true
 ephemeral = true
 default = null
}
module "dev_otlp_source" {
 source = "SOURCE"
 account_id = "111111111111"
 aws_region = "ap-southeast-2"
 managed = var.dev_otlp_source_managed
 write_revision = var.dev_otlp_source_write_revision
 creation = var.dev_otlp_source_creation
 creation_value = var.dev_otlp_source_creation_value
}
'''.replace("SOURCE", source)
                (self.directory / "main.tf").write_text(hcl)
                self.run_tf("init", "-backend=false", "-lockfile=readonly")
                self.select(OFF)
                self.run_tf("plan", "-out=off.plan")
                self.assertEqual(server.calls, [])
                self.select(CREATION)
                client = LoopbackClient(url)
                with boundary.creation_environment(client, CREATION, "111111111111", "ap-southeast-2") as child:
                    self.env[boundary.PRIVATE_VARIABLE] = child[boundary.PRIVATE_VARIABLE]
                    self.run_tf("plan", "-out=create.plan")
                    public_plan = json.loads(self.run_tf("show", "-json", "create.plan").stdout)
                    boundary.plan_guard(public_plan, CREATION)
                    self.assert_no_payload()
                    self.run_tf("apply", "create.plan")
                self.env.pop(boundary.PRIVATE_VARIABLE)
                self.assertEqual(server.value, base.FIRST)
                self.assert_no_payload()
                self.select(MAINTENANCE)
                before = len(server.calls)
                self.run_tf("plan", "-out=maintain.plan", "-detailed-exitcode")
                boundary.plan_guard(json.loads(self.run_tf("show", "-json", "maintain.plan").stdout), MAINTENANCE)
                self.assertTrue(all(name != boundary.LEGACY for _, name in server.calls[before:]))
                self.run_tf("apply", "maintain.plan")
                self.assertEqual(sum(action == "PutParameter" for action, _ in server.calls), 1)
                self.assert_no_payload()
                server.deny = True
                self.run_tf("plan", allowed=(1,))
                server.deny = False
                server.kind = "String"
                self.run_tf("plan", allowed=(1,))
                self.assert_no_payload()
            finally:
                server.shutdown()
                server.server_close()
                worker.join()

    def select(self, chosen):
        for key, value in chosen.items():
            self.env["TF_VAR_dev_otlp_source_" + key] = json.dumps(value)

if __name__ == "__main__":
    unittest.main()
