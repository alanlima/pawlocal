"""Release consumer mode/privacy validation is separate from the YAML copier."""

import unittest

from test_integration import build, helper, values, mappings, store_for, FakeAPI, module
from urllib.error import HTTPError

consumer = helper("release_config", "release-config.py")


class ReleaseConsumerTests(unittest.TestCase):
    def test_disabled_snapshot_needs_no_ingest_bindings_and_omits_stale_collector(self):
        data = values("development")
        for name in (
            "OTEL_EXPORTER_OTLP_ENDPOINT",
            "PAWLOCAL_GRAFANA_OTLP_INSTANCE_ID",
            "VITE_FARO_COLLECTOR_URL",
        ):
            data.pop(name)
        result = consumer.project(data, "development")
        self.assertEqual(result["VITE_TELEMETRY_ENABLED"], "false")
        self.assertNotIn("VITE_FARO_COLLECTOR_URL", result)
        self.assertEqual(build.load_public(__import__("json").dumps(result)), result)

    def test_enabled_consumer_requires_verified_public_bindings(
        self,
    ):
        data = values("development") | {
            "VITE_TELEMETRY_ENABLED": "true",
            "PAWLOCAL_TELEMETRY_ENABLED": "true",
        }
        result = consumer.project(data, "development")
        self.assertEqual(
            result["VITE_FARO_COLLECTOR_URL"], data["VITE_FARO_COLLECTOR_URL"]
        )
        for name in (
            "VITE_FARO_COLLECTOR_URL",
            "OTEL_EXPORTER_OTLP_ENDPOINT",
            "PAWLOCAL_GRAFANA_OTLP_INSTANCE_ID",
        ):
            bad = dict(data)
            bad.pop(name)
            with self.subTest(name=name), self.assertRaises((ValueError, TypeError)):
                consumer.project(bad, "development")
        for name, value in (
            ("PAWLOCAL_TELEMETRY_ENABLED", "invalid"),
            ("VITE_TELEMETRY_ENABLED", "1"),
            (
                "VITE_FARO_COLLECTOR_URL",
                "https://user:private@faro.grafana.net/collect/public",
            ),
            (
                "OTEL_EXPORTER_OTLP_ENDPOINT",
                "https://gateway.grafana.net/otlp?token=private",
            ),
            ("PAWLOCAL_GRAFANA_OTLP_INSTANCE_ID", "private-instance"),
        ):
            with self.subTest(name=name), self.assertRaises((ValueError, TypeError)):
                consumer.project(data | {name: value}, "development")

    def test_all_independent_combinations_and_browser_only_without_otlp(self):
        for backend in ("true", "false"):
            for frontend in ("true", "false"):
                with self.subTest(backend=backend, frontend=frontend):
                    data = values("development") | {
                        "PAWLOCAL_TELEMETRY_ENABLED": backend,
                        "VITE_TELEMETRY_ENABLED": frontend,
                    }
                    if backend == "false":
                        data.pop("OTEL_EXPORTER_OTLP_ENDPOINT")
                        data.pop("PAWLOCAL_GRAFANA_OTLP_INSTANCE_ID")
                    result = consumer.project(data, "development")
                    self.assertEqual(result["PAWLOCAL_TELEMETRY_ENABLED"], backend)
                    self.assertEqual(result["VITE_TELEMETRY_ENABLED"], frontend)
                    self.assertEqual("VITE_FARO_COLLECTOR_URL" in result, frontend == "true")
                    self.assertEqual(build.load_public(__import__("json").dumps(result)), result)
                    self.assertNotIn("OTEL_EXPORTER_OTLP_ENDPOINT", result)

    def test_frontend_only_complete_copier_snapshot_needs_seeded_public_metadata(self):
        data = values("development") | {
            "PAWLOCAL_TELEMETRY_ENABLED": "false",
            "VITE_TELEMETRY_ENABLED": "true",
            "OTEL_EXPORTER_OTLP_ENDPOINT": "https://otlp-gateway-prod-au-southeast-1.grafana.net/otlp",
            "PAWLOCAL_GRAFANA_OTLP_INSTANCE_ID": "1880841",
        }
        data.pop("PAWLOCAL_GRAFANA_URL")
        data.pop("PAWLOCAL_GRAFANA_WEBHOOK_URL")
        selected = mappings("development")

        def target_api(api):
            def request(value, timeout):
                if "/environments/oncall-development" in value.full_url:
                    raise HTTPError(value.full_url, 404, "Not Found", {}, None)
                return api(value, timeout)
            return request

        api = FakeAPI()
        store = store_for(selected, data)
        result = module.reconcile(
            selected, store, module.GitHub("alanlima/pawlocal", "fixture", target_api(api)),
            lambda _: None, mode="enforce", environment="development",
        )
        snapshot = consumer.project(result, "development")
        self.assertEqual(snapshot["VITE_TELEMETRY_ENABLED"], "true")
        self.assertEqual(snapshot["PAWLOCAL_TELEMETRY_ENABLED"], "false")
        self.assertEqual(build.load_public(__import__("json").dumps(snapshot)), snapshot)
        self.assertFalse(any("/secrets/" in call["Name"] for call in store.client.calls))
        self.assertFalse(any("/oncall/" in call["Name"] or call["Name"].endswith("grafana/stack-url") for call in store.client.calls))
        self.assertFalse(api.secrets)

        # An unseeded, tag-protected optional backend binding can be denied by
        # AWS. Generic copying must abort, never manufacture a partial snapshot.
        denied = Exception("public parameter denied")
        denied.response = {"Error": {"Code": "AccessDeniedException"}}
        store = store_for(selected, data)
        store.client.values["/pawlocal/development/config/grafana/otlp-endpoint"] = denied
        api = FakeAPI()
        with self.assertRaises(module.ReconciliationError):
            module.reconcile(
                selected, store, module.GitHub("alanlima/pawlocal", "fixture", target_api(api)),
                lambda _: None, mode="enforce", environment="development",
            )
        self.assertFalse(api.variables)

    def test_missing_mode_yields_no_build_snapshot_and_private_fields_never_pass(self):
        data = values("development")
        data.pop("VITE_TELEMETRY_ENABLED")
        self.assertEqual(consumer.project(data, "development"), {})
        data = values("development") | {
            "OPENAI_API_KEY": "private",
            "PAWLOCAL_GRAFANA_QUERY_TOKEN": "private",
        }
        result = consumer.project(data, "development")
        self.assertNotIn("private", __import__("json").dumps(result))
        self.assertEqual(set(result), build.FIELDS | {"VITE_TELEMETRY_ENABLED", "PAWLOCAL_TELEMETRY_ENABLED"})
