import copy
import importlib.util
import io
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from test_provision import FakeAPI, configured

SPEC = importlib.util.spec_from_file_location(
    "development_setup", Path(__file__).resolve().parents[1] / "development_setup.py"
)
setup = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(setup)
CREDS = {"GRAFANA_CLOUD_ACCESS_POLICY_TOKEN": "fixture-cloud", "GRAFANA_SERVICE_ACCOUNT_TOKEN": "fixture-stack"}


def manifest():
    return {
        "version": 1,
        "environments": {
            "development": configured(),
            "production": {"enabled": False, "stack": None, "frontend_origin": None,
                           "datasources": None, "approval": None},
        },
    }


class DevelopmentSetupTests(unittest.TestCase):
    def test_main_reports_only_safe_protocol_metadata_on_failure(self):
        stderr = io.StringIO()
        with patch.object(setup, "execute", side_effect=setup.provision.TransportError(
            "private-response-fixture", "http-error", 403
        )), patch("sys.stderr", stderr), self.assertRaises(SystemExit):
            setup.main()
        self.assertIn("http_status=403", stderr.getvalue())
        self.assertNotIn("private-response-fixture", stderr.getvalue())

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
        raw = json.dumps(manifest())
        setup.execute("plan", "", "", raw, configured()["frontend_origin"], CREDS, api)
        self.assertTrue(all(call[0] == "GET" for call in api.calls))
        setup.execute("apply", "", "", raw, configured()["frontend_origin"], CREDS, api)
        writes = [call for call in api.calls if call[0] != "GET"]
        self.assertTrue(writes)
        for method, url, _token, payload, _stack in writes:
            self.assertIn(method, {"POST", "PUT"})
            self.assertTrue("/api/folders" in url or "/faro/api/v1/app" in url)
            self.assertNotIn("production", json.dumps(payload))
            self.assertNotIn("alert", url)
            self.assertNotIn("synthetic", url)

    def test_production_or_foreign_origin_never_reaches_remote_api(self):
        for mutation in ("production", "origin", "disabled"):
            value = manifest()
            if mutation == "production":
                value["environments"]["production"] = copy.deepcopy(configured())
                value["environments"]["production"]["frontend_origin"] = "https://prod.test.org"
            elif mutation == "disabled":
                value["environments"]["development"] = copy.deepcopy(value["environments"]["production"])
            api = FakeAPI()
            origin = "https://foreign.test.org" if mutation == "origin" else configured()["frontend_origin"]
            with self.subTest(mutation=mutation), self.assertRaises(setup.provision.ProvisionError):
                setup.execute("apply", "", "", json.dumps(value), origin, {}, api)
            self.assertEqual(api.calls, [])

    def test_ambiguous_oversized_or_mixed_mode_inputs_are_rejected_before_api(self):
        for mode, stack, region, raw, origin in (
            ("alerts", "", "", "", ""),
            ("discover", "https://teststack.grafana.net", "au", "{}", ""),
            ("discover", "", "", "", ""),
            ("plan", "", "", '{"version":1,"version":1}', configured()["frontend_origin"]),
            ("apply", "", "", " " * 16385, configured()["frontend_origin"]),
            ("plan", "https://teststack.grafana.net", "au", json.dumps(manifest()), configured()["frontend_origin"]),
        ):
            api = FakeAPI()
            with self.subTest(mode=mode, size=len(raw)), self.assertRaises(setup.provision.ProvisionError):
                setup.execute(mode, stack, region, raw, origin, {}, api)
            self.assertEqual(api.calls, [])


if __name__ == "__main__":
    unittest.main()
