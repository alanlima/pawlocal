import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "ops/incident-response"))
import finalize


class Client:
    def __init__(self, stopped=False, uncertain=False):
        self.calls, self.stopped, self.uncertain = [], stopped, uncertain

    def request(self, method, path, body=None):
        self.calls.append((method, path, body))
        if method == "GET" and path == "/issues/456":
            return {
                "state": "closed" if self.stopped else "open",
                "body": "<!-- pawlocal-oncall-quota:v1 -->",
                "user": {"login": "alanlima"},
            }
        if method == "GET" and path == "/issues/789":
            return {
                "state": "open",
                "body": "<!-- pawlocal-incident:v1:"
                + "a" * 64
                + " -->\nhttps://github.com/alanlima/pawlocal/actions/runs/777",
                "user": {"login": "github-actions[bot]"},
            }
        if method == "POST":
            if self.uncertain:
                raise TimeoutError("fixture accepted-or-not unknown")
            return {"body": body["body"], "user": {"login": "github-actions[bot]"}}
        if method == "PATCH":
            return {"number": 789, "state": "closed"}
        raise AssertionError((method, path))


class FinalizerTests(unittest.TestCase):
    def run_finalizer(self, client=None, **changes):
        client = client or Client()
        with tempfile.TemporaryDirectory() as directory:
            summary = Path(directory) / "summary"
            env = {
                "INCIDENT_DEADLINE": str(int(time.time()) + 600),
                "INCIDENT_ISSUE": "789",
                "INCIDENT_KEY": "a" * 64,
                "PAWLOCAL_QUOTA_ISSUE": "456",
                "GITHUB_RUN_ID": "777",
                "GH_TOKEN": "fixture",
                "GITHUB_STEP_SUMMARY": str(summary),
                "ADMITTED": "false",
            } | changes
            metadata = {
                "issue": 789,
                "quota_issue": 456,
                "alert": {"incident_key": "a" * 64},
            }
            with (
                patch.dict(os.environ, env, clear=True),
                patch.object(finalize, "arm"),
                patch.object(finalize, "ReleaseClient", return_value=client),
                patch.object(finalize, "context", return_value=(metadata, None)),
                patch.object(
                    finalize, "publication", return_value=(metadata, None, {})
                ),
                patch.object(finalize, "complete", return_value=("b" * 40, 123)),
            ):
                error = None
                try:
                    finalize.main()
                except (finalize.Denied, TimeoutError) as caught:
                    error = caught
            return client.calls, summary.read_text(), error

    def test_expired_deadline_records_uncertain_locally_without_api_mutation(self):
        calls, summary, error = self.run_finalizer(
            INCIDENT_DEADLINE=str(int(time.time()) - 1)
        )
        self.assertEqual(calls, [])
        self.assertIsNone(error)
        self.assertIn("LEASE_UNCERTAIN", summary)

    def test_live_global_stop_prevents_outcome_mutation(self):
        calls, summary, error = self.run_finalizer(Client(stopped=True))
        self.assertIsInstance(error, finalize.Denied)
        self.assertFalse(any(method != "GET" for method, _, _ in calls))
        self.assertIn("LEASE_UNCERTAIN", summary)

    def test_failed_attempt_comments_escalation_without_closing_or_retrying(self):
        calls, summary, error = self.run_finalizer()
        self.assertIsNone(error)
        writes = [call for call in calls if call[0] != "GET"]
        self.assertEqual(len(writes), 1)
        self.assertIn("ESCALATED", writes[0][2]["body"])
        self.assertIn("ESCALATED", summary)
        self.assertIn("Any recorded or uncertain monthly reservation", summary)
        self.assertNotIn("full monthly reservation", writes[0][2]["body"])
        calls, summary, _ = self.run_finalizer(PUBLICATION_SHA256="b" * 64)
        self.assertIn("LEASE_UNCERTAIN", summary)
        self.assertFalse(any(method == "PATCH" for method, _, _ in calls))

    def test_only_verified_complete_recovery_closes_the_bound_incident(self):
        calls, summary, error = self.run_finalizer(
            ADMITTED="true", PROMOTER_RESULT="success", PUBLICATION_SHA256="b" * 64
        )
        self.assertIsNone(error)
        self.assertIn("RECOVERED", summary)
        self.assertEqual(
            [call for call in calls if call[0] == "PATCH"],
            [
                (
                    "PATCH",
                    "/issues/789",
                    {"state": "closed", "state_reason": "completed"},
                )
            ],
        )

    def test_uncertain_outcome_write_is_never_retried_or_followed_by_closure(self):
        calls, summary, error = self.run_finalizer(
            Client(uncertain=True), ADMITTED="true", PROMOTER_RESULT="success"
        )
        self.assertIsInstance(error, TimeoutError)
        self.assertEqual(sum(method == "POST" for method, _, _ in calls), 1)
        self.assertFalse(any(method == "PATCH" for method, _, _ in calls))
        self.assertIn("LEASE_UNCERTAIN", summary)

    def test_complete_requires_actual_release_identity_and_full_stable_proof(self):
        now = int(time.time())
        release = {
            "affected_sha": "b" * 40,
            "image_digest": "sha256:" + "c" * 64,
            "deployment_id": 12,
            "deployment_run": 123,
        }
        proof = {
            "schema": 1,
            "environment": "production",
            "commit": release["affected_sha"],
            "digest": release["image_digest"],
            "deployment_id": 12,
            "deployment_run": 123,
            "profile_sha256": "d" * 64,
            "window_seconds": 600,
            "samples": 21,
            "started_at": now - 601,
            "completed_at": now - 1,
            "settling_seconds": 0,
            "settling_samples": 0,
        }
        payload = {
            "merged_sha": "b" * 40,
            "merge_sha256": "e" * 64,
            "development_sha256": "f" * 64,
            "release": release,
            "recovery": proof,
        }
        profile, client = (
            SimpleNamespace(digest="d" * 64, recovery_seconds=600),
            SimpleNamespace(deadline=now + 60),
        )
        development = payload | {
            "recovery": proof
            | {
                "environment": "development",
                "started_at": now - 1801,
                "completed_at": now - 1201,
            }
        }
        published = {"published_at": now - 2400, "promotion_deadline": now + 60}
        with (
            patch.dict(
                os.environ, {"MERGE_SHA256": "e" * 64, "DEVELOPMENT_SHA256": "f" * 64}
            ),
            patch.object(
                finalize.receipts,
                "read",
                side_effect=lambda phase, *_args: (
                    development if phase == "development" else payload
                ),
            ),
            patch.object(finalize, "verified_merge", return_value="b" * 40),
            patch.object(finalize, "deployed_release", return_value=release),
        ):
            self.assertEqual(
                finalize.complete(client, {}, profile, published),
                ("b" * 40, 123),
            )
            proof["completed_at"] = now - 100
            with self.assertRaises(finalize.Denied):
                finalize.complete(client, {}, profile, published)


if __name__ == "__main__":
    unittest.main()
