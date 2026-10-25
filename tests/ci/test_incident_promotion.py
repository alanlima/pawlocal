import os
from unittest.mock import patch
import copy
import io
import json
import subprocess
import sys
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "ops/incident-response"))
import promotion


def publication():
    return {
        "pr": 12,
        "candidate_sha": "a" * 40,
        "base_sha": "b" * 40,
        "tree_sha": "c" * 40,
        "branch": "incident/development/" + "d" * 16,
    }


def run(workflow="fullstack-release.yml", event="pull_request"):
    return {
        "id": 123,
        "repository": {"id": 1423024931},
        "head_repository": {"id": 1423024931},
        "path": ".github/workflows/" + workflow,
        "event": event,
        "run_attempt": 1,
        "head_sha": "a" * 40,
        "head_branch": "main",
        "status": "completed",
        "conclusion": "success",
        "pull_requests": [{"number": 12}],
    }


class Client:
    deadline = int(time.time()) + 600
    token = "fixture"

    def __init__(self):
        self.run = run()
        self.jobs = [
            {
                "name": name,
                "conclusion": "success",
                "run_id": 123,
                "run_attempt": 1,
                "head_sha": "a" * 40,
                "check_run_url": promotion.GITHUB + "/check-runs/456",
            }
            for name in promotion.CHECKS
        ]
        self.environment = {
            "protection_rules": [],
            "deployment_branch_policy": {
                "protected_branches": False,
                "custom_branch_policies": True,
            },
        }
        self.branches = {
            "total_count": 1,
            "branch_policies": [{"name": "main", "type": "branch"}],
        }
        self.statuses = [
            {
                "context": "PawLocal change authorization",
                "state": "success",
                "creator": {"login": "pawlocal-publisher[bot]", "type": "Bot"},
            }
        ]

    def request(self, method, path, _body=None):
        assert method == "GET"
        if path.startswith("/actions/runs?"):
            return {"total_count": 1, "workflow_runs": [self.run]}
        if path == "/actions/runs/123/jobs?per_page=100":
            return {"total_count": len(self.jobs), "jobs": self.jobs}
        if path.startswith("/environments/") and "/deployment-branch-policies" in path:
            return self.branches
        if path.startswith("/environments/"):
            return self.environment
        if path == f"/commits/{'a' * 40}/statuses":
            return self.statuses
        raise AssertionError(path)


@patch.dict(os.environ, {'PAWLOCAL_ONCALL_ENFORCE_GUARDS': 'true'})
class PromotionTests(unittest.TestCase):
    def test_dispatch_broker_accepts_optional_origin_environment(self):
        body = {
            "ref": "main", "return_run_details": True,
            "inputs": {"release_commit": "a" * 40,
                       "backend_image": "ghcr.io/alanlima/pawlocal-api@sha256:" + "b" * 64,
                       "expected_workflow_sha": "a" * 40,
                       "incident_environment": "development"},
        }
        class Response(io.BytesIO):
            status = 200
        class Opener:
            def open(self, request, **options):
                return Response(b"{}")
        self.assertEqual(promotion.request("fixture", time.time()+30, "POST",
                          "/actions/workflows/deploy-production.yml/dispatches", body,
                          opener=Opener()), {})
        body["inputs"]["incident_environment"] = "unsupported"
        with self.assertRaisesRegex(promotion.Denied, "non-allowlisted"):
            promotion.request("fixture", time.time()+30, "POST",
                              "/actions/workflows/deploy-production.yml/dispatches", body)

    def test_dispatch_broker_requires_the_exact_workflow_assertion(self):
        body = {
            "ref": "main",
            "return_run_details": True,
            "inputs": {
                "release_commit": "a" * 40,
                "backend_image": "ghcr.io/alanlima/pawlocal-api@sha256:" + "d" * 64,
                "expected_workflow_sha": "a" * 40,
            },
        }
        for expected in (None, "", "b" * 40, True):
            bad = copy.deepcopy(body)
            if expected is None:
                del bad["inputs"]["expected_workflow_sha"]
            else:
                bad["inputs"]["expected_workflow_sha"] = expected
            with self.subTest(expected=expected), self.assertRaisesRegex(
                promotion.Denied, "non-allowlisted"
            ):
                promotion.request(
                    "fixture", time.time() + 30, "POST",
                    "/actions/workflows/deploy-production.yml/dispatches", bad,
                )

    def test_main_race_returns_wrong_workflow_sha_and_never_claims_production(self):
        sha = "a" * 40
        development = {"affected_sha": sha, "image_digest": "sha256:" + "d" * 64}
        client = Client()
        dispatched_run = run("deploy-production.yml", "workflow_dispatch")
        dispatched_run["head_sha"] = "b" * 40

        def read(method, path, _body=None):
            if path == "/git/ref/heads/main":
                return {"object": {"sha": sha}}
            if path == "/actions/runs/123":
                return dispatched_run
            raise AssertionError(path)

        client.request = read
        with (
            patch.object(promotion, "runtime_ready"),
            patch.object(promotion, "wait_development", return_value=development),
            patch.object(promotion, "deployed_release") as deployed,
            patch.object(promotion, "request", return_value={
                "workflow_run_id": 123,
                "run_url": promotion.GITHUB + "/actions/runs/123",
                "html_url": "https://github.com/alanlima/pawlocal/actions/runs/123",
            }) as dispatch,
        ):
            with self.assertRaisesRegex(promotion.Denied, "provenance"):
                promotion.promote(client, sha, incident_environment="development")
            inputs = dispatch.call_args.args[4]["inputs"]
            self.assertEqual(inputs["expected_workflow_sha"], sha)
            self.assertEqual(inputs["release_commit"], sha)
            self.assertEqual(inputs["incident_environment"], "development")
            deployed.assert_not_called()

    def test_production_binding_precedes_every_reusable_or_credential_job(self):
        root = Path(__file__).resolve().parents[2]
        jobs = yaml.safe_load((root / ".github/workflows/deploy-production.yml").read_text())["jobs"]
        guard = jobs["workflow-binding"]
        self.assertEqual(guard["permissions"], {})
        self.assertNotIn("environment", guard)
        self.assertTrue(all("uses" not in step for step in guard["steps"]))

        def depends(name):
            needs = jobs[name].get("needs", [])
            needs = [needs] if isinstance(needs, str) else needs
            return "workflow-binding" in needs or any(depends(item) for item in needs)

        for name, job in jobs.items():
            if "uses" in job or job.get("permissions", {}).get("id-token") == "write":
                with self.subTest(job=name):
                    self.assertTrue(depends(name))

    @unittest.skipIf(os.name == "nt", "Production guard executes under hosted Linux bash")
    def test_actual_entry_guard_rejects_race_and_preserves_ordinary_older_release(self):
        root = Path(__file__).resolve().parents[2]
        workflow = yaml.safe_load((root / ".github/workflows/deploy-production.yml").read_text())
        script = workflow["jobs"]["workflow-binding"]["steps"][0]["run"]
        for expected, actual, release, accepted in (
            ("a" * 40, "a" * 40, "a" * 40, True),
            ("a" * 40, "b" * 40, "a" * 40, False),
            ("a" * 40, "a" * 40, "b" * 40, False),
            ("true", "a" * 40, "a" * 40, False),
            ("", "b" * 40, "a" * 40, True),
        ):
            with self.subTest(expected=expected, actual=actual, release=release):
                result = subprocess.run(
                    ["bash", "-c", script], check=False, capture_output=True,
                    env={"PATH": os.environ["PATH"], "EXPECTED_WORKFLOW_SHA": expected,
                         "ACTUAL_WORKFLOW_SHA": actual, "RELEASE_COMMIT": release},
                )
                self.assertEqual(result.returncode == 0, accepted)

    def test_configured_production_rule_is_required_before_dispatch(self):
        metadata = {"alert": {"environment": "development", "service": "pawlocal-api"}}
        profile = SimpleNamespace(digest="d" * 64, recovery_seconds=600)
        value = {"promotion_deadline": int(time.time()) + 600}
        development = {
            "merged_sha": "a" * 40,
            "merge_sha256": "e" * 64,
            "release": {"affected_sha": "a" * 40},
            "recovery": {"profile_sha256": profile.digest, "window_seconds": 600},
        }
        with (
            patch.dict(
                os.environ,
                ({"PAWLOCAL_ONCALL_ENFORCE_GUARDS": "true"} | {
                    "PROMOTION_DEADLINE": str(value["promotion_deadline"]),
                    "GH_TOKEN": "fixture",
                    "PAWLOCAL_ONCALL_ENABLED": "true",
                    "PAWLOCAL_PRODUCTION_TELEMETRY_READ_APPROVED": "true",
                    "RUNNER_TEMP": "/fixture",
                    "GITHUB_WORKSPACE": "/fixture",
                    "MERGE_SHA256": "e" * 64,
                    "DEVELOPMENT_SHA256": "f" * 64,
                }),
                clear=True,
            ),
            patch.object(sys, "argv", ["promotion.py", "promote"]),
            patch.object(promotion, "arm"),
            patch.object(
                promotion, "publication", return_value=(metadata, profile, value)
            ),
            patch.object(promotion, "ReleaseClient"),
            patch.object(promotion, "LiveControl"),
            patch.object(promotion, "verified_merge", return_value="a" * 40),
            patch.object(promotion.receipts, "read", return_value=development),
            patch.object(promotion.receipts, "validate_recovery"),
            patch.object(
                promotion,
                "configured_rule",
                side_effect=promotion.Denied("fixture production rule absent"),
            ) as rule,
            patch.object(promotion, "promote") as dispatch,
        ):
            with self.assertRaises(promotion.Denied):
                promotion.main()
            self.assertEqual(rule.call_args.args[1], "production")
            dispatch.assert_not_called()

    def test_candidate_authorization_waits_for_pending_and_requires_authorized_bot(self):
        client = Client()
        self.assertTrue(promotion.candidate_authorization(client, publication()))

        client.statuses = []
        self.assertFalse(promotion.candidate_authorization(client, publication()))

        client.statuses = [{"context": "PawLocal change authorization", "state": "pending"}]
        self.assertFalse(promotion.candidate_authorization(client, publication()))

        client.statuses = [{"context": "PawLocal change authorization", "state": "failure"}]
        with self.assertRaises(promotion.Denied):
            promotion.candidate_authorization(client, publication())

        client.statuses = [
            {
                "context": "PawLocal change authorization",
                "state": "success",
                "creator": {"login": "attacker", "type": "User"},
            }
        ]
        with self.assertRaises(promotion.Denied):
            promotion.candidate_authorization(client, publication())

    def test_candidate_requires_both_authentic_jobs_from_fixed_pr_workflow(self):
        client = Client()
        self.assertTrue(promotion.candidate_ci(client, publication()))
        for mutation in (
            {"run_attempt": 2},
            {"head_sha": "e" * 40},
            {"conclusion": "skipped"},
            {"check_run_url": "https://attacker.invalid/check-runs/456"},
        ):
            bad = Client()
            bad.jobs[0].update(mutation)
            with self.subTest(mutation=mutation), self.assertRaises(promotion.Denied):
                promotion.candidate_ci(bad, publication())
        client.jobs.append(copy.deepcopy(client.jobs[0]))
        with self.assertRaises(promotion.Denied):
            promotion.candidate_ci(client, publication())

    def test_foreign_workflow_repo_generation_or_pr_never_qualifies(self):
        for mutation in (
            {"path": ".github/workflows/attacker.yml"},
            {"repository": {"id": 99}},
            {"head_repository": {"id": 99}},
            {"run_attempt": 2},
            {"head_sha": "f" * 40},
            {"pull_requests": [{"number": 999}]},
        ):
            client = Client()
            client.run.update(mutation)
            self.assertFalse(promotion.candidate_ci(client, publication()))

    def test_failed_candidate_is_not_a_retry_loop(self):
        client = Client()
        client.run["conclusion"] = "failure"
        with self.assertRaises(promotion.Denied):
            promotion.candidate_ci(client, publication())

    def test_production_requires_no_runtime_human_gate_and_exact_main_branch(self):
        promotion.runtime_ready(Client())
        client = Client()
        client.environment["protection_rules"] = [{"type": "required_reviewers"}]
        with self.assertRaises(promotion.Denied):
            promotion.runtime_ready(client)
        for branch in ("*", "release/*", "main*"):
            client = Client()
            client.branches["branch_policies"][0]["name"] = branch
            with self.subTest(branch=branch), self.assertRaises(promotion.Denied):
                promotion.runtime_ready(client)

    def test_release_mutations_reject_arbitrary_workflows_approvals_and_unpinned_merge(
        self,
    ):
        for method, path, body in (
            ("POST", "/actions/workflows/terraform-environment.yml/dispatches", {}),
            ("PUT", "/pulls/12/merge", {"sha": "a" * 40, "merge_method": "merge"}),
            ("PUT", "/pulls/12/merge", {"merge_method": "squash"}),
            ("POST", "/pulls/12/reviews", {"event": "APPROVE"}),
            ("PATCH", "/git/refs/heads/main", {"sha": "a" * 40}),
        ):
            with self.subTest(path=path), self.assertRaises(promotion.Denied):
                promotion.request("fixture", time.time() + 30, method, path, body)

    def test_only_production_apply_reviewer_blocks_full_runtime_readiness(self):
        client = Client()
        original = client.request
        visited = []

        def read(method, path, body=None):
            visited.append(path)
            value = original(method, path, body)
            if path == "/environments/production-apply":
                return value | {"protection_rules": [{"type": "required_reviewers"}]}
            return value

        client.request = read
        with self.assertRaises(promotion.Denied):
            promotion.runtime_ready(client)
        self.assertIn("/environments/production-apply", visited)
        self.assertIn("/environments/development-apply", visited)
        self.assertFalse(
            any("bootstrap" in path or "destroy" in path for path in visited)
        )

    def test_revoked_production_read_authority_stops_both_followup_phases(self):
        for phase in ("merge", "promote"):
            with (
                self.subTest(phase=phase),
                patch.dict(
                    os.environ,
                    ({"PAWLOCAL_ONCALL_ENFORCE_GUARDS": "true"} | {
                        "PAWLOCAL_ONCALL_ENABLED": "true",
                        "PAWLOCAL_PRODUCTION_TELEMETRY_READ_APPROVED": "false",
                        "PROMOTION_DEADLINE": str(int(time.time()) + 600),
                        "GH_TOKEN": "fixture",
                    }),
                    clear=True,
                ),
                patch.object(sys, "argv", ["promotion.py", phase]),
                patch.object(promotion, "arm"),
                patch.object(
                    promotion,
                    "publication",
                    return_value=(
                        {"alert": {"environment": "production"}},
                        None,
                        {"promotion_deadline": int(time.time()) + 600},
                    ),
                ),
                patch.object(promotion, "ReleaseClient") as client,
                patch.object(promotion, "current_alert") as alert,
                patch.object(promotion, "deployed_release") as release,
            ):
                with self.assertRaises(promotion.Denied):
                    promotion.main()
                client.return_value.request.assert_not_called()
                alert.assert_not_called()
                release.assert_not_called()

    def test_exact_squash_request_carries_candidate_sha(self):
        class Response(io.BytesIO):
            status = 200

        class Opener:
            def open(self, request, timeout):
                self.request = request
                return Response(b'{"merged":true,"sha":"fixture"}')

        opener = Opener()
        body = {"sha": "a" * 40, "merge_method": "squash"}
        promotion.request(
            "fixture", time.time() + 30, "PUT", "/pulls/12/merge", body, opener
        )
        self.assertEqual(opener.request.full_url, promotion.GITHUB + "/pulls/12/merge")
        self.assertEqual(json.loads(opener.request.data), body)

    def test_failed_development_push_stops_before_production_dispatch(self):
        client = Client()
        client.run = run(event="push")
        client.run["conclusion"] = "failure"
        with (
            patch.object(promotion, "runtime_ready"),
            patch.object(promotion, "request") as dispatch,
        ):
            with self.assertRaises(promotion.Denied):
                promotion.promote(client, "a" * 40)
            dispatch.assert_not_called()

    def test_expired_release_phase_denies_without_any_mutation(self):
        with self.assertRaises(promotion.Denied):
            promotion.pause(time.time() - 1)
        with self.assertRaises(promotion.Denied):
            promotion.request(
                "fixture",
                time.time() - 1,
                "PUT",
                "/pulls/12/merge",
                {"sha": "a" * 40, "merge_method": "squash"},
            )


if __name__ == "__main__":
    unittest.main()
