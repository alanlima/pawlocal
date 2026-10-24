import copy
import importlib.util
import io
import json
import os
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from test_provision import FakeAPI, configured

SPEC = importlib.util.spec_from_file_location(
    "production_setup", Path(__file__).resolve().parents[1] / "production_setup.py"
)
setup = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(setup)
CREDS = {"GRAFANA_CLOUD_ACCESS_POLICY_TOKEN": "fixture-cloud", "GRAFANA_SERVICE_ACCOUNT_TOKEN": "fixture-stack"}


def prod_manifest():
    prod_conf = copy.deepcopy(configured())
    prod_conf["frontend_origin"] = "https://pawlocal.alanlima.cloud"
    return {
        "version": 1,
        "environments": {
            "development": {"enabled": False, "stack": None, "frontend_origin": None,
                            "datasources": None, "approval": None},
            "production": prod_conf,
        },
    }


class ProductionSetupTests(unittest.TestCase):
    def test_main_preserves_actionable_real_validation_and_credential_reasons(self):
        for env, reason in (
            ({"SETUP_MODE": "discover"}, "Discovery requires actual stack URL and region"),
            ({"STACK_URL": "https://teststack.grafana.net", "STACK_REGION": "au"}, "Missing operator credential GRAFANA_CLOUD_ACCESS_POLICY_TOKEN"),
        ):
            stderr = io.StringIO()
            with self.subTest(reason=reason), patch.dict(os.environ, env, clear=True), patch("sys.stderr", stderr), self.assertRaises(SystemExit):
                setup.main()
            self.assertIn(reason, stderr.getvalue())

    def test_main_preserves_protocol_reason_without_actual_server_body_or_token(self):
        for error, reason, category in (
            (HTTPError("https://teststack.grafana.net", 403, "private-server-reason", {}, io.BytesIO(b"private-server-body")), "GET API failed with HTTP 403", "http-error"),
            (URLError("private-network-detail"), "GET API transport failure", "network"),
        ):
            transport = setup.provision.Transport()
            stderr = io.StringIO()
            env = {"STACK_URL": "https://teststack.grafana.net", "STACK_REGION": "au", "GRAFANA_CLOUD_ACCESS_POLICY_TOKEN": "private-token-fixture"}
            with self.subTest(category=category), patch.dict(os.environ, env, clear=True), patch.object(setup.provision, "Transport", return_value=transport), patch.object(transport.opener, "open", side_effect=error), patch("sys.stderr", stderr), self.assertRaises(SystemExit):
                setup.main()
            self.assertIn(reason, stderr.getvalue())
            self.assertIn("category=" + category, stderr.getvalue())
            self.assertNotIn("private-", stderr.getvalue())

    def test_default_discovery_reads_only_and_returns_actual_public_bindings(self):
        api = FakeAPI()
        result = setup.execute(
            "discover", "https://teststack.grafana.net", "au", "", "", CREDS, api
        )
        self.assertEqual(result["stack"]["id"], 42)
        self.assertTrue(api.calls)
        self.assertTrue(all(call[0] == "GET" for call in api.calls))

    def test_plan_is_read_only_and_apply_owns_only_selected_folder_and_faro(self):
        api = FakeAPI()
        raw = json.dumps(prod_manifest())
        origin = "https://pawlocal.alanlima.cloud"
        setup.execute("plan", "", "", raw, origin, CREDS, api)
        self.assertTrue(all(call[0] == "GET" for call in api.calls))
        setup.execute("apply", "", "", raw, origin, CREDS, api)
        writes = [call for call in api.calls if call[0] != "GET"]
        self.assertTrue(writes)
        for method, url, _token, payload, _stack in writes:
            self.assertIn(method, {"POST", "PUT"})
            self.assertTrue("/api/folders" in url or "/faro/api/v1/app" in url)
            self.assertIn("production", json.dumps(payload))
            self.assertNotIn("alert", url)
            self.assertNotIn("synthetic", url)

    def test_disabled_or_foreign_origin_never_reaches_remote_api(self):
        for mutation in ("origin", "disabled"):
            value = prod_manifest()
            if mutation == "disabled":
                value["environments"]["production"]["enabled"] = False
            api = FakeAPI()
            origin = "https://foreign.test.org" if mutation == "origin" else "https://pawlocal.alanlima.cloud"
            with self.subTest(mutation=mutation), self.assertRaises(setup.provision.ProvisionError):
                setup.execute("apply", "", "", json.dumps(value), origin, {}, api)
            self.assertEqual(api.calls, [])


if __name__ == "__main__":
    unittest.main()
