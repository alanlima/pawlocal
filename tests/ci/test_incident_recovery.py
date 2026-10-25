import os
from unittest.mock import patch
import copy
import datetime as dt
import io
import json
import sys
import tempfile
import unittest
import urllib.parse
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "ops/incident-response"))
import recovery
from quota import Denied


class Response(io.BytesIO):
    status = 200

    def __init__(self, value, url):
        super().__init__(
            value if isinstance(value, bytes) else json.dumps(value).encode()
        )
        self.url = url

    def geturl(self):
        return self.url


@patch.dict(os.environ, {'PAWLOCAL_ONCALL_ENFORCE_GUARDS': 'true'})
class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.now = 1800000000.0
        self.calls = []
        self.scenario_environment = "development"
        self.mutate = lambda value, url: value
        self.release = {
            "affected_sha": "a" * 40,
            "image_digest": "sha256:" + "b" * 64,
            "deployment_id": 12,
            "deployment_run": 13,
        }
        self.profile = SimpleNamespace(
            recovery_seconds=600,
            rule_uids={"development": "rule1", "production": "rule2"},
            digest="c" * 64,
            valid_at=lambda now: None,
        )
        path = self.root / "observability/grafana/cloud/bindings.json"
        path.parent.mkdir(parents=True)
        self.binding = {
            "version": 1,
            "environments": {
                "development": {
                    "enabled": True,
                    "approval": {"reference": "approved"},
                    "frontend_origin": "https://pawlocal-dev.example.com",
                    "stack": {"url": "https://test.grafana.net"},
                    "datasources": {
                        "metrics": {"uid": "metrics1", "name": "Prometheus"}
                    },
                }
            },
        }
        path.write_text(json.dumps(self.binding), encoding="utf-8")
        self.environment = patch.dict(os.environ, {"PAWLOCAL_ONCALL_ENABLED": "true"})
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def open(self, request, timeout):
        url = request.full_url
        self.calls.append((url, dict(request.headers), timeout))
        parsed = urllib.parse.urlsplit(url)
        if parsed.netloc == "test.grafana.net":
            self.assertEqual(
                request.get_header("Authorization"), "Bearer private-token"
            )
            if parsed.path.endswith("/rules"):
                rule = {
                    "uid": self.profile.rule_uids.get(self.scenario_environment, "default-uid"),
                    "queriedDatasourceUIDs": ["metrics1"],
                    "type": "alerting",
                    "isPaused": False,
                    "health": "ok",
                    "state": "inactive",
                    "lastError": "",
                    "alerts": [],
                    "labels": {
                        "environment": self.scenario_environment,
                        "service": "pawlocal-api",
                    },
                    "lastEvaluation": dt.datetime.fromtimestamp(
                        self.now, dt.UTC
                    ).isoformat(),
                }
                value = {"status": "success", "data": {"groups": [{"rules": [rule]}]}}
            elif parsed.path.endswith("/alerts"):
                value = []
            else:
                query = urllib.parse.parse_qs(parsed.query)["query"][0]
                self.assertIn(self.release["image_digest"], query)
                self.assertIn(f'environment="{self.scenario_environment}"', query)
                self.assertIn('service="pawlocal-api"', query)
                self.assertIn("timestamp(", query)
                value = {
                    "status": "success",
                    "data": {
                        "resultType": "vector",
                        "result": [{"value": [self.now, "2"]}],
                    },
                }
        else:
            self.assertIsNone(request.get_header("Authorization"))
            if parsed.path == "/health":
                value = {
                    "status": "ok",
                    "environment": self.scenario_environment,
                    "image_digest": self.release["image_digest"],
                }
            elif parsed.path == "/api/v1/places":
                value = {
                    "items": [
                        {
                            "id": "11111111-2222-3333-4444-555555555555",
                            "name": "PRIVATE_CUSTOMER_SENTINEL",
                        }
                    ]
                }
            elif parsed.path.startswith("/api/v1/places/"):
                value = {
                    "id": "11111111-2222-3333-4444-555555555555",
                    "description": "PRIVATE_CUSTOMER_SENTINEL",
                }
            else:
                value = b"<html>public frontend</html>"
        return Response(self.mutate(copy.deepcopy(value), url), url)

    def observe(self, **overrides):
        arguments = {
            "trusted": self.root,
            "environment": "development",
            "release": self.release,
            "profile": self.profile,
            "service": "pawlocal-api",
            "api_base_url": "https://api-dev.example.com/api/v1",
            "frontend_origin": "https://pawlocal-dev.example.com",
            "stack_url": "https://test.grafana.net",
            "query_token": "private-token",
            "deadline": self.now + 1800,
            "opener": self,
            "clock": lambda: self.now,
            "sleep": self.sleep,
        }
        arguments.update(overrides)
        return recovery.observe(**arguments)

    def sleep(self, seconds):
        self.now += seconds

    def production(self):
        self.scenario_environment = "production"
        os.environ["PAWLOCAL_PRODUCTION_TELEMETRY_READ_APPROVED"] = "true"
        selected = copy.deepcopy(self.binding["environments"]["development"])
        selected["frontend_origin"] = "https://pawlocal.example.com"
        self.binding["environments"]["production"] = selected
        (self.root / "observability/grafana/cloud/bindings.json").write_text(
            json.dumps(self.binding), encoding="utf-8"
        )
        return {
            "environment": "production",
            "frontend_origin": "https://pawlocal.example.com",
            "api_base_url": "https://api.example.com/api/v1",
        }

    def test_production_full_stable_window_exact_scopes(self):
        proof = self.observe(**self.production())
        self.assertEqual(proof["environment"], "production")
        self.assertEqual(proof["digest"], self.release["image_digest"])
        self.assertEqual(proof["deployment_id"], 12)
        self.assertEqual(proof["samples"], 21)
        self.assertEqual(proof["completed_at"] - proof["started_at"], 600)
        for url, headers, _ in self.calls:
            self.assertNotIn("api-dev.", url)
            self.assertNotIn("pawlocal-dev.", url)
            if "/api/v1/query?" in url:
                query = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)[
                    "query"
                ][0]
                self.assertNotIn('environment="development"', query)
                self.assertIn("pawlocal_api_requests_total", query)
                self.assertIn("pawlocal_dependency_requests_total", query)
                self.assertIn('outcome="success"', query)
                self.assertIn(self.release["image_digest"], query)
            if "test.grafana.net" not in url:
                self.assertNotIn("Authorization", headers)

    def test_production_normal_instance_matches_real_grafana_runtime_shape(self):
        # Grafana api_prometheus_test.go: inactive rules retain Normal instances.
        # https://github.com/grafana/grafana/blob/main/pkg/services/ngalert/api/api_prometheus_test.go
        options = self.production()

        def mutate(value, url):
            if url.endswith("/rules"):
                rule = value["data"]["groups"][0]["rules"][0]
                rule["alerts"] = [
                    {
                        "state": "Normal",
                        "labels": {"job": "prometheus"},
                        "annotations": {},
                        "activeAt": "0001-01-01T00:00:00Z",
                        "value": "",
                    }
                ]
                rule["totals"] = {"normal": 1}
                rule["totalsFiltered"] = {"normal": 1}
            return value

        self.mutate = mutate
        proof = self.observe(**options)
        self.assertEqual(proof["samples"], 21)
        self.assertEqual(proof["settling_samples"], 0)

    def test_development_nodata_instance_reports_healthy(self):
        def mutate(value, url):
            if url.endswith("/rules"):
                value["data"]["groups"][0]["rules"][0]["alerts"] = [
                    {"state": "NoData"}
                ]
            return value

        self.mutate = mutate
        proof = self.observe()
        self.assertEqual(proof["environment"], "development")
        self.assertEqual(proof["samples"], 21)
        self.assertEqual(proof["settling_samples"], 0)

    def test_production_non_normal_instances_never_report_healthy(self):
        options = self.production()
        for state in [
            "Pending",
            "Alerting",
            "Recovering",
            "NoData",
            "Error",
            "unknown",
        ]:
            with self.subTest(state=state):

                def mutate(value, url, state=state):
                    if url.endswith("/rules"):
                        value["data"]["groups"][0]["rules"][0]["alerts"] = [
                            {"state": "Normal"},
                            {"state": state},
                        ]
                    return value

                self.mutate = mutate
                with self.assertRaises(Denied):
                    self.observe(**options)

    def test_production_wrong_rule_or_environment_never_recovers(self):
        options = self.production()
        for field, bad in [
            ("uid", "rule1"),
            ("isPaused", True),
            ("health", "error"),
            ("labels", {"environment": "development", "service": "pawlocal-api"}),
        ]:
            with self.subTest(field=field):

                def mutate(value, url, field=field, bad=bad):
                    if url.endswith("/rules"):
                        value["data"]["groups"][0]["rules"][0][field] = bad
                    return value

                self.mutate = mutate
                with self.assertRaises(Denied):
                    self.observe(**options)

    def test_production_no_metric_data_cannot_report_recovery(self):
        options = self.production()

        def mutate(value, url):
            if "/api/v1/query?" in url:
                value["data"]["result"] = []
            return value

        self.mutate = mutate
        with self.assertRaisesRegex(Denied, "settling exhausted"):
            self.observe(**options)

    def test_production_metric_regression_and_read_revocation(self):
        options = self.production()
        initial = self.now

        def mutate(value, url):
            if "/api/v1/query?" in url and self.now - initial >= 300:
                value["data"]["result"] = []
            return value

        self.mutate = mutate
        with self.assertRaisesRegex(Denied, "regressed"):
            self.observe(**options)
        self.mutate = lambda value, url: value
        initial = self.now

        def control():
            if self.now - initial >= 60:
                os.environ["PAWLOCAL_PRODUCTION_TELEMETRY_READ_APPROVED"] = "false"

        with self.assertRaisesRegex(Denied, "revoked"):
            self.observe(**options, control=control)

    def configured(self, **overrides):
        options = {
            "trusted": self.root,
            "environment": "production",
            "profile": self.profile,
            "service": "pawlocal-api",
            "api_base_url": "https://api.example.com/api/v1",
            "frontend_origin": "https://pawlocal.example.com",
            "stack_url": "https://test.grafana.net",
            "query_token": "private-token",
            "deadline": self.now + 1800,
            "opener": self,
            "clock": lambda: self.now,
        }
        options.update(overrides)
        return recovery.configured_rule(**options)

    def test_configured_production_rule_allows_pre_repair_firing_without_claiming_recovery(
        self,
    ):
        self.production()
        for state, instance in [
            ("inactive", "Normal"),
            ("pending", "Pending"),
            ("firing", "Alerting"),
        ]:
            with self.subTest(state=state):
                self.calls = []

                def mutate(value, url, state=state, instance=instance):
                    rule = value["data"]["groups"][0]["rules"][0]
                    rule["state"] = state
                    rule["alerts"] = [{"state": instance}]
                    return value

                self.mutate = mutate
                self.assertIsNone(self.configured())
                self.assertEqual(len(self.calls), 1)
                self.assertTrue(
                    self.calls[0][0].endswith("/api/prometheus/grafana/api/v1/rules")
                )

    def test_configured_rule_missing_wrong_paused_unknown_denies_before_queries(self):
        self.production()
        cases = [
            ("uid", "foreign"),
            ("isPaused", True),
            ("state", "unknown"),
            ("health", "error"),
            ("health", "nodata"),
            ("lastEvaluation", "2000-01-01T00:00:00Z"),
            ("alerts", [{"state": "NoData"}]),
        ]
        for field, bad in cases:
            with self.subTest(field=field, bad=bad):
                self.calls = []

                def mutate(value, url, field=field, bad=bad):
                    value["data"]["groups"][0]["rules"][0][field] = bad
                    return value

                self.mutate = mutate
                with self.assertRaises(Denied):
                    self.configured()
                self.assertEqual(len(self.calls), 1)
                self.assertNotIn("query?", self.calls[0][0])
        self.mutate = lambda value, url: {"status": "success", "data": {"groups": []}}
        with self.assertRaisesRegex(Denied, "exact rule unavailable"):
            self.configured()

    def test_configured_production_read_and_binding_revocation_fail_before_reads(self):
        self.production()
        os.environ["PAWLOCAL_PRODUCTION_TELEMETRY_READ_APPROVED"] = "false"
        with self.assertRaisesRegex(Denied, "revoked"):
            self.configured()
        self.assertEqual(self.calls, [])
        os.environ["PAWLOCAL_PRODUCTION_TELEMETRY_READ_APPROVED"] = "true"
        self.binding["environments"]["production"]["enabled"] = False
        (self.root / "observability/grafana/cloud/bindings.json").write_text(
            json.dumps(self.binding), encoding="utf-8"
        )
        with self.assertRaisesRegex(Denied, "binding unavailable"):
            self.configured()
        self.assertEqual(self.calls, [])

    def test_configured_live_control_denial_prevents_any_read(self):
        self.production()

        def control():
            raise Denied("live stop")

        with self.assertRaisesRegex(Denied, "live stop"):
            self.configured(control=control)
        self.assertEqual(self.calls, [])

    def test_rule_datasource_binding_exact_for_observation_and_prerequisite(self):
        options = self.production()
        for sources in [
            None,
            [],
            ["foreign"],
            ["metrics1", "foreign"],
            ["metrics1", "__expr__"],
            ["metrics1", "metrics1"],
            "metrics1",
            [123],
        ]:
            with self.subTest(sources=sources):

                def mutate(value, url, sources=sources):
                    if url.endswith("/rules"):
                        rule = value["data"]["groups"][0]["rules"][0]
                        if sources is None:
                            rule.pop("queriedDatasourceUIDs")
                        else:
                            rule["queriedDatasourceUIDs"] = sources
                    return value

                self.mutate = mutate
                with self.assertRaisesRegex(Denied, "datasource differs"):
                    self.observe(**options)
                self.calls = []
                with self.assertRaisesRegex(Denied, "datasource differs"):
                    self.configured()
                self.assertEqual(len(self.calls), 1)
                self.assertNotIn("query?", self.calls[0][0])

    def test_dynamic_alert_name_matching_without_rule_uid(self):
        self.profile.rule_uids = {}
        def mutate(value, url):
            if url.endswith("/rules"):
                value["data"]["groups"][0]["rules"][0]["uid"] = "random-generated-uid"
                value["data"]["groups"][0]["rules"][0]["name"] = "places-5xx-error"
            return value
        self.mutate = mutate
        proof = self.observe(alert_name="places-5xx-error")
        self.assertEqual(proof["samples"], 21)

    def test_full_window_and_redacted_receipt(self):
        proof = self.observe()
        self.assertEqual(proof["samples"], 21)
        self.assertEqual(proof["completed_at"] - proof["started_at"], 600)
        self.assertNotIn("PRIVATE", json.dumps(proof))
        self.assertNotIn("private-token", json.dumps(proof))
        self.assertTrue(all(0 < timeout <= 10 for _, _, timeout in self.calls))

    def test_rule_uncertainty_is_not_recovery(self):
        for field, bad in [
            ("isPaused", True),
            ("health", "nodata"),
            ("health", "error"),
            ("state", "pending"),
            ("state", "firing"),
            ("state", "unknown"),
            ("lastError", "private failure"),
            ("alerts", [{"state": "firing"}]),
            ("uid", "other"),
            ("lastEvaluation", "2000-01-01T00:00:00Z"),
        ]:
            with self.subTest(field=field, value=bad):

                def mutate(value, url, field=field, bad=bad):
                    if url.endswith("/rules"):
                        value["data"]["groups"][0]["rules"][0][field] = bad
                    return value

                self.mutate = mutate
                with self.assertRaises(Denied):
                    self.observe()

    def test_no_data_or_stale_metric_denies(self):
        for rows in [
            [],
            [{"value": [self.now - 121, "2"]}],
            [{"value": [self.now, "NaN"]}],
            [{"value": [self.now, "0"]}],
        ]:

            def mutate(value, url, rows=rows):
                if "/api/v1/query?" in url:
                    value["data"]["result"] = rows
                return value

            self.mutate = mutate
            with self.assertRaises(Denied):
                self.observe()

    def test_new_alert_generation_after_healthy_samples_denies(self):
        options = self.production()
        initial = self.now

        def mutate(value, url):
            if url.endswith("/alerts") and self.now - initial >= 300:
                return [
                    {
                        "fingerprint": "new-generation",
                        "labels": {
                            "environment": "production",
                            "service": "pawlocal-api",
                        },
                    }
                ]
            return value

        self.mutate = mutate
        with self.assertRaisesRegex(Denied, "regressed"):
            self.observe(**options)
        self.assertEqual(self.now - initial, 300)

    def test_development_alert_generation_does_not_fail_recovery(self):
        def mutate(value, url):
            if url.endswith("/alerts"):
                return [
                    {
                        "fingerprint": "dev-nodata",
                        "labels": {
                            "alertname": "pawlocal-development-search-detail-failure",
                            "environment": "development",
                            "service": "pawlocal-api",
                        },
                    }
                ]
            return value

        self.mutate = mutate
        proof = self.observe()
        self.assertEqual(proof["environment"], "development")
        self.assertEqual(proof["samples"], 21)

    def test_cold_start_settles_then_starts_full_stable_window(self):
        initial = self.now

        def mutate(value, url):
            elapsed = self.now - initial
            if url.endswith("/rules") and elapsed < 120:
                value["data"]["groups"][0]["rules"][0]["state"] = "firing"
            if "/api/v1/query?" in url and elapsed < 180:
                value["data"]["result"] = []
            return value

        self.mutate = mutate
        proof = self.observe()
        self.assertEqual(proof["settling_seconds"], 180)
        self.assertEqual(proof["completed_at"] - proof["started_at"], 600)
        self.assertEqual(proof["settling_samples"], 6)

    def test_never_healthy_exhausts_without_extending_deadline(self):
        initial = self.now

        def mutate(value, url):
            if "/api/v1/query?" in url:
                value["data"]["result"] = []
            return value

        self.mutate = mutate
        with self.assertRaisesRegex(Denied, "settling exhausted"):
            self.observe(deadline=initial + 950)
        self.assertLess(self.now, initial + 950)

    def test_live_control_before_every_read_and_final_receipt(self):
        count = 0

        def control():
            nonlocal count
            count += 1
            if len(self.calls) == 2:
                raise Denied("live stop")

        with self.assertRaisesRegex(Denied, "live stop"):
            self.observe(control=control)
        self.assertEqual(len(self.calls), 2)
        self.assertGreaterEqual(count, 3)

    def test_identity_drift_denies(self):
        def mutate(value, url):
            if url.endswith("/health"):
                value["image_digest"] = "sha256:" + "d" * 64
            return value

        self.mutate = mutate
        with self.assertRaisesRegex(Denied, "identity mismatch"):
            self.observe()

    def test_wrong_api_origin_denied_before_network(self):
        with self.assertRaises(Denied):
            self.observe(api_base_url="https://api.example.com/api/v1")
        self.assertEqual(self.calls, [])

    def test_deadline_cannot_extend_window(self):
        with self.assertRaises(Denied):
            self.observe(deadline=self.now + 599)
        self.assertEqual(self.calls, [])

    def test_midwindow_disable_and_live_control(self):
        initial = self.now

        def control():
            if self.now - initial >= 120:
                raise Denied("live stop")

        with self.assertRaisesRegex(Denied, "live stop"):
            self.observe(control=control)
        self.assertEqual(self.now - initial, 120)
        os.environ["PAWLOCAL_ONCALL_ENABLED"] = "false"
        with self.assertRaisesRegex(Denied, "disabled"):
            self.observe()

    def test_production_read_denied_before_network(self):
        with self.assertRaisesRegex(Denied, "revoked"):
            self.observe(
                environment="production",
                frontend_origin="https://pawlocal.example.com",
                api_base_url="https://api.example.com/api/v1",
            )
        self.assertEqual(self.calls, [])

    def test_network_failure_redacted(self):
        def fail(request, timeout):
            raise OSError("PRIVATE_CUSTOMER_SENTINEL")

        with self.assertRaisesRegex(Denied, "^recovery network unavailable$"):
            self.observe(opener=SimpleNamespace(open=fail))

    def test_redirect_and_large_response_denied(self):
        for response in [
            Response(b"x", "https://other.example"),
            Response(
                b"x" * (recovery.MAX_BODY + 1), "https://pawlocal-dev.example.com/"
            ),
        ]:
            with self.assertRaises(Denied):
                self.observe(
                    opener=SimpleNamespace(
                        open=lambda request, timeout, response=response: response
                    )
                )


if __name__ == "__main__":
    unittest.main()
