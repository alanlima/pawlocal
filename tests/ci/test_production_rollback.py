"""Exercise rollback history selection and the actual workflow contracts."""

import copy
import importlib.util
import os
from pathlib import Path
import unittest
from unittest.mock import patch

import yaml
import test_incident_admission as fixtures
from test_historical_release_verification import status

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("rollback", ROOT / "ops/rollback-production.py")
rollback = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rollback)


class History(fixtures.FakeGitHub):
    def __init__(self):
        super().__init__()
        self.records = []
        self.runs = {}
        self.statuses = {}
        # Newest is current; duplicate pair is not a distinct rollback release.
        self.add(10, "c", "d", 10)
        self.add(9, "c", "d", 9)
        self.add(8, "a", "b", 8)
        self.add(7, "e", "f", 7)
        self.development_missing = False
        self.development_telemetry = {}

    def add(self, identity, sha, digest, second):
        production = copy.deepcopy(fixtures.deployment())
        production.update(id=identity, environment="production", sha=sha * 40,
                          created_at=f"2026-10-01T00:00:{second:02d}Z")
        production["payload"].update(release_commit=sha * 40, workflow_run_id=identity,
            backend_image_digest="sha256:" + digest * 64, running_image_digest="sha256:" + digest * 64,
            backend_image="ghcr.io/alanlima/pawlocal-api@sha256:" + digest * 64)
        self.records.append(production)
        self.runs[identity] = self.run | {"id": identity, "event": "workflow_dispatch",
                                        "path": ".github/workflows/deploy-production.yml"}
        self.statuses[identity] = [status("success", second)] if identity == 10 else [status("inactive", 20), status("success", second)]

    def pages(self, path, maximum=10):
        if path == "/deployments?environment=production":
            return copy.deepcopy(self.records)
        if path.startswith("/deployments?environment=development&ref="):
            if self.development_missing:
                return []
            sha = path.rsplit("=", 1)[1]
            record = next(r for r in self.records if r.get("sha") == sha)
            dev = copy.deepcopy(record)
            dev.update(environment="development", id=record["id"] + 100)
            dev["payload"]["workflow_run_id"] += 100
            if record["id"] in self.development_telemetry:
                value = self.development_telemetry[record["id"]]
                if value == "missing":
                    dev["payload"].pop("telemetry_enabled")
                else:
                    dev["payload"]["telemetry_enabled"] = value
            return [dev]
        raise AssertionError(path)

    def request(self, method, path, data=None):
        if path.startswith("/actions/runs/"):
            identity = int(path.split("/")[3])
            if identity >= 100:
                record = next(r for r in self.records if r["id"] == identity - 100)
                return self.run | {"id": identity, "head_sha": record["sha"]}
            return self.runs[identity]
        if path.startswith("/deployments/"):
            identity = int(path.split("/")[2])
            return self.statuses[identity if identity < 100 else identity - 100]
        raise AssertionError(path)


@patch.dict(os.environ, {"PAWLOCAL_ONCALL_ENFORCE_GUARDS": "true"})
class RollbackTests(unittest.TestCase):
    def resolve(self, fake=None, selection=rollback.PREVIOUS, identity="", reason="Incident #404"):
        return rollback.resolve(fake or History(), selection, identity, reason)

    def test_previous_distinct_retired_success_and_explicit_selection(self):
        value = self.resolve()
        self.assertEqual(value["rollback_from_deployment_id"], "10")
        self.assertEqual(value["rollback_to_deployment_id"], "8")
        self.assertEqual(value["release_commit"], "a" * 40)
        self.assertEqual(self.resolve(selection=rollback.SPECIFIC, identity="7")["release_commit"], "e" * 40)

    def test_historical_automatic_environment_and_invalid_records_can_be_skipped(self):
        fake = History()
        fake.records.insert(1, fake.records[0] | {"id": 99, "created_at": "2026-10-01T00:00:09Z", "payload": {}})
        self.assertEqual(self.resolve(fake)["rollback_to_deployment_id"], "8")
        fake.statuses[8] = [status("failure", 21)]
        self.assertEqual(self.resolve(fake)["rollback_to_deployment_id"], "7")
        with self.assertRaises(rollback.Denied):
            self.resolve(fake, rollback.SPECIFIC, "8")

    def test_unknown_or_automatic_current_never_falls_back(self):
        for state in ("failure", "inactive", "unknown", "in_progress"):
            fake = History()
            fake.statuses[10] = [status(state, 21)]
            with self.subTest(state=state), self.assertRaises(rollback.Denied):
                self.resolve(fake)
        fake = History()
        fake.records[0]["payload"] = {}
        with self.assertRaises(rollback.Denied):
            self.resolve(fake)

    def test_bad_ids_current_pair_and_missing_proof_rejected(self):
        for identity in ("", "abc", "0", "-1", "10", "9", "999", "1\n", "9007199254740992"):
            with self.subTest(identity=identity), self.assertRaises(rollback.Denied):
                self.resolve(selection=rollback.SPECIFIC, identity=identity)
        for reason in ("", " ", "bad\nreason", "x" * 501):
            with self.subTest(reason=reason), self.assertRaises(rollback.Denied):
                self.resolve(reason=reason)
        fake = History()
        fake.development_missing = True
        with self.assertRaises(rollback.Denied):
            self.resolve(fake)
        fake = History()
        fake.records.append(copy.deepcopy(fake.records[-1]))
        with self.assertRaises(rollback.Denied):
            self.resolve(fake)

    def test_stale_identity_pair_and_producer_changes_rejected(self):
        fake = History()
        value = self.resolve(fake)
        args = ("10", "8", "Incident #404", value["release_commit"], value["backend_image"])
        rollback.validate(fake, *args)
        for source, target, sha, image in (("9", "8", args[3], args[4]), ("10", "10", args[3], args[4]),
                                          ("10", "8", "f" * 40, args[4]), ("10", "8", args[3], "bad")):
            with self.assertRaises(rollback.Denied):
                rollback.validate(fake, source, target, args[2], sha, image)
        fake.runs[8]["path"] = ".github/workflows/attacker.yml"
        with self.assertRaises(rollback.Denied):
            rollback.validate(fake, *args)

    def test_equal_timestamp_order_is_deterministic_and_newer_specific_rejected(self):
        fake = History()
        fake.records[2]["created_at"] = fake.records[1]["created_at"]
        self.assertEqual(self.resolve(fake)["rollback_to_deployment_id"], "8")
        fake.records[-1]["created_at"] = "2026-10-01T00:00:30Z"
        # Current identity cannot be silently taken from a stale earlier record.
        with self.assertRaises(rollback.Denied):
            rollback.validate(fake, "10", "7", "reason", "e" * 40, "ghcr.io/alanlima/pawlocal-api@sha256:" + "f" * 64)

    def test_readable_summary_escapes_operator_markup(self):
        value = self.resolve(reason='```<script>unsafe</script>')
        result = rollback.summary(value)
        self.assertIn('| From | 10 |', result)
        self.assertIn('| To | 8 |', result)
        self.assertNotIn('<script>', result)
        self.assertEqual(result.count('```'), 2)

    def test_rollback_producer_is_trusted_by_canonical_history(self):
        fake = History()
        fake.runs[10]["path"] = ".github/workflows/release-rollback-production.yml"
        self.assertEqual(self.resolve(fake)["rollback_from_deployment_id"], "10")

    def test_manual_rollback_accepts_disabled_current_target_and_development(self):
        for disabled in ({10}, {8}, {10, 9, 8, 7}):
            fake = History()
            for record in fake.records:
                if record["id"] in disabled:
                    record["payload"]["telemetry_enabled"] = False
            result = self.resolve(fake)
            self.assertEqual(result["rollback_to_deployment_id"], "8")
            rollback.validate(fake, "10", "8", "reason", result["release_commit"], result["backend_image"])
        # Development and production can have different configured telemetry modes.
        fake = History()
        fake.development_telemetry = {10: False, 8: False}
        self.assertEqual(self.resolve(fake)["rollback_to_deployment_id"], "8")
        # Existing incident consumers preserve the secure enabled-only default,
        # including the matching development record when production is enabled.
        with self.assertRaises(rollback.Denied):
            rollback.deployed_release(fake, "production")
        fake.records[0]["payload"]["telemetry_enabled"] = False
        with self.assertRaises(rollback.Denied):
            rollback.deployed_release(fake, "production")
        with self.assertRaises(rollback.Denied):
            rollback.verified_record(fake, fake.records[0], "production")

    def test_manual_rollback_still_rejects_missing_or_nonboolean_telemetry(self):
        for invalid in (None, "false", "true", 0, 1, [], {}, "missing"):
            for where in ("current", "target", "development-current", "development-target"):
                fake = History()
                identity = 10 if where.endswith("current") else 8
                record = next(r for r in fake.records if r["id"] == identity)
                if where.startswith("development"):
                    fake.development_telemetry[identity] = invalid
                elif invalid == "missing":
                    record["payload"].pop("telemetry_enabled")
                else:
                    record["payload"]["telemetry_enabled"] = invalid
                with self.subTest(invalid=invalid, where=where), self.assertRaises(rollback.Denied):
                    self.resolve(fake, rollback.SPECIFIC, "8")


class WorkflowTests(unittest.TestCase):
    def load(self, name):
        return yaml.safe_load((ROOT / ".github/workflows" / name).read_text(encoding="utf-8"))

    def test_one_canonical_pipeline_and_lock_with_no_incident_input_changes(self):
        wrapper = self.load("release-rollback-production.yml")
        production = self.load("deploy-production.yml")
        self.assertNotIn("concurrency", wrapper)
        self.assertEqual(production["concurrency"]["group"], "pawlocal-lifecycle-production")
        self.assertEqual(wrapper["jobs"]["rollback"]["uses"], "./.github/workflows/deploy-production.yml")
        self.assertIn("!inputs.preview_only", wrapper["jobs"]["rollback"]["if"])
        self.assertEqual(set(production[True]["workflow_dispatch"]["inputs"]),
                         {"release_commit", "backend_image", "incident_environment", "expected_workflow_sha"})
        binding = production["jobs"]["workflow-binding"]
        self.assertIn("rollback-binding", binding["needs"])
        self.assertIn("needs.rollback-binding.result == 'success'", binding["if"])
        stale = production["jobs"]["rollback-binding"]
        self.assertFalse(any('environment' in step or 'aws-actions' in step.get('uses', '') for step in stale["steps"]))
        self.assertNotIn("environment", stale)

    def test_rollback_plan_enforcement_cannot_be_disabled_by_incident_toggle(self):
        terraform = self.load("terraform-environment.yml")
        steps = terraform["jobs"]["plan"]["steps"]
        guard = next(s for s in steps if s.get("name") == "Reject unrelated infrastructure changes in a rollback")
        self.assertEqual(guard["if"], "inputs.rollback_only")
        self.assertEqual(guard["env"]["PAWLOCAL_ONCALL_ENFORCE_GUARDS"], "true")
        self.assertIn("--mode=validate-plan", guard["run"])
        self.assertLess(steps.index(guard), next(i for i,s in enumerate(steps) if s.get("name") == "Bind exact plan metadata"))


if __name__ == "__main__":
    unittest.main()
