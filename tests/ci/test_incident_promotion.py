import copy
import io
import json
import os
import sys
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

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
        raise AssertionError(path)


class PromotionTests(unittest.TestCase):
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
                {
                    "PROMOTION_DEADLINE": str(value["promotion_deadline"]),
                    "GH_TOKEN": "fixture",
                    "PAWLOCAL_ONCALL_ENABLED": "true",
                    "PAWLOCAL_PRODUCTION_TELEMETRY_READ_APPROVED": "true",
                    "RUNNER_TEMP": "/fixture",
                    "GITHUB_WORKSPACE": "/fixture",
                    "MERGE_SHA256": "e" * 64,
                    "DEVELOPMENT_SHA256": "f" * 64,
                },
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
                    {
                        "PAWLOCAL_ONCALL_ENABLED": "true",
                        "PAWLOCAL_PRODUCTION_TELEMETRY_READ_APPROVED": "false",
                        "PROMOTION_DEADLINE": str(int(time.time()) + 600),
                        "GH_TOKEN": "fixture",
                    },
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
