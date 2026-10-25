"""Historical evidence remains valid while current runtime checks stay strict."""

import copy
import json
import os
from pathlib import Path
import subprocess
import time
import unittest
from unittest.mock import patch

import yaml

import test_incident_admission as fixtures
import admission
import finalize
import promotion
import publisher

ROOT = Path(__file__).resolve().parents[2]


def status(state, when, creator="github-actions[bot]"):
    return {"state": state, "created_at": f"2026-10-01T00:00:{when:02d}Z", "creator": {"login": creator}}


class ReleaseHistory(fixtures.FakeGitHub):
    def __init__(self):
        super().__init__()
        self.historical = self.record
        self.production = copy.deepcopy(self.record)
        self.production.update(id=2, environment="production")
        self.production["payload"]["workflow_run_id"] = 456
        self.current_development = copy.deepcopy(self.record)
        self.current_development.update(id=3, sha="f" * 40, created_at="2026-10-02T00:00:00Z")
        self.current_development["payload"]["release_commit"] = "f" * 40
        self.current_development["payload"]["workflow_run_id"] = 789
        self.current_run = self.run | {"id": 789, "head_sha": "f" * 40}
        self.production_run = self.run | {"id": 456, "path": ".github/workflows/deploy-production.yml", "event": "workflow_dispatch"}
        self.historical_statuses = [status("inactive", 2), status("success", 1)]
        self.current_statuses = [status("success", 3)]
        self.production_statuses = [status("success", 3)]
        # A later failed rerun does not invalidate a genuine prior attempt.
        self.latest_historical_run = self.run | {"run_attempt": 2, "conclusion": "failure"}

    def pages(self, path, maximum=10):
        if path == "/deployments?environment=production":
            return [self.production]
        if path == "/deployments?environment=development":
            return [self.current_development, self.historical]
        if path == "/deployments?environment=development&ref=" + "a" * 40:
            return [self.historical]
        return super().pages(path, maximum)

    def request(self, method, path, data=None):
        if path == "/actions/runs/123/attempts/1":
            return self.run
        if path == "/actions/runs/123":
            return self.latest_historical_run
        if path == "/actions/runs/456":
            return self.production_run
        if path == "/actions/runs/789":
            return self.current_run
        if path.startswith("/deployments/1/statuses"):
            return self.historical_statuses
        if path.startswith("/deployments/2/statuses"):
            return self.production_statuses
        if path.startswith("/deployments/3/statuses"):
            return self.current_statuses
        if path == "/issues/99":
            return {"state": "open", "user": {"login": "github-actions[bot]"}, "body": admission.INCIDENT_PREFIX + "b" * 64 + " -->"}
        return super().request(method, path, data)


@patch.dict(os.environ, {"PAWLOCAL_ONCALL_ENFORCE_GUARDS": "true"})
class HistoricalReleaseTests(unittest.TestCase):
    def test_production_retains_verified_pair_after_development_advances_and_reruns(self):
        for event in ("push", "workflow_dispatch"):
            fake = ReleaseHistory()
            fake.run["event"] = event
            with self.subTest(event=event):
                release = admission.deployed_release(fake, "production")
                self.assertEqual(release["affected_sha"], "a" * 40)
                self.assertEqual(admission.deployed_release(fake, "development")["affected_sha"], "f" * 40)

    def test_current_unknown_failed_inactive_newer_deployments_never_fall_back(self):
        for environment in ("development", "production"):
            for state in ("failure", "error", "inactive", "pending", "in_progress", "queued", "unknown"):
                fake = ReleaseHistory()
                target = fake.current_statuses if environment == "development" else fake.production_statuses
                target.insert(0, status(state, 4))
                with self.subTest(environment=environment, state=state), self.assertRaises(admission.Denied):
                    admission.deployed_release(fake, environment)
        fake = ReleaseHistory()
        fake.current_run["run_attempt"] = 2
        with self.assertRaises(admission.Denied):
            admission.deployed_release(fake, "development")

    def test_historical_failures_unknown_statuses_and_missing_success_deny(self):
        for history in (
            [], [status("inactive", 2)], [status("inactive", 3), status("failure", 2), status("success", 1)],
            [status("error", 2), status("success", 1)], [status("pending", 2), status("success", 1)],
            [status("unknown", 2), status("success", 1)], [status("inactive", 2, "attacker"), status("success", 1)],
            [status("inactive", 2), status("success", 1, "attacker")], [status("success", 1)] * 100, [status("success", 1) | {"created_at": "bad"}],
        ):
            fake = ReleaseHistory()
            fake.historical_statuses = history
            with self.subTest(history=history[:3]), self.assertRaises(admission.Denied):
                admission.deployed_release(fake, "production")

    def test_historical_producer_and_payload_bindings_are_not_relaxed(self):
        for mutation in (
            {"id": 999}, {"status": "in_progress"}, {"conclusion": "failure"}, {"run_attempt": 2},
            {"repository": {"id": 999}}, {"head_repository": {"id": 999}}, {"event": "pull_request"},
            {"path": ".github/workflows/other.yml"}, {"head_branch": "other"}, {"head_sha": "f" * 40},
        ):
            fake = ReleaseHistory()
            fake.run.update(mutation)
            with self.subTest(run=mutation), self.assertRaises(admission.Denied):
                admission.deployed_release(fake, "production")
        for mutation in (
            {"workflow_run_id": 0}, {"workflow_run_attempt": 0}, {"workflow_run_attempt": True},
            {"release_commit": "f" * 40}, {"running_image_digest": "sha256:" + "f" * 64},
            {"evidence_validated": False}, {"verification_evidence_digest": "bad"},
            {"public_endpoint_health": {"frontend": False, "api": True}},
            {"manifest_schema_version": 3, "evidence_schema_version": 1},
            {"manifest_schema_version": []}, {"record_schema_version": True},
        ):
            fake = ReleaseHistory()
            fake.historical["payload"].update(mutation)
            with self.subTest(payload=mutation), self.assertRaises(admission.Denied):
                admission.deployed_release(fake, "production")

    def test_publisher_merge_and_recovery_revalidate_real_production_history(self):
        fake = ReleaseHistory()
        release = admission.deployed_release(fake, "production")
        metadata = release | {"issue": 99, "base_sha": "f" * 40, "deadline": time.time() + 600,
                              "alert": {"environment": "production", "incident_key": "b" * 64, "service": "pawlocal-api"}}
        with (
            patch.dict(os.environ, {"PAWLOCAL_ONCALL_ENABLED": "true", "PAWLOCAL_PRODUCTION_TELEMETRY_READ_APPROVED": "true", "GITHUB_WORKSPACE": str(ROOT)}),
            patch.object(publisher, "LiveControl"), patch.object(publisher, "readiness"),
            patch.object(publisher, "current_alert", return_value=True),
            patch.object(promotion, "LiveControl"), patch.object(promotion, "current_alert", return_value=True),
            patch.object(promotion, "observe", return_value={"proof": True}),
        ):
            publisher.can_publish(fake, metadata)
            promotion.check_incident(fake, metadata)
            self.assertEqual(promotion.recover(fake, "production", release, None, metadata, lambda: None), {"proof": True})
            fake.production_statuses.insert(0, status("failure", 5))
            for check in (lambda: publisher.can_publish(fake, metadata), lambda: promotion.check_incident(fake, metadata),
                          lambda: promotion.recover(fake, "production", release, None, metadata, lambda: None)):
                with self.assertRaises(admission.Denied):
                    check()

    def test_finalizer_uses_current_production_with_durable_development_history(self):
        fake = ReleaseHistory()
        release = admission.deployed_release(fake, "production")
        common = {"merged_sha": "a" * 40, "merge_sha256": "c" * 64, "release": release}
        development = common | {"recovery": {"completed_at": 10}}
        production = common | {"development_sha256": "d" * 64, "recovery": {"started_at": 11}}
        with (
            patch.dict(os.environ, {"MERGE_SHA256": "c" * 64, "DEVELOPMENT_SHA256": "d" * 64}),
            patch.object(finalize.receipts, "read", side_effect=lambda phase, *_: development if phase == "development" else production),
            patch.object(finalize.receipts, "validate_recovery"),
            patch.object(finalize, "verified_merge", return_value="a" * 40),
        ):
            self.assertEqual(finalize.complete(fake, {}, None, {}), ("a" * 40, 456))
            fake.production_statuses.insert(0, status("inactive", 5))
            with self.assertRaises(admission.Denied):
                finalize.complete(fake, {}, None, {})


@patch.dict(os.environ, {"PAWLOCAL_ONCALL_ENFORCE_GUARDS": "true"})
class ProductionEligibilityTests(unittest.TestCase):
    def fixture(self):
        fake = ReleaseHistory()
        return {"deployment": fake.historical, "producer": fake.run | {"workflow_id": 17}, "statuses": fake.historical_statuses}

    def execute(self, fixture):
        workflow = yaml.safe_load((ROOT / ".github/workflows/terraform-environment.yml").read_text())
        script = workflow["jobs"]["production-eligibility"]["steps"][0]["with"]["script"]
        harness = r"""
const fixture = JSON.parse(process.argv[1]);
const context = {repo:{owner:'alanlima',repo:'pawlocal'},payload:{repository:{id:1423024931}}};
const github = {rest:{repos:{
 compareCommitsWithBasehead:async()=>({data:{status:'ahead'}}),
 listDeployments:'deployments',listDeploymentStatuses:async()=>({data:fixture.statuses})
},actions:{getWorkflow:async()=>({data:{id:17}}),getWorkflowRunAttempt:async args=>{
 if(args.run_id!==fixture.deployment.payload.workflow_run_id||args.attempt_number!==fixture.deployment.payload.workflow_run_attempt) throw Error('wrong requested attempt');
 return {data:fixture.producer};
}}},paginate:async()=>[...(fixture.invalid_deployments || []), fixture.deployment]};
(async()=>{SCRIPT;console.log('accepted')})().catch(e=>{console.error(e.message);process.exitCode=1});
""".replace("SCRIPT", script)
        return subprocess.run(["node", "-e", harness, json.dumps(fixture)], capture_output=True, text=True,
                              env=os.environ | {"RELEASE_COMMIT": "a" * 40, "BACKEND_IMAGE": "ghcr.io/alanlima/pawlocal-api@sha256:" + "b" * 64}, check=False)

    def test_actual_gate_accepts_retired_success_from_push_and_manual_producer(self):
        for event in ("push", "workflow_dispatch"):
            for statuses in ([status("success", 1)], [status("inactive", 2), status("success", 1)]):
                fixture = self.fixture()
                fixture["producer"]["event"] = event
                fixture["statuses"] = statuses
                result = self.execute(fixture)
                with self.subTest(event=event, statuses=statuses):
                    self.assertEqual(result.returncode, 0, result.stderr)

    def test_actual_gate_skips_malformed_payload_before_valid_history(self):
        fixture = self.fixture()
        fixture["invalid_deployments"] = [
            fixture["deployment"] | {"payload": value}
            for value in ("null", "[]", "1", "true", "broken-json", None, [], 1)
        ]
        result = self.execute(fixture)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_actual_gate_rejects_untrusted_failed_and_mismatched_history(self):
        mutations = [
            ("producer", {"id": 999}), ("producer", {"workflow_id": 99}),
            ("producer", {"status": "in_progress"}), ("producer", {"conclusion": "failure"}),
            ("producer", {"run_attempt": 2}), ("producer", {"event": "pull_request"}),
            ("producer", {"head_sha": "f" * 40}), ("producer", {"head_branch": "other"}),
            ("producer", {"repository": {"id": 99}}), ("producer", {"head_repository": {"id": 99}}),
            ("producer", {"path": ".github/workflows/other.yml"}),
            ("deployment", {"sha": "f" * 40}), ("deployment", {"environment": "production"}),
            ("deployment", {"creator": {"login": "attacker"}}), ("deployment", {"repository_url": "https://example.test"}),
            ("payload", {"workflow_run_attempt": 0}), ("payload", {"evidence_validated": False}),
            ("payload", {"release_commit": "f" * 40}), ("payload", {"backend_image_digest": "sha256:" + "f" * 64}),
            ("payload", {"verification_evidence_digest": "bad"}),
            ("payload", {"public_endpoint_health": {"frontend": False, "api": True}}),
            ("payload", {"manifest_schema_version": 3, "evidence_schema_version": 1}),
        ]
        for part, mutation in mutations:
            fixture = self.fixture()
            target = fixture["deployment"]["payload"] if part == "payload" else fixture[part]
            target.update(mutation)
            with self.subTest(part=part, mutation=mutation):
                self.assertNotEqual(self.execute(fixture).returncode, 0)
        for statuses in ([], [status("inactive", 2)], [status("inactive", 3), status("failure", 2), status("success", 1)],
                         [status("unknown", 2), status("success", 1)], [status("inactive", 2, "attacker"), status("success", 1)],
                         [status("success", 1)] * 100, [status("success", 1) | {"created_at": "bad"}]):
            fixture = self.fixture()
            fixture["statuses"] = statuses
            with self.subTest(statuses=statuses[:3]):
                self.assertNotEqual(self.execute(fixture).returncode, 0)


if __name__ == "__main__":
    unittest.main()
