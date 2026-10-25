import copy
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import experience as e
from test_provision import FakeAPI, configured


def enabled():
    return {
        "version": 1,
        "enabled": True,
        "active": False,
        "usage_datasource_uid": "usage",
        "synthetic_api_url": "https://synthetic-monitoring-api-au-southeast-0.grafana.net",
        "probe_id": 123,
        "api_base_url": "https://api-dev.test.org/api/v1",
        "webhook_url": "https://abcdefgh.lambda-url.ap-southeast-2.on.aws/",
        "operator_receiver": "reviewed-operator",
        "approval": "issue-226-live-owner-reference",
        "responder_routing": True,
        "responder_approval": "reviewed-g1-and-receiver",
    }


class API(FakeAPI):
    def __init__(self):
        super().__init__()
        self.folder = {"uid": e.FOLDER, "title": "PawLocal development"}
        self.dashboards = {}
        self.checks = []
        self.group = None
        self.contacts = []
        self.request_headers = []
        self.policy = {
            "receiver": "reviewed-operator",
            "group_by": ["grafana_folder", "alertname"],
            "routes": [
                {"receiver": "unrelated", "object_matchers": [["team", "=", "other"]]}
            ],
        }

    def request(
        self,
        method,
        url,
        token,
        payload=None,
        stack_id=None,
        missing=False,
        extra_headers=None,
    ):
        self.request_headers.append((method, url, copy.deepcopy(extra_headers)))
        self.calls.append((method, url, token, payload, stack_id))
        if url.endswith("/api/org"):
            return {"id": 1}
        if "/api/dashboards/uid/" in url:
            return copy.deepcopy(self.dashboards.get(url.rsplit("/", 1)[1]))
        if url.endswith("/api/dashboards/db"):
            item = copy.deepcopy(payload["dashboard"])
            old = self.dashboards.get(item["uid"])
            item["id"] = item.get("id") or len(self.dashboards) + 1
            item["version"] = (old["dashboard"]["version"] if old else 0) + 1
            self.dashboards[item["uid"]] = {
                "dashboard": item,
                "meta": {"folderUid": e.FOLDER},
            }
            return {"uid": item["uid"]}
        if url.endswith("/api/datasources/uid/usage"):
            return {"uid": "usage", "name": "grafanacloud-usage", "type": "prometheus"}
        if url.endswith("/tenant"):
            return {
                "id": 42,
                "stackId": 42,
                "status": 0,
                "metricsRemote": {"password": "never-serialize-private-tenant-data"},
            }
        if url.endswith("/probe/list"):
            return [{"id": 123, "public": True, "online": True}]
        if url.endswith("/check/list"):
            return copy.deepcopy(self.checks)
        if url.endswith(("/check/add", "/check/update")):
            item = {**copy.deepcopy(payload), "id": 55, "tenantId": 42}
            self.checks = [item]
            return item
        if url.endswith("/check/55"):
            return copy.deepcopy(self.checks[0])
        if "/rule-groups/" in url:
            if method == "GET":
                return copy.deepcopy(self.group)
            self.group = copy.deepcopy(payload)
            return self.group
        if "/contact-points" in url:
            if method == "GET":
                return copy.deepcopy(self.contacts)
            item = copy.deepcopy(payload)
            item["settings"]["hmacConfig"].pop("secret")
            self.contacts = [item]
            return item
        if url.endswith("/provisioning/policies"):
            if method == "GET":
                return copy.deepcopy(self.policy)
            self.policy = copy.deepcopy(payload)
            return self.policy
        self.calls.pop()
        return super().request(method, url, token, payload, stack_id, missing)


class ExperienceTests(unittest.TestCase):
    def setUp(self):
        self.api = API()
        self.config = enabled()
        self.binding = configured()
        self.secrets = {
            "GRAFANA_CLOUD_ACCESS_POLICY_TOKEN": "private-cloud",
            "GRAFANA_SERVICE_ACCOUNT_TOKEN": "private-sa",
            "GRAFANA_FARO_ACCESS_POLICY_TOKEN": "private-faro",
            "GRAFANA_SYNTHETIC_MONITORING_TOKEN": "private-sm",
            "PAWLOCAL_GRAFANA_WEBHOOK_HMAC": "sensitive-hmac-" * 4,
        }
        self.runner = e.Experience(self.api, self.secrets)

    def test_disabled_is_no_network_even_without_credentials(self):
        config = e.configuration(ROOT / "experience.json")
        self.assertEqual(
            e.Experience(self.api, {}).reconcile_experience(config, None, apply=True)[
                "status"
            ],
            "disabled",
        )
        self.assertEqual(self.api.calls, [])

    def test_six_templates_regenerate_exactly_and_bind_only_actual_datasource_uids(
        self,
    ):
        self.assertEqual(
            set(e.build()),
            {
                "journey",
                "application",
                "dependencies",
                "releases",
                "telemetry",
                "incidents",
            },
        )
        for name, template in e.build().items():
            self.assertEqual(
                json.loads((ROOT / "dashboards" / f"{name}.json").read_text()), template
            )
        bound = e.dashboards(self.binding, "usage")
        self.assertEqual(len({item["uid"] for item in bound}), 6)
        self.assertNotIn("__METRICS_UID__", json.dumps(bound))
        for dashboard in bound:
            self.assertEqual(
                [var["name"] for var in dashboard["templating"]["list"]],
                ["environment", "service", "release"]
                + (["traceId"] if dashboard["uid"] == "pawlocal-incidents" else []),
            )
            for panel in dashboard["panels"]:
                self.assertEqual(
                    panel["fieldConfig"]["defaults"]["noValue"], "NO DATA / UNKNOWN"
                )
                for target in panel["targets"]:
                    self.assertNotIn("or vector(0)", target.get("expr", ""))
                    self.assertNotIn("place_id=", target.get("expr", ""))

    def test_trace_search_table_and_single_trace_waterfall_have_matching_contracts(
        self,
    ):
        template = (
            ROOT.parents[2]
            / "infra/terraform/modules/pawlocal-environment/dashboards/incidents.json.tftpl"
        ).read_text()
        for key, value in {
            "environment": "production",
            "title(environment)": "Production",
            "metrics_uid": "metrics",
            "logs_uid": "logs",
            "traces_uid": "traces",
        }.items():
            template = template.replace("${" + key + "}", value)
        for dashboard in (e.build()["incidents"], json.loads(template)):
            panels = {panel["title"]: panel for panel in dashboard["panels"]}
            self.assertEqual(panels["Related traces"]["type"], "table")
            self.assertIn(
                "resource.deployment.environment.name",
                panels["Related traces"]["targets"][0]["query"],
            )
            self.assertEqual(panels["Selected trace waterfall"]["type"], "traces")
            self.assertEqual(
                panels["Selected trace waterfall"]["targets"][0]["query"], "$traceId"
            )
            variable = next(
                var
                for var in dashboard["templating"]["list"]
                if var["name"] == "traceId"
            )
            self.assertEqual(variable["type"], "textbox")
            self.assertEqual(variable["current"]["value"], "")

    def test_script_encodes_only_public_target_and_bounded_route_tags(self):
        check = e.synthetic(self.config)
        import base64

        script = base64.b64decode(check["settings"]["scripted"]["script"]).decode()
        self.assertIn("/places?page_size=1", script)
        self.assertIn("name: '/api/v1/places/{place_id}'", script)
        self.assertIn("systemTags: ['status', 'method', 'name', 'check']", script)
        self.assertNotIn("console.", script)
        self.assertNotIn("Authorization", script)
        self.assertEqual(check["frequency"], 300000)
        self.assertEqual(check["probes"], [123])
        self.assertFalse(check["enabled"])

    def test_alert_unknown_states_and_signed_resolved_notifications(self):
        rule = e.alert_rule("metrics")
        self.assertEqual(rule["noDataState"], "NoData")
        self.assertEqual(rule["execErrState"], "Error")
        self.assertEqual(rule["for"], "5m")
        self.assertEqual(rule["keep_firing_for"], "2m")
        self.assertTrue(rule["isPaused"])
        self.assertEqual(rule["title"], "pawlocal-development-search-detail-failure")
        contact = e.contact_point(self.config["webhook_url"], "secret")
        self.assertFalse(contact["disableResolveMessage"])
        self.assertEqual(contact["settings"]["maxAlerts"], 20)
        self.assertEqual(
            contact["settings"]["hmacConfig"]["timestampHeader"],
            "X-Grafana-Alerting-Timestamp",
        )

    def test_plan_readonly_and_import_is_idempotent_except_opaque_secret_write(self):
        result = self.runner.reconcile_experience(self.config, self.binding)
        self.assertEqual(self.api.writes, [])
        unrelated = copy.deepcopy(self.api.policy["routes"][0])
        result = self.runner.reconcile_experience(self.config, self.binding, apply=True)
        self.assertEqual(len(self.api.dashboards), 6)
        self.assertEqual(self.api.policy["routes"][1], unrelated)
        self.assertEqual(result["raw_executions_per_30_days"], 8640)
        for secret in self.secrets.values():
            self.assertNotIn(secret, json.dumps(result))
        self.api.calls.clear()
        result = self.runner.reconcile_experience(self.config, self.binding, apply=True)
        self.assertEqual(result["operations"], ["contact-point:runtime-secret-write"])
        self.assertEqual([call[0] for call in self.api.writes], ["PUT"])
        self.assertNotIn("DELETE", [call[0] for call in self.api.calls])

    def test_shared_policy_put_preserves_operator_ui_and_unrelated_tree(self):
        original = copy.deepcopy(self.api.policy)
        original["routes"][0]["routes"] = [
            {"receiver": "nested-owner", "group_wait": "1m"}
        ]
        self.api.policy = copy.deepcopy(original)
        self.runner.reconcile_experience(self.config, self.binding, apply=True)
        self.assertEqual(self.api.policy["receiver"], original["receiver"])
        self.assertEqual(self.api.policy["group_by"], original["group_by"])
        self.assertEqual(self.api.policy["routes"][1:], original["routes"])
        with_headers = [
            call for call in self.api.request_headers if call[2] is not None
        ]
        self.assertEqual(
            with_headers,
            [
                (
                    "PUT",
                    self.binding["stack"]["url"] + "/api/v1/provisioning/policies",
                    {"X-Disable-Provenance": "true"},
                )
            ],
        )
        self.config["responder_routing"] = False
        self.api.request_headers.clear()
        self.runner.reconcile_experience(self.config, self.binding, apply=True)
        self.assertEqual(self.api.policy, original)
        self.assertEqual(
            [call[2] for call in self.api.request_headers if call[0] == "PUT"],
            [{"X-Disable-Provenance": "true"}],
        )

    def test_foreign_dashboard_or_rule_collision_blocks_all_writes(self):
        self.api.dashboards["pawlocal-journey"] = {
            "dashboard": {"tags": [], "uid": "pawlocal-journey"},
            "meta": {"folderUid": e.FOLDER},
        }
        with self.assertRaises(e.ProvisionError):
            self.runner.reconcile_experience(self.config, self.binding, apply=True)
        self.assertEqual(self.api.writes, [])
        self.api.dashboards.clear()
        self.api.group = {"rules": [{"uid": "foreign", "labels": {}}]}
        with self.assertRaises(e.ProvisionError):
            self.runner.reconcile_experience(self.config, self.binding, apply=True)
        self.assertEqual(self.api.writes, [])

    def test_g1_monitoring_does_not_require_receiver_or_hmac_and_has_no_webhook_route(
        self,
    ):
        self.config["responder_routing"] = False
        self.config["webhook_url"] = None
        self.config["responder_approval"] = None
        self.secrets.pop("PAWLOCAL_GRAFANA_WEBHOOK_HMAC")
        self.runner.reconcile_experience(self.config, self.binding, apply=True)
        self.assertEqual(self.api.contacts, [])
        self.assertEqual(len(self.api.policy["routes"]), 1)
        self.assertEqual(len(self.api.dashboards), 6)

    def test_production_or_foreign_api_origin_rejected_before_any_network(self):
        for api in (
            "https://api.test.org/api/v1",
            "https://api-dev.foreign.org/api/v1",
        ):
            with self.subTest(api=api):
                self.config["api_base_url"] = api
                self.api.calls.clear()
                with self.assertRaises(e.ProvisionError):
                    self.runner.reconcile_experience(
                        self.config, self.binding, apply=True
                    )
                self.assertEqual(self.api.calls, [])
        self.config["api_base_url"] = "https://api-dev.test.org/api/v1"
        self.binding["frontend_origin"] = "https://pawlocal.test.org"
        with self.assertRaises(e.ProvisionError):
            self.runner.reconcile_experience(self.config, self.binding, apply=True)
        self.assertEqual(self.api.calls, [])

    def test_unknown_operator_route_and_missing_hmac_block_writes(self):
        self.config["operator_receiver"] = "guessed"
        with self.assertRaises(e.ProvisionError):
            self.runner.reconcile_experience(self.config, self.binding, apply=True)
        self.assertEqual(self.api.writes, [])
        self.config["operator_receiver"] = "reviewed-operator"
        self.secrets.pop("PAWLOCAL_GRAFANA_WEBHOOK_HMAC")
        with self.assertRaises(e.ProvisionError):
            self.runner.reconcile_experience(self.config, self.binding, apply=True)
        self.assertEqual(self.api.writes, [])


if __name__ == "__main__":
    unittest.main()
