import os
from unittest.mock import patch
import copy
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "ops/incident-response"))
import receipts
import settings


@patch.dict(os.environ, {'PAWLOCAL_ONCALL_ENFORCE_GUARDS': 'true'})
class RecoveryReceiptTests(unittest.TestCase):
    def setUp(self):
        self.now = int(time.time())
        self.profile = SimpleNamespace(recovery_seconds=600, digest="a" * 64)
        self.release = {
            "affected_sha": "b" * 40,
            "image_digest": "sha256:" + "c" * 64,
            "deployment_id": 123,
            "deployment_run": 456,
        }
        self.publication = {
            "published_at": self.now - 1000,
            "promotion_deadline": self.now + 1000,
        }
        self.proof = {
            "schema": 1,
            "environment": "production",
            "commit": "b" * 40,
            "digest": self.release["image_digest"],
            "deployment_id": 123,
            "deployment_run": 456,
            "window_seconds": 600,
            "started_at": self.now - 650,
            "completed_at": self.now - 50,
            "samples": 11,
            "settling_seconds": 100,
            "settling_samples": 2,
            "profile_sha256": "a" * 64,
        }

    def validate(self, proof):
        receipts.validate_recovery(
            proof, self.release, self.profile, "production", self.publication
        )

    def test_matching_complete_stable_proof(self):
        self.validate(self.proof)

    def test_identity_window_and_deadline_tampering_denied(self):
        changes = (
            {"environment": "development"},
            {"deployment_run": 999},
            {"profile_sha256": "d" * 64},
            {"window_seconds": 599},
            {"completed_at": self.now + 1},
            {"started_at": self.now - 649},
            {"settling_seconds": 400},
            {"samples": True},
            {"settling_samples": -1},
            {"started_at": float("nan")},
        )
        for change in changes:
            with self.subTest(change=change), self.assertRaises(receipts.Denied):
                self.validate(self.proof | change)
        incomplete = dict(self.proof)
        del incomplete["deployment_id"]
        with self.assertRaises(receipts.Denied):
            self.validate(incomplete)

    def test_envelope_rejects_cross_run_and_wrong_hash(self):
        metadata = {"run_id": "777"}
        publication = self.publication | {
            "admission_sha256": "e" * 64,
            "profile_sha256": "a" * 64,
        }
        envelope = {
            "schema": 1,
            "phase": "production",
            "run_id": "778",
            "admission_sha256": "e" * 64,
            "publication_sha256": "f" * 64,
            "profile_sha256": "a" * 64,
            "deadline": publication["promotion_deadline"],
            "recorded_at": self.now,
            "payload": {"recovery": self.proof},
        }
        raw = json.dumps(envelope).encode()
        with (
            patch.dict(os.environ, {"PUBLICATION_SHA256": "f" * 64}),
            patch.object(receipts, "download", return_value={"receipt.json": raw}),
        ):
            for expected in (receipts.digest(raw), "0" * 64):
                with (
                    self.subTest(expected=expected),
                    self.assertRaises(receipts.Denied),
                ):
                    receipts.read("production", expected, metadata, publication)


@patch.dict(os.environ, {'PAWLOCAL_ONCALL_ENFORCE_GUARDS': 'true'})
class ConfiguredBindingsTests(unittest.TestCase):
    def fixture(self):
        return {
            "version": 1,
            "environments": {
                env: {
                    "enabled": True,
                    "approval": {
                        "reference": "fixture-reviewed",
                        "residency": "fixture actual region review",
                        "free_plan_verified": True,
                        "quota_review": "fixture account quota review",
                        "isolation_review": "fixture both environment review",
                    },
                    "stack": {
                        "id": 42,
                        "slug": "fixture",
                        "url": "https://fixture.grafana.net",
                        "region": "au",
                        "faro_api_url": "https://faro-api-prod-au-southeast-0.grafana.net/faro",
                        "otlp_endpoint": "https://otlp-gateway-prod-au-southeast-0.grafana.net/otlp",
                        "otlp_instance_id": "42",
                    },
                    "frontend_origin": "https://" + prefix + ".example.com",
                    "datasources": {
                        signal: {"uid": signal + "-fixture", "name": "cloud-" + signal}
                        for signal in ("metrics", "logs", "traces")
                    },
                }
                for env, prefix in (
                    ("development", "pawlocal-dev"),
                    ("production", "pawlocal"),
                )
            },
        }

    def check(self, value):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "observability/grafana/cloud/bindings.json"
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps(value))
            settings.bindings_ready(directory)

    def test_both_configured_environments_required_before_spend(self):
        self.check(self.fixture())
        for change in (
            {"enabled": False},
            {"approval": None},
            {"approval": "invalid former mock-only contract"},
            {"datasources": None},
            {"frontend_origin": "https://attacker.example"},
            {"stack": None},
        ):
            value = copy.deepcopy(self.fixture())
            value["environments"]["production"].update(change)
            with self.subTest(change=change), self.assertRaises(settings.Denied):
                self.check(value)

    def test_producer_approval_reviews_and_complete_stack_are_required(self):
        for field in (
            "reference",
            "residency",
            "free_plan_verified",
            "quota_review",
            "isolation_review",
        ):
            value = self.fixture()
            del value["environments"]["production"]["approval"][field]
            with self.subTest(field=field), self.assertRaises(settings.Denied):
                self.check(value)
        value = self.fixture()
        value["environments"]["production"]["approval"]["free_plan_verified"] = False
        with self.assertRaises(settings.Denied):
            self.check(value)
        value = self.fixture()
        del value["environments"]["production"]["stack"]["otlp_instance_id"]
        with self.assertRaises(settings.Denied):
            self.check(value)


if __name__ == "__main__":
    unittest.main()
