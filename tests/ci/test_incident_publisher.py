import os
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch

DIRECTORY = Path(__file__).resolve().parents[2] / "ops/incident-response"
sys.path.insert(0, str(DIRECTORY))
import publisher


class PublisherPolicyTests(unittest.TestCase):
    def fixture(self):
        metadata = {
            "base_sha": "a" * 40,
            "deadline": int(time.time()) + 1200,
            "alert": {"environment": "development", "incident_key": "b" * 64},
        }
        return publisher.Broker("fixture-not-real-token", metadata, "c" * 40)

    def test_only_exact_incident_ref_can_be_created(self):
        broker = self.fixture()
        self.assertTrue(
            broker.approved(
                "POST",
                "/git/refs",
                {"ref": "refs/heads/incident/development/" + "b" * 16, "sha": "c" * 40},
            )
        )
        for ref in (
            "refs/heads/main",
            "refs/heads/incident/production/" + "b" * 16,
            "refs/tags/incident",
        ):
            self.assertFalse(
                broker.approved("POST", "/git/refs", {"ref": ref, "sha": "c" * 40})
            )
        self.assertFalse(
            broker.approved("PATCH", "/git/refs/heads/main", {"sha": "c" * 40})
        )

    def test_credentials_settings_infrastructure_and_foreign_workflow_operations_deny(
        self,
    ):
        broker = self.fixture()
        for method, path, body in (
            ("PATCH", "/actions/permissions", {}),
            ("PUT", "/actions/secrets/TOKEN", {}),
            ("POST", "/actions/workflows/arbitrary.yml/dispatches", {"ref": "main"}),
            ("POST", "/pulls/999/reviews", {"event": "APPROVE"}),
            ("DELETE", "/git/refs/heads/main", None),
        ):
            with self.subTest(path=path), self.assertRaises(publisher.Denied):
                broker.request(method, path, body)

    def test_candidate_tree_cannot_include_auth_workflow_terraform_or_traversal(self):
        broker = self.fixture()
        for path in (
            "backend/pawlocal/api/auth.py",
            ".github/workflows/deploy-production.yml",
            "infra/terraform/main.tf",
            "../../secret",
        ):
            value = {
                "base_tree": "a" * 40,
                "tree": [
                    {"path": path, "type": "blob", "mode": "100644", "sha": "d" * 40}
                ],
            }
            self.assertFalse(broker.approved("POST", "/git/trees", value))

    def test_authentic_job_gate_rejects_failed_or_duplicate_machine_evidence(self):
        class GitHub:
            def __init__(self, bad=False, duplicate=False):
                self.bad, self.duplicate = bad, duplicate

            def request(self, method, path):
                if path == "/actions/runs/123":
                    return {
                        "id": 123,
                        "repository": {"id": 1423024931},
                        "head_repository": {"id": 1423024931},
                        "path": ".github/workflows/incident-responder.yml",
                        "head_sha": "f" * 40,
                        "head_branch": "main",
                        "event": "workflow_dispatch",
                        "run_attempt": 1,
                    }
                jobs = [
                    {
                        "name": name,
                        "conclusion": "success",
                        "run_attempt": 1,
                        "run_id": 123,
                        "head_sha": "f" * 40,
                    }
                    for name in (
                        "Trusted preflight",
                        "Fix search/detail",
                        "Validate candidate",
                        "Fresh review",
                    )
                ]
                if self.bad:
                    jobs[-1]["conclusion"] = "failure"
                if self.duplicate:
                    jobs.append(jobs[-1])
                return {"jobs": jobs, "total_count": len(jobs)}

        with patch.dict(os.environ, {"GITHUB_SHA": "f" * 40}):
            publisher.authentic_jobs(GitHub(), "123")
            for fake in (GitHub(bad=True), GitHub(duplicate=True)):
                with self.assertRaises(publisher.Denied):
                    publisher.authentic_jobs(fake, "123")


if __name__ == "__main__":
    unittest.main()
