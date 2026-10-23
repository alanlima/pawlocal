"""Tests for change authorization and entrypoint guard contracts (#245)."""

from __future__ import annotations

import json
import time
import unittest
from unittest.mock import MagicMock

import sys
from pathlib import Path

# Add search paths for change-authorization and incident-response
root_dir = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(root_dir / "ops" / "change-authorization"))
sys.path.insert(0, str(root_dir / "ops" / "incident-response"))

from authorizer import (
    CONTEXT,
    Denied,
    GitHubClient,
    classify_pr,
    verify_incident_candidate,
    verify_ordinary_approval,
)
from guards import PlanViolation, validate_production_promotion, validate_release_plan_strict


class ChangeAuthorizationClassifierTests(unittest.TestCase):
    def test_authenticated_bot_incident_branch_classifies_as_incident(self):
        pr = {
            "number": 100,
            "draft": False,
            "base": {"ref": "main", "sha": "a" * 40},
            "head": {"ref": "incident/development/0123456789abcdef", "sha": "b" * 40},
            "user": {"login": "pawlocal-publisher[bot]", "type": "Bot"},
        }
        self.assertEqual(classify_pr(pr), "incident")

    def test_ordinary_human_pr_classifies_as_ordinary(self):
        pr = {
            "number": 101,
            "draft": False,
            "base": {"ref": "main", "sha": "a" * 40},
            "head": {"ref": "feature/my-feature", "sha": "c" * 40},
            "user": {"login": "alanlima", "type": "User"},
        }
        self.assertEqual(classify_pr(pr), "ordinary")

    def test_spoofed_incident_branch_from_human_classifies_as_ordinary(self):
        pr = {
            "number": 102,
            "draft": False,
            "base": {"ref": "main", "sha": "a" * 40},
            "head": {"ref": "incident/development/forged", "sha": "d" * 40},
            "user": {"login": "attacker", "type": "User"},
        }
        self.assertEqual(classify_pr(pr), "ordinary")

    def test_draft_pr_denied(self):
        pr = {
            "number": 103,
            "draft": True,
            "base": {"ref": "main"},
            "head": {"ref": "incident/development/test"},
            "user": {"login": "pawlocal-publisher[bot]", "type": "Bot"},
        }
        with self.assertRaises(Denied):
            classify_pr(pr)

    def test_non_main_target_denied(self):
        pr = {
            "number": 104,
            "draft": False,
            "base": {"ref": "release-branch"},
            "head": {"ref": "incident/development/test"},
            "user": {"login": "pawlocal-publisher[bot]", "type": "Bot"},
        }
        with self.assertRaises(Denied):
            classify_pr(pr)

    def test_parameterized_publisher_bot_login(self):
        pr = {
            "number": 105,
            "draft": False,
            "base": {"ref": "main"},
            "head": {"ref": "incident/development/test"},
            "user": {"login": "custom-app-publisher[bot]", "type": "Bot"},
        }
        self.assertEqual(classify_pr(pr, publisher_bot_logins={"custom-app-publisher[bot]"}), "incident")

    def test_github_client_parameterization_and_validation(self):
        client = GitHubClient(token="dummy-token", repository="custom-org/custom-repo", context="Custom authorization")
        self.assertEqual(client.repository, "custom-org/custom-repo")
        self.assertEqual(client.context, "Custom authorization")
        self.assertEqual(client.api_base, "https://api.github.com/repos/custom-org/custom-repo")

        with self.assertRaises(Denied):
            GitHubClient(token="dummy-token", repository="")
        with self.assertRaises(Denied):
            GitHubClient(token="dummy-token", repository="invalid-format-no-slash")


class IncidentCandidateVerificationTests(unittest.TestCase):
    def setUp(self):
        self.client = MagicMock(spec=GitHubClient)
        self.head_sha = "1" * 40
        self.base_sha = "2" * 40
        self.pr_number = 200

        self.valid_pr = {
            "number": self.pr_number,
            "state": "open",
            "draft": False,
            "head": {"sha": self.head_sha, "ref": "incident/development/0123456789abcdef"},
            "base": {"sha": self.base_sha, "ref": "main"},
        }
        self.valid_receipt = {
            "schema": 1,
            "pr": self.pr_number,
            "candidate_sha": self.head_sha,
            "base_sha": self.base_sha,
            "branch": "incident/development/0123456789abcdef",
            "promotion_deadline": time.time() + 600,
        }

    def test_valid_incident_candidate_authorized(self):
        self.client.get_pr.return_value = self.valid_pr
        self.client.get_pr_files.return_value = [
            "backend/pawlocal/api.py",
            "frontend/src/App.tsx",
        ]
        result = verify_incident_candidate(self.client, self.pr_number, self.valid_receipt)
        self.assertTrue(result["authorized"])
        self.assertEqual(result["route"], "incident")

    def test_candidate_touching_migrations_denied(self):
        self.client.get_pr.return_value = self.valid_pr
        self.client.get_pr_files.return_value = [
            "backend/pawlocal/api.py",
            "backend/migrations/dsql/0001_initial/001_places.sql",
        ]
        with self.assertRaises(Denied):
            verify_incident_candidate(self.client, self.pr_number, self.valid_receipt)

    def test_candidate_touching_post_apply_setup_denied(self):
        self.client.get_pr.return_value = self.valid_pr
        self.client.get_pr_files.return_value = [
            "backend/pawlocal/dsql_post_apply_setup.py",
        ]
        with self.assertRaises(Denied):
            verify_incident_candidate(self.client, self.pr_number, self.valid_receipt)

    def test_candidate_touching_env_files_denied(self):
        self.client.get_pr.return_value = self.valid_pr
        self.client.get_pr_files.return_value = [
            "frontend/.env.production",
        ]
        with self.assertRaises(Denied):
            verify_incident_candidate(self.client, self.pr_number, self.valid_receipt)

    def test_candidate_touching_lockfiles_denied(self):
        self.client.get_pr.return_value = self.valid_pr
        self.client.get_pr_files.return_value = [
            "backend/uv.lock",
        ]
        with self.assertRaises(Denied):
            verify_incident_candidate(self.client, self.pr_number, self.valid_receipt)

    def test_candidate_exceeding_max_file_count_denied(self):
        self.client.get_pr.return_value = self.valid_pr
        self.client.get_pr_files.return_value = [
            f"backend/pawlocal/module_{i}.py" for i in range(25)
        ]
        with self.assertRaises(Denied):
            verify_incident_candidate(self.client, self.pr_number, self.valid_receipt)

    def test_mismatched_candidate_sha_denied(self):
        self.client.get_pr.return_value = self.valid_pr
        receipt = dict(self.valid_receipt, candidate_sha="3" * 40)
        with self.assertRaises(Denied):
            verify_incident_candidate(self.client, self.pr_number, receipt)

    def test_expired_promotion_deadline_denied(self):
        self.client.get_pr.return_value = self.valid_pr
        self.client.get_pr_files.return_value = ["backend/pawlocal/api.py"]
        receipt = dict(self.valid_receipt, promotion_deadline=time.time() - 10)
        with self.assertRaises(Denied):
            verify_incident_candidate(self.client, self.pr_number, receipt)

    def test_automatic_publication_download_from_pr_body(self):
        import io, zipfile
        pr_with_body = dict(
            self.valid_pr,
            body="Workflow evidence: https://github.com/alanlima/pawlocal/actions/runs/12345"
        )
        self.client.get_pr.return_value = pr_with_body
        self.client.get_pr_files.return_value = ["backend/pawlocal/api.py"]
        
        # Mock run and artifact calls
        self.client.request.side_effect = lambda method, url, data=None: {
            "/actions/runs/12345": {
                "id": 12345,
                "path": ".github/workflows/incident-responder.yml",
                "head_branch": "main",
                "repository": {"id": 1423024931},
                "event": "workflow_dispatch",
            },
            "/actions/runs/12345/artifacts?per_page=100": {
                "artifacts": [{"id": 999, "name": "oncall-publication-12345"}]
            }
        }.get(url, {})

        zip_buf = io.BytesIO()
        with zipfile.ZipFile(zip_buf, "w") as z:
            z.writestr("publication.json", json.dumps(self.valid_receipt))
        self.client.download_raw.return_value = zip_buf.getvalue()

        result = verify_incident_candidate(self.client, self.pr_number)
        self.assertTrue(result["authorized"])

    def test_untrusted_workflow_path_for_publication_denied(self):
        pr_with_body = dict(
            self.valid_pr,
            body="Workflow evidence: https://github.com/alanlima/pawlocal/actions/runs/12345"
        )
        self.client.get_pr.return_value = pr_with_body
        self.client.request.return_value = {
            "id": 12345,
            "path": ".github/workflows/untrusted.yml",
            "head_branch": "main",
            "repository": {"id": 1423024931},
            "event": "workflow_dispatch",
        }
        with self.assertRaises(Denied):
            verify_incident_candidate(self.client, self.pr_number)


class OrdinaryChangeApprovalTests(unittest.TestCase):
    def setUp(self):
        self.client = MagicMock(spec=GitHubClient)
        self.head_sha = "a" * 40
        self.base_sha = "b" * 40
        self.pr_number = 300

    def test_ordinary_pr_with_unchanged_head_approved(self):
        self.client.get_pr.return_value = {
            "number": self.pr_number,
            "state": "open",
            "draft": False,
            "head": {"sha": self.head_sha},
            "base": {"sha": self.base_sha, "ref": "main"},
        }
        result = verify_ordinary_approval(
            self.client, self.pr_number, self.head_sha, self.base_sha
        )
        self.assertTrue(result["authorized"])
        self.assertEqual(result["route"], "ordinary")

    def test_ordinary_pr_denied_if_head_changed_after_review(self):
        # A new commit pushed while waiting in protected environment
        self.client.get_pr.return_value = {
            "number": self.pr_number,
            "state": "open",
            "draft": False,
            "head": {"sha": "new_unreviewed_sha_" + "c" * 23},
            "base": {"sha": self.base_sha, "ref": "main"},
        }
        with self.assertRaises(Denied):
            verify_ordinary_approval(
                self.client, self.pr_number, self.head_sha, self.base_sha
            )


class EntrypointGuardTests(unittest.TestCase):
    def setUp(self):
        self.commit = "f" * 40
        self.image = "ghcr.io/alanlima/pawlocal-api@sha256:" + "0" * 64

    def test_machine_production_promotion_requires_valid_lineage(self):
        lineage = {
            "schema": 1,
            "release_commit": self.commit,
            "backend_image": self.image,
            "development_verified": True,
            "recovery_verified": True,
        }
        self.assertTrue(
            validate_production_promotion(lineage, self.commit, self.image, is_machine_route=True)
        )

    def test_machine_production_promotion_without_lineage_denies(self):
        with self.assertRaises(ValueError):
            validate_production_promotion(None, self.commit, self.image, is_machine_route=True)

    def test_machine_production_promotion_missing_recovery_denies(self):
        lineage = {
            "schema": 1,
            "release_commit": self.commit,
            "backend_image": self.image,
            "development_verified": True,
            "recovery_verified": False,
        }
        with self.assertRaises(ValueError):
            validate_production_promotion(lineage, self.commit, self.image, is_machine_route=True)

    def test_strict_plan_validation_permits_deployment_version_update(self):
        plan = {
            "resource_changes": [
                {
                    "type": "aws_lightsail_container_service_deployment_version",
                    "name": "pawlocal",
                    "change": {"actions": ["create"]},
                }
            ]
        }
        validate_release_plan_strict(plan)

    def test_strict_plan_validation_rejects_resource_deletion(self):
        plan = {
            "resource_changes": [
                {
                    "type": "aws_lightsail_container_service_deployment_version",
                    "name": "pawlocal",
                    "change": {"actions": ["delete"]},
                }
            ]
        }
        with self.assertRaises(PlanViolation):
            validate_release_plan_strict(plan)

    def test_strict_plan_validation_rejects_iam_modification(self):
        plan = {
            "resource_changes": [
                {
                    "type": "aws_iam_role_policy",
                    "name": "attacker_policy",
                    "change": {"actions": ["update"]},
                }
            ]
        }
        with self.assertRaises(PlanViolation):
            validate_release_plan_strict(plan)


if __name__ == "__main__":
    unittest.main()
