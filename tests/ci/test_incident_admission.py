import copy
import hashlib
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

DIRECTORY = Path(__file__).resolve().parents[2] / "ops/incident-response"
sys.path.insert(0, str(DIRECTORY))
import admission
import test_incident_quota as quota_fixtures


def alert():
    value = {
        "environment": "development",
        "fingerprint": "a" * 16,
        "starts_at": "2026-10-01T00:00:00.000Z",
        "ends_at": "0001-01-01T00:00:00.000Z",
        "status": "firing",
        "service": "pawlocal-api",
        "alert_name": "pawlocal-development-search-detail-failure",
    }
    value["incident_key"] = hashlib.sha256(
        json.dumps(
            [value["environment"], value["fingerprint"], value["starts_at"]],
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    return value


def deployment():
    sha, digest = "a" * 40, "sha256:" + "b" * 64
    payload = {
        "record_schema_version": 1,
        "manifest_schema_version": 2,
        "evidence_schema_version": 1,
        "evidence_validated": True,
        "release_commit": sha,
        "backend_image": "ghcr.io/alanlima/pawlocal-api@" + digest,
        "backend_image_digest": digest,
        "running_image_digest": digest,
        "workflow_run_id": 123,
        "workflow_run_attempt": 1,
        "release_manifest_digest": "sha256:" + "c" * 64,
        "verification_evidence_digest": "sha256:" + "d" * 64,
        "frontend_artifact_digest": "sha256:" + "e" * 64,
        "database_provider": "aurora_dsql",
        "migration_runner": "dsql_baseline",
        "migration_id": "dsql_0001_initial",
        "telemetry_enabled": True,
        "public_endpoint_health": {"frontend": True, "api": True},
        "database_query_smoke": {
            "route": "/api/v1/places",
            "result": "valid_place_page",
        },
    }
    return {
        "id": 1,
        "sha": sha,
        "payload": payload,
        "repository_url": admission.GITHUB,
        "creator": {"login": "github-actions[bot]"},
        "created_at": "2026-10-01T00:00:00Z",
    }


class FakeGitHub:
    deadline = int(time.time()) + 1200

    def __init__(self, *_args):
        self.calls = []
        self.existing = []
        self.record = deployment()
        self.run = {
            "repository": {"id": 1423024931},
            "head_repository": {"id": 1423024931},
            "conclusion": "success",
            "event": "push",
            "path": ".github/workflows/fullstack-release.yml",
            "head_branch": "main",
            "head_sha": "a" * 40,
            "run_attempt": 1,
        }
        self.status = [
            {
                "state": "success",
                "creator": {"login": "github-actions[bot]"},
                "created_at": "2026-10-01T00:00:01Z",
            }
        ]

    def request(self, method, path, data=None):
        self.calls.append((method, path, data))
        if method == "PATCH" and path == "/issues/789":
            return {"number": 789, "state": "closed"}
        if method == "POST" and path == "/issues":
            return {"number": 789, "user": {"login": "github-actions[bot]"}}
        if method == "POST" and path.endswith("/comments"):
            return {
                "id": 321,
                "body": data["body"],
                "user": {"login": "github-actions[bot]"},
            }
        if path == "/issues/456":
            return {
                "state": "closed" if getattr(self, "ledger_closed", False) else "open",
                "body": admission.LEDGER_MARKER,
                "user": {"login": "alanlima"},
            }
        if path == "/actions/runs/123":
            return self.run
        if path.startswith("/deployments/1/statuses"):
            return self.status
        if path == "/git/ref/heads/main":
            return {"object": {"sha": "f" * 40}}
        raise AssertionError((method, path))

    def pages(self, path, maximum=10):
        if path.startswith("/issues?state=all"):
            return self.existing
        if path == "/issues/456/comments":
            return []
        if path.startswith("/deployments?environment=development"):
            return [self.record]
        raise AssertionError(path)


class AdmissionTests(unittest.TestCase):
    def test_every_effective_ruleset_is_checked_before_admission(self):
        rule = {
            "enforcement": "active",
            "target": "branch",
            "bypass_actors": [],
            "conditions": {"ref_name": {"include": ["~ALL"], "exclude": []}},
            "rules": [
                {"type": "deletion"},
                {"type": "non_fast_forward"},
                {
                    "type": "pull_request",
                    "parameters": {
                        "required_approving_review_count": 0,
                        "require_code_owner_review": False,
                        "required_review_thread_resolution": True,
                        "allowed_merge_methods": ["squash"],
                    },
                },
                {
                    "type": "required_status_checks",
                    "parameters": {
                        "strict_required_status_checks_policy": True,
                        "required_status_checks": [
                            {"context": name}
                            | (
                                {"integration_id": 42}
                                if name == "PawLocal change authorization"
                                else {}
                            )
                            for name in (
                                "Backend checks / Backend checks",
                                "Frontend checks and HTTP-mode build / frontend",
                                "PawLocal change authorization",
                            )
                        ],
                    },
                },
            ],
        }

        class Rules:
            deadline = int(time.time()) + 600

            def __init__(self, rows):
                self.rows = rows

            def request(self, _method, path):
                if path == "/rulesets?per_page=100":
                    return [{"id": index + 1} for index in range(len(self.rows))]
                return self.rows[int(path.rsplit("/", 1)[1]) - 1]

        with (
            patch.dict(os.environ, {"PAWLOCAL_AUTHORIZER_APP_ID": "42"}),
            patch.object(admission, "runtime_ready") as environments,
            patch.object(admission, "classic_absent"),
        ):
            admission.readiness(Rules([rule]))
            environments.assert_called_once()
        human = copy.deepcopy(rule)
        human["conditions"]["ref_name"]["include"] = ["refs/heads/m*"]
        human["rules"][2]["parameters"]["required_approving_review_count"] = 1
        unknown = copy.deepcopy(rule)
        unknown["rules"].append({"type": "required_deployments", "parameters": {}})
        for second in (human, unknown):
            with (
                self.subTest(second=second),
                patch.dict(os.environ, {"PAWLOCAL_AUTHORIZER_APP_ID": "42"}),
                patch.object(admission, "runtime_ready") as environments,
                self.assertRaises(admission.Denied),
            ):
                admission.readiness(Rules([rule, second]))
            environments.assert_not_called()
        for issuer in (None, 15368, "42", True):
            bad = copy.deepcopy(rule)
            bad["rules"][3]["parameters"]["required_status_checks"][-1][
                "integration_id"
            ] = issuer
            with (
                self.subTest(issuer=issuer),
                patch.dict(os.environ, {"PAWLOCAL_AUTHORIZER_APP_ID": "42"}),
                patch.object(admission, "runtime_ready") as environments,
                self.assertRaises(admission.Denied),
            ):
                admission.readiness(Rules([bad]))
            environments.assert_not_called()

    def test_readiness_uses_oncall_readiness_token_when_present(self):
        rule = {
            "enforcement": "active",
            "target": "branch",
            "bypass_actors": [],
            "conditions": {"ref_name": {"include": ["~ALL"], "exclude": []}},
            "rules": [
                {"type": "deletion"},
                {"type": "non_fast_forward"},
                {
                    "type": "pull_request",
                    "parameters": {
                        "required_approving_review_count": 0,
                        "require_code_owner_review": False,
                        "required_review_thread_resolution": True,
                        "allowed_merge_methods": ["squash"],
                    },
                },
                {
                    "type": "required_status_checks",
                    "parameters": {
                        "strict_required_status_checks_policy": True,
                        "required_status_checks": [
                            {"context": name}
                            | (
                                {"integration_id": 42}
                                if name == "PawLocal change authorization"
                                else {}
                            )
                            for name in (
                                "Backend checks / Backend checks",
                                "Frontend checks and HTTP-mode build / frontend",
                                "PawLocal change authorization",
                            )
                        ],
                    },
                },
            ],
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            token_file = Path(temp_dir) / "oncall-readiness-token.json"
            token_file.write_text(json.dumps({"token": "capability-admin-token"}))
            class RecordingClient:
                deadline = int(time.time()) + 600
                opener = None
                def __init__(self, token, deadline=None, opener=None):
                    self.token = token
                    self.deadline = deadline or int(time.time()) + 600
                    self.opener = opener
                def request(self, _method, path):
                    if path == "/rulesets?per_page=100":
                        return [{"id": 1}]
                    return rule
            with (
                patch.dict(os.environ, {"PAWLOCAL_AUTHORIZER_APP_ID": "42", "RUNNER_TEMP": temp_dir}),
                patch.object(admission, "GitHub", side_effect=RecordingClient) as client_mock,
                patch.object(admission, "runtime_ready"),
                patch.object(admission, "classic_absent"),
            ):
                initial_client = RecordingClient("initial-unprivileged-token")
                admission.readiness(initial_client)
                client_mock.assert_called_with("capability-admin-token", initial_client.deadline, initial_client.opener)

    def test_grouped_schema_rejects_private_extra_generation_and_wrong_environment(
        self,
    ):
        self.assertEqual(
            admission.alerts(json.dumps([alert()]), "development"), [alert()]
        )
        for changed in (
            {"annotations": "CUSTOMER_SENTINEL"},
            {"incident_key": "c" * 64},
            {"environment": "production"},
            {"ends_at": "private"},
            {"status": "resolved"},
        ):
            with self.subTest(changed=changed), self.assertRaises(admission.Denied):
                admission.alerts(json.dumps([alert() | changed]), "development")
        with self.assertRaises(admission.Denied):
            admission.alerts(json.dumps([alert(), alert()]), "development")

    def run_preflight(self, fake, current=True, reserve_error=False):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "output"
            output.touch()
            profile = quota_fixtures.QuotaTests().profile()
            env = {
                "INCIDENT_DEADLINE": str(int(time.time()) + 1200),
                "GITHUB_REPOSITORY": "alanlima/pawlocal",
                "GITHUB_REF": "refs/heads/main",
                "GITHUB_EVENT_NAME": "workflow_dispatch",
                "GITHUB_RUN_ATTEMPT": "1",
                "GITHUB_RUN_ID": "777",
                "GITHUB_ACTOR": "fixture-dispatch[bot]",
                "PAWLOCAL_DISPATCH_ACTOR": "fixture-dispatch[bot]",
                "PAWLOCAL_ONCALL_ENABLED": "true",
                "SCHEMA_VERSION": "1",
                "PAWLOCAL_MODEL_PROFILE": json.dumps(profile.__dict__),
                "INCIDENT_ENVIRONMENT": "development",
                "ALERTS_JSON": json.dumps([alert()]),
                "GH_TOKEN": "fixture",
                "GRAFANA_STACK_URL": "https://fixture.grafana.net",
                "PAWLOCAL_GRAFANA_QUERY_TOKEN": "fixture",
                "GITHUB_WORKSPACE": directory,
                "PAWLOCAL_QUOTA_ISSUE": "456",
                "RUNNER_TEMP": directory,
                "GITHUB_OUTPUT": str(output),
            }
            with (
                patch.dict(os.environ, env, clear=True),
                patch.object(admission, "GitHub", return_value=fake),
                patch.object(admission, "readiness"),
                patch.object(admission, "bindings_ready"),
                patch.object(admission, "arm"),
                patch.object(admission, "current_alert", return_value=current),
                patch.object(
                    admission,
                    "gather",
                    return_value={"signals": {"metrics": {}, "logs": {}, "traces": {}}},
                ),
            ):
                if reserve_error:
                    with (
                        patch.object(
                            admission,
                            "reserve_month",
                            side_effect=admission.Denied("fixture unknown reservation"),
                        ),
                        self.assertRaises(admission.Denied),
                    ):
                        admission.main()
                else:
                    admission.main()
            metadata_path = Path(directory) / "oncall-admission/admission.json"
            return output.read_text(), json.loads(
                metadata_path.read_text()
            ) if metadata_path.exists() else None

    def test_claim_precedes_monthly_reservation_and_model_metadata(self):
        fake = FakeGitHub()
        output, metadata = self.run_preflight(fake)
        writes = [(path, data) for method, path, data in fake.calls if method == "POST"]
        self.assertEqual(writes[0][0], "/issues")
        self.assertIn("ADMISSION_PENDING", writes[0][1]["body"])
        self.assertTrue(writes[1][1]["body"].startswith(admission.ENTRY_MARKER))
        self.assertIn("admitted=true", output)
        self.assertEqual(metadata["affected_sha"], "a" * 40)
        self.assertEqual(metadata["base_sha"], "f" * 40)
        self.assertEqual(metadata["reservation"]["run_id"], "777")

    def test_live_global_stop_prevents_even_initial_claim_mutation(self):
        fake = FakeGitHub()
        fake.ledger_closed = True
        with self.assertRaises(admission.Denied):
            self.run_preflight(fake)
        self.assertFalse(any(method != "GET" for method, _, _ in fake.calls))

    def test_closed_generation_and_late_firing_after_resolution_do_not_reserve(self):
        fake = FakeGitHub()
        fake.existing = [
            {
                "body": admission.INCIDENT_PREFIX + alert()["incident_key"] + " -->",
                "state": "closed",
                "user": {"login": "github-actions[bot]"},
            }
        ]
        output, metadata = self.run_preflight(fake)
        self.assertIn("admitted=false", output)
        self.assertIsNone(metadata)
        self.assertFalse(any(method == "POST" for method, _, _ in fake.calls))
        fake = FakeGitHub()
        output, _ = self.run_preflight(fake, current=False)
        self.assertIn("admitted=false", output)
        self.assertFalse(
            any(
                data and data.get("body", "").startswith(admission.ENTRY_MARKER)
                for _, _, data in fake.calls
            )
        )

    def test_postclaim_uncertain_reservation_records_escalation_and_no_admission(self):
        fake = FakeGitHub()
        output, metadata = self.run_preflight(fake, reserve_error=True)
        self.assertNotIn("admitted=true", output)
        self.assertIsNone(metadata)
        self.assertTrue(
            any(
                "ESCALATED" in (data or {}).get("body", "") for _, _, data in fake.calls
            )
        )

    def test_untrusted_release_producer_or_latest_failed_deployment_denies(self):
        for mutation in (
            {"head_sha": "b" * 40},
            {"run_attempt": 2},
            {"repository": {"id": 99}},
            {"event": "pull_request"},
        ):
            fake = FakeGitHub()
            fake.run.update(mutation)
            with self.subTest(mutation=mutation), self.assertRaises(admission.Denied):
                admission.deployed_release(fake, "development")
        fake = FakeGitHub()
        fake.status[0]["state"] = "failure"
        with self.assertRaises(admission.Denied):
            admission.deployed_release(fake, "development")
        for field in (
            "evidence_validated",
            "running_image_digest",
            "release_commit",
            "telemetry_enabled",
        ):
            fake = FakeGitHub()
            del fake.record["payload"][field]
            with self.subTest(field=field), self.assertRaises(admission.Denied):
                admission.deployed_release(fake, "development")

        # Verify schema version 3 with frontend telemetry passes
        fake = FakeGitHub()
        fake.record["payload"]["manifest_schema_version"] = 3
        fake.record["payload"]["evidence_schema_version"] = 2
        fake.record["payload"]["frontend_telemetry_enabled"] = True
        self.assertIsNotNone(admission.deployed_release(fake, "development"))

        # Incompatible schema versions or invalid frontend_telemetry_enabled deny
        for invalid_mutation in (
            {"manifest_schema_version": 3, "evidence_schema_version": 1},
            {"manifest_schema_version": 2, "evidence_schema_version": 2},
            {"manifest_schema_version": 4, "evidence_schema_version": 3},
            {"manifest_schema_version": 3, "evidence_schema_version": 2, "frontend_telemetry_enabled": "true"},
            {"manifest_schema_version": 3, "evidence_schema_version": 2},  # missing frontend_telemetry_enabled
        ):
            fake = FakeGitHub()
            fake.record["payload"].update(invalid_mutation)
            if "frontend_telemetry_enabled" not in invalid_mutation and "frontend_telemetry_enabled" in fake.record["payload"]:
                del fake.record["payload"]["frontend_telemetry_enabled"]
            with self.subTest(invalid_mutation=invalid_mutation), self.assertRaises(admission.Denied):
                admission.deployed_release(fake, "development")


if __name__ == "__main__":
    unittest.main()
