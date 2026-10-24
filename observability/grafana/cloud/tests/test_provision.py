import copy
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

MODULE = Path(__file__).resolve().parents[1] / "provision.py"
SPEC = importlib.util.spec_from_file_location("cloud_provision", MODULE)
p = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(p)


def configured():
    return {
        "enabled": True,
        "stack": {
            "id": 42,
            "slug": "teststack",
            "url": "https://teststack.grafana.net",
            "region": "au",
            "faro_api_url": "https://faro-api-prod-au-southeast-0.grafana.net/faro",
            "otlp_endpoint": "https://otlp-gateway-prod-au-southeast-0.grafana.net/otlp",
            "otlp_instance_id": "42",
        },
        "frontend_origin": "https://pawlocal-dev.test.org",
        "datasources": {
            signal: {"uid": signal, "name": f"cloud-{signal}"}
            for signal in ("metrics", "logs", "traces")
        },
        "approval": {
            "reference": "issue-224-reviewed",
            "residency": "Australia reviewed",
            "free_plan_verified": True,
            "quota_review": "shared account quota reviewed",
            "isolation_review": "dev-only scope; production still disabled",
        },
    }


class FakeAPI:
    def __init__(self):
        self.calls = []
        self.folder = None
        self.apps = []
        self.remote_region = "au"
        self.datasource_type = None
        self.otlp_http_url = "https://otlp-gateway-prod-au-southeast-0.grafana.net"

    def request(self, method, url, token, payload=None, stack_id=None, missing=False):
        self.calls.append((method, url, token, payload, stack_id))
        if url in (
            "https://grafana.com/api/instances/42",
            "https://grafana.com/api/instances/teststack",
        ):
            return {
                "id": 42,
                "slug": "teststack",
                "url": "https://teststack.grafana.net",
                "regionSlug": self.remote_region,
            }
        if url == "https://grafana.com/api/instances/teststack/connections":
            return {"otlpHttpUrl": self.otlp_http_url}
        if url == "https://teststack.grafana.net/api/datasources":
            return [
                {
                    "uid": key,
                    "name": f"cloud-{key}",
                    "type": kind,
                    "arbitrary": "never-export",
                }
                for key, kind in (
                    ("metrics", "prometheus"),
                    ("logs", "loki"),
                    ("traces", "tempo"),
                )
            ]
        if "/datasources/uid/" in url:
            signal = url.rsplit("/", 1)[1]
            return {
                "uid": signal,
                "name": "cloud-" + signal,
                "type": self.datasource_type
                or {"metrics": "prometheus", "logs": "loki", "traces": "tempo"}[signal],
                "secureJsonFields": {"password": True},
                "unapproved": "should-never-export",
            }
        if "/api/folders" in url:
            if method == "GET":
                return self.folder
            self.folder = copy.deepcopy(payload)
            return self.folder
        if method == "GET" and url.endswith("/app"):
            return copy.deepcopy(self.apps)
        if method in ("POST", "PUT"):
            result = {
                **copy.deepcopy(payload),
                "id": 17,
                "appKey": "public-app-key",
                "collectEndpointURL": "https://faro-collector-prod-au-southeast-0.grafana.net/collect",
            }
            self.apps = [result]
            return result
        if method == "GET" and url.endswith("/app/17"):
            return copy.deepcopy(self.apps[0])
        raise AssertionError((method, url))

    @property
    def writes(self):
        return [item for item in self.calls if item[0] != "GET"]


class ProvisionTests(unittest.TestCase):
    def setUp(self):
        self.api = FakeAPI()
        self.credentials = {
            name: "private-" + name
            for name in (
                "GRAFANA_CLOUD_ACCESS_POLICY_TOKEN",
                "GRAFANA_SERVICE_ACCOUNT_TOKEN",
                "GRAFANA_FARO_ACCESS_POLICY_TOKEN",
            )
        }
        self.runner = p.Provisioner(self.api, self.credentials)
        self.config = configured()

    def test_discovery_needs_only_stack_url_region_and_two_credential_domains(self):
        credentials = {
            key: value
            for key, value in self.credentials.items()
            if key != "GRAFANA_FARO_ACCESS_POLICY_TOKEN"
        }
        result = p.Provisioner(self.api, credentials).discover(
            "https://teststack.grafana.net", "au"
        )
        self.assertEqual(result["stack"]["otlp_instance_id"], "42")
        self.assertEqual(
            result["stack"]["faro_api_url"],
            "https://faro-api-prod-au-southeast-0.grafana.net/faro",
        )
        self.assertEqual(result["datasources"]["traces"]["uid"], "traces")
        self.assertEqual(result["status"], "discovered-not-approved")
        self.assertNotIn("arbitrary", json.dumps(result))
        self.assertEqual(self.api.writes, [])
        with self.assertRaises(p.ProvisionError):
            self.runner.discover("https://teststack.grafana.net", "eu")

    def test_ambiguous_discovery_returns_public_candidates_then_explicit_selection(self):
        original = self.api.request
        def request(method, url, token, **kwargs):
            result = original(method, url, token, **kwargs)
            if url.endswith("/api/datasources"):
                result.append({"uid": "usage", "name": "cloud-usage", "type": "prometheus", "secureJsonData": {"token": "private-never-export"}})
            return result
        self.api.request = request
        result = self.runner.discover("https://teststack.grafana.net", "au")
        self.assertEqual(result["status"], "needs-selection-not-approved")
        self.assertEqual(result["unresolved_signals"], ["metrics"])
        self.assertNotIn("metrics", result["datasources"])
        self.assertEqual(len(result["datasource_candidates"]["metrics"]), 2)
        self.assertTrue(all(set(row) == {"uid", "name", "type"} for rows in result["datasource_candidates"].values() for row in rows))
        self.assertNotIn("private-never-export", json.dumps(result))
        self.assertNotIn("arbitrary", json.dumps(result))
        self.assertEqual(len(self.api.calls), 3)
        result = self.runner.discover("https://teststack.grafana.net", "au", '{"metrics":"metrics"}')
        self.assertEqual(result["status"], "discovered-not-approved")
        self.assertEqual(result["unresolved_signals"], [])
        self.assertEqual(result["datasources"]["metrics"], {"uid": "metrics", "name": "cloud-metrics"})
        self.assertEqual(len(self.api.calls), 6)
        self.assertEqual(self.api.writes, [])
        for selector in ('{"metrics":"foreign"}', '{"metrics":"logs"}'):
            with self.subTest(selector=selector), self.assertRaises(p.ProvisionError):
                self.runner.discover("https://teststack.grafana.net", "au", selector)

    def test_bad_selector_denies_before_any_network_even_for_unique_sources(self):
        for selector in ('[]', '{"metrics":1}', '{"metrics":""}', '{"metrics":"a/b"}', '{"metrics":"a\\n"}', '{"metrics":"a","metrics":"b"}', '{"unknown":"a"}', 'x'*513):
            with self.subTest(selector=selector), self.assertRaises(p.ProvisionError):
                self.runner.discover("https://teststack.grafana.net", "au", selector)
            self.assertEqual(self.api.calls, [])
        for selector in ('{"metrics":"missing"}', '{"metrics":"logs"}'):
            with self.subTest(selector=selector), self.assertRaises(p.ProvisionError):
                self.runner.discover("https://teststack.grafana.net", "au", selector)

    def test_duplicate_selected_uid_and_malformed_or_oversized_candidates_deny(self):
        original = self.api.request
        for mutation in ("duplicate", "name", "uid", "oversized", "shape"):
            def request(method, url, token, mutation=mutation, **kwargs):
                result = original(method, url, token, **kwargs)
                if url.endswith("/api/datasources"):
                    if mutation == "duplicate": result.append(copy.deepcopy(result[0]))
                    if mutation == "name": result[0]["name"] = "private\nline"
                    if mutation == "uid": result[0]["uid"] = "foreign/path"
                    if mutation == "oversized": result *= 34
                    if mutation == "shape": result.append(None)
                return result
            self.api.request = request
            with self.subTest(mutation=mutation), self.assertRaises(p.ProvisionError):
                self.runner.discover("https://teststack.grafana.net", "au", '{"metrics":"metrics"}')
        self.assertEqual(self.api.writes, [])

    def test_cli_discovery_forwards_selector_and_rejects_it_in_other_modes(self):
        arguments = ["provision.py", "--environment", "development", "--mode", "discover", "--stack-url", "https://teststack.grafana.net", "--region", "au", "--datasource-uids-json", '{"metrics":"metrics"}']
        output = io.StringIO()
        with patch("sys.argv", arguments), patch.object(p, "Transport", return_value=self.api), patch.dict(p.os.environ, self.credentials), patch("sys.stdout", output):
            p.main()
        self.assertEqual(json.loads(output.getvalue())["datasources"]["metrics"]["uid"], "metrics")
        self.assertEqual(self.api.writes, [])
        with patch("sys.argv", ["provision.py", "--environment", "development", "--mode", "check", "--datasource-uids-json", '{}']), self.assertRaises(p.ProvisionError):
            p.main()

    def test_faro_endpoint_creation_cutoff_and_regional_exceptions(self):
        self.assertEqual(
            p.faro_management_url("prod-us-east-0", "2025-01-01T00:00:00Z"),
            "https://faro-api-prod-us-east-2.grafana.net/faro",
        )
        self.assertEqual(
            p.faro_management_url("prod-us-east-0", "2024-01-01T00:00:00Z"),
            "https://faro-api-prod-us-east-0.grafana.net/faro",
        )
        self.assertEqual(
            p.faro_management_url("azure-uaenorth-0", None),
            "https://faro-api-prod-me-central-2.azure-uaenorth-0.grafana.net/faro",
        )
        with self.assertRaises(p.ProvisionError):
            p.faro_management_url("prod-us-east-0", None)

    def test_connection_origin_and_suffixed_endpoint_normalize_once_for_discovery_and_reconcile(
        self,
    ):
        expected = "https://otlp-gateway-prod-au-southeast-0.grafana.net/otlp"
        for suffix in ("", "/", "/otlp", "/otlp/"):
            with self.subTest(suffix=suffix):
                self.api.otlp_http_url = expected.removesuffix("/otlp") + suffix
                result = self.runner.discover("https://teststack.grafana.net", "au")
                self.assertEqual(result["stack"]["otlp_endpoint"], expected)
                self.runner.reconcile("development", self.config, apply=False)
                self.assertEqual(self.api.writes, [])

    def test_unsafe_or_non_otlp_connection_shape_blocks_discovery_and_all_writes(self):
        for url in (
            "https://otlp-gateway.grafana.net/otlp/otlp",
            "https://otlp-gateway.grafana.net/v1/traces",
            "https://user:private@otlp-gateway.grafana.net/otlp",
            "https://otlp-gateway.grafana.net/otlp?token=private",
            "https://otlp-gateway.grafana.net:443/otlp",
            "https://otlp-gateway.invalid/otlp",
        ):
            self.api.otlp_http_url = url
            with self.subTest(url=url):
                with self.assertRaises(p.ProvisionError):
                    self.runner.discover("https://teststack.grafana.net", "au")
                with self.assertRaises(p.ProvisionError):
                    self.runner.reconcile("development", self.config, apply=True)
                self.assertEqual(self.api.writes, [])

    def test_disabled_never_reads_credentials_or_calls_network(self):
        disabled = {
            "enabled": False,
            "stack": None,
            "frontend_origin": None,
            "datasources": None,
            "approval": None,
        }
        self.assertEqual(
            p.Provisioner(self.api, {}).reconcile("development", disabled, apply=True)[
                "status"
            ],
            "disabled",
        )
        self.assertEqual(self.api.calls, [])

    def test_manifest_rejects_unknown_fields_duplicate_keys_wildcards_and_secret_fields(
        self,
    ):
        disabled = {
            "enabled": False,
            "stack": None,
            "frontend_origin": None,
            "datasources": None,
            "approval": None,
        }
        document = {
            "version": 1,
            "environments": {"development": self.config, "production": disabled},
        }
        p.validate_manifest(document)
        for key, value in [
            ("frontend_origin", "https://*.test.org"),
            ("frontend_origin", "https://test.org/path"),
            ("approval", None),
        ]:
            broken = copy.deepcopy(document)
            broken["environments"]["development"][key] = value
            with self.assertRaises(p.ProvisionError):
                p.validate_manifest(broken)
        with_disclaimer = copy.deepcopy(document)
        with_disclaimer["disclaimer"] = "Architectural review note."
        p.validate_manifest(with_disclaimer)
        for invalid_disclaimer in [123, "", "x" * 2001, None]:
            bad_disclaimer = copy.deepcopy(document)
            bad_disclaimer["disclaimer"] = invalid_disclaimer
            with self.assertRaises(p.ProvisionError):
                p.validate_manifest(bad_disclaimer)
        document["token"] = "secret"
        with self.assertRaises(p.ProvisionError):
            p.validate_manifest(document)
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "bad.json"
            path.write_text('{"version":1,"version":1,"environments":{}}')
            with self.assertRaises(p.ProvisionError):
                p.load_manifest(path)

    def test_plan_is_read_only_and_create_then_second_apply_is_noop(self):
        planned = self.runner.reconcile("development", self.config)
        self.assertEqual(planned["operations"], ["create-folder", "create-faro"])
        self.assertEqual(self.api.writes, [])
        created = self.runner.reconcile("development", self.config, apply=True)
        self.assertEqual(len(self.api.writes), 2)
        self.assertEqual(
            created["public_handoff"][
                "/pawlocal/development/config/grafana/faro-collector-url"
            ],
            "https://faro-collector-prod-au-southeast-0.grafana.net/collect/public-app-key",
        )
        for token in self.credentials.values():
            self.assertNotIn(token, json.dumps(created))
        self.assertNotIn("unapproved", json.dumps(created))
        self.api.calls.clear()
        self.assertEqual(
            self.runner.reconcile("development", self.config, apply=True)["operations"],
            [],
        )
        self.assertEqual(self.api.writes, [])

    def test_updates_faro_in_place_without_delete_or_recreate(self):
        self.runner.reconcile("development", self.config, apply=True)
        self.api.calls.clear()
        self.config["frontend_origin"] = "https://reviewed-new.test.org"
        self.runner.reconcile("development", self.config, apply=True)
        self.assertEqual([item[0] for item in self.api.writes], ["PUT"])
        self.assertTrue(self.api.writes[0][1].endswith("/app/17"))

    def test_foreign_folder_or_app_collision_blocks_all_writes(self):
        self.api.folder = {"uid": "pawlocal-development", "title": "Unrelated folder"}
        with self.assertRaises(p.ProvisionError):
            self.runner.reconcile("development", self.config, apply=True)
        self.assertEqual(self.api.writes, [])
        self.api.folder = None
        self.api.apps = [
            {"id": 17, "name": "pawlocal-development", "extraLogLabels": []}
        ]
        with self.assertRaises(p.ProvisionError):
            self.runner.reconcile("development", self.config, apply=True)
        self.assertEqual(self.api.writes, [])

    def test_region_or_datasource_mismatch_blocks_all_writes(self):
        self.api.remote_region = "eu"
        with self.assertRaises(p.ProvisionError):
            self.runner.reconcile("development", self.config, apply=True)
        self.assertEqual(self.api.writes, [])
        self.api.remote_region = "au"
        self.api.datasource_type = "wrong-plugin"
        with self.assertRaises(p.ProvisionError):
            self.runner.reconcile("development", self.config, apply=True)
        self.assertEqual(self.api.writes, [])

    def test_foreign_otlp_endpoint_blocks_mutation(self):
        self.config["stack"]["otlp_endpoint"] = "https://other-stack.grafana.net/otlp"
        with self.assertRaisesRegex(p.ProvisionError, "OTLP endpoint differs"):
            self.runner.reconcile("development", self.config, apply=True)
        self.assertEqual(self.api.writes, [])

    def test_missing_credentials_fail_before_writes(self):
        with self.assertRaisesRegex(p.ProvisionError, "Missing operator credential"):
            p.Provisioner(self.api, {}).reconcile("development", self.config)
        self.assertEqual(self.api.calls, [])

    def test_real_transport_auth_shape_and_redirect_denial(self):
        transport = p.Transport()
        response = unittest.mock.MagicMock()
        response.__enter__.return_value.read.return_value = b"[]"
        with patch.object(transport.opener, "open", return_value=response) as opening:
            transport.request(
                "GET", "https://test.grafana.net/faro/api/v1/app", "secret", stack_id=42
            )
            request = opening.call_args.args[0]
            self.assertEqual(request.get_header("Authorization"), "Bearer 42:secret")
            self.assertEqual(request.get_header("X-scope-orgid"), "42")
            transport.request(
                "PUT",
                "https://test.grafana.net/api/v1/provisioning/policies",
                "secret",
                payload={"receiver": "operator"},
                extra_headers={"X-Disable-Provenance": "true"},
            )
            request = opening.call_args.args[0]
            self.assertEqual(request.get_header("X-disable-provenance"), "true")
            self.assertEqual(request.get_header("Authorization"), "Bearer secret")
            transport.request("GET", "https://test.grafana.net/api/org", "secret")
            self.assertIsNone(
                opening.call_args.args[0].get_header("X-disable-provenance")
            )
            with self.assertRaises(p.ProvisionError):
                transport.request(
                    "GET",
                    "https://test.grafana.net/api/org",
                    "secret",
                    extra_headers={"Authorization": "Bearer other"},
                )
        with self.assertRaises(p.ProvisionError):
            p.NoRedirect().redirect_request(
                None, None, 302, "", {}, "https://attacker.test"
            )

    def test_api_errors_never_echo_response_payload(self):
        transport = p.Transport()
        error = HTTPError(
            "https://test.grafana.net",
            403,
            "denied",
            {},
            io.BytesIO(b"echoed-private-token"),
        )
        with patch.object(transport.opener, "open", side_effect=error):
            with self.assertRaises(p.ProvisionError) as result:
                transport.request("GET", "https://test.grafana.net", "private")
            self.assertNotIn("echoed-private", str(result.exception))
            self.assertIn("403", str(result.exception))


if __name__ == "__main__":
    unittest.main()
