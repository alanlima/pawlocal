"""Default-off policy and honest disabled-mode phase integration (#375)."""

import base64
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "ops/incident-response"))
import admission
import candidate
import control
import deadline
import enforcement
import finalize
import promotion
import publisher
import quota
import receipts
import recovery
import settings
import test_incident_quota as quota_fixtures
import test_incident_admission as admission_fixtures
import test_incident_finalizer as finalizer_fixtures


class EnforcementTests(unittest.TestCase):
    def test_exact_default_and_invalid_configuration(self):
        for value, expected in (
            (None, False),
            ("", False),
            ("false", False),
            ("true", True),
        ):
            with self.subTest(value=value), patch.dict(os.environ, {}, clear=True):
                if value is not None:
                    os.environ[enforcement.FLAG] = value
                self.assertEqual(enforcement.enabled(), expected)
        for value in ("TRUE", "False", "0", " true ", "yes"):
            with (
                self.subTest(value=value),
                patch.dict(os.environ, {enforcement.FLAG: value}),
            ):
                with self.assertRaises(ValueError):
                    enforcement.enabled()

    def test_policy_switch_preserves_enabled_denial(self):
        with patch.dict(os.environ, {enforcement.FLAG: "true"}):
            with self.assertRaises(quota.Denied):
                enforcement.policy(False, "fixture denial", "candidate")
        with patch.dict(os.environ, {enforcement.FLAG: "false"}):
            enforcement.policy(False, "fixture denial", "candidate")
            self.assertIn("candidate", enforcement.evidence()["disabled_categories"])

    @patch.dict(os.environ, {enforcement.FLAG: "false"})
    def test_all_live_readiness_continuity_stop_and_deadline_checks_skip_without_reads(
        self,
    ):
        reader = Mock(side_effect=AssertionError("disabled guard must not query"))
        admission.readiness(reader)
        settings.runtime_ready(reader)
        settings.bindings_ready("/nonexistent")
        self.assertTrue(admission.current_alert("", "", {}, -1, opener=reader))
        control.LiveControl(reader, {"quota_issue": 1, "issue": 2}, -1).check()
        deadline.arm(-1)
        self.assertIsNone(deadline.DEADLINE)

    @patch.dict(os.environ, {enforcement.FLAG: "false"})
    def test_profile_expiry_monthly_and_request_ceilings_are_optional(self):
        profile = quota_fixtures.QuotaTests().profile(
            monthly_runs=1,
            monthly_microdollars=1,
            input_per_request=1,
            input_per_role=1,
            output_per_request=2,
            output_per_role=1,
            requests_per_role=1,
        )
        profile.valid_at(0)
        budget = quota.RequestBudget(profile)
        self.assertEqual(budget.admit(100), 2)
        self.assertEqual(budget.admit(100), 2)
        first = quota.reserve(profile, [], "2026-10", "1", 1)
        second = quota.reserve(profile, [first], "2026-10", "1", 2)
        self.assertEqual(first, second)

    @patch.dict(os.environ, {enforcement.FLAG: "false"})
    def test_candidate_non_allowlisted_path_roundtrip_and_isolation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original, edited, output = (
                root / name for name in ("original", "edited", "output")
            )
            for folder in (original, edited, output):
                folder.mkdir()
            (edited / "README.md").write_text("Actual candidate bytes\n")
            metadata = {"base_sha": "a" * 40, "alert": {"incident_key": "b" * 64}}
            # Windows lacks descriptor-relative read APIs; test bytes transport
            # here and retain the real contained reader in hosted Linux checks.
            with patch.object(
                candidate,
                "safe_bytes",
                side_effect=lambda root, name, maximum: (root / name).read_bytes(),
            ):
                raw = candidate.export(original, edited, metadata)
            candidate.materialize(candidate.load(raw, metadata), output)
            self.assertEqual(
                (output / "README.md").read_text(), "Actual candidate bytes\n"
            )
            for path in (
                "../escape",
                ".git/config",
                ".env",
                "nested/.env.local",
                "/absolute",
            ):
                with self.subTest(path=path), self.assertRaises(quota.Denied):
                    candidate.materialize({path: b"secret"}, output)

    @patch.dict(os.environ, {enforcement.FLAG: "false"})
    def test_disabled_recovery_never_queries_sleeps_or_fabricates_proof(self):
        profile = quota_fixtures.QuotaTests().profile()
        unavailable = Mock(
            side_effect=AssertionError("disabled recovery must not wait/query")
        )
        proof = recovery.observe(
            "/missing",
            "development",
            {},
            profile,
            service="",
            api_base_url="",
            frontend_origin="",
            stack_url="",
            query_token="",
            deadline=-1,
            opener=unavailable,
            sleep=unavailable,
        )
        self.assertFalse(proof["recovery_verified"])
        self.assertEqual(proof["window_seconds"], 0)
        self.assertEqual(proof["observations"], [])
        receipts.validate_recovery(proof, {}, profile, "development", {})
        with self.assertRaises(quota.Denied):
            receipts.validate_recovery(
                {"recovery_verified": True}, {}, profile, "development", {}
            )

    @patch.dict(os.environ, {enforcement.FLAG: "false"})
    def test_operational_credentials_and_transport_failures_still_error(self):
        with self.assertRaises(quota.Denied):
            admission.GitHub("", -1)
        with self.assertRaises(quota.Denied):
            quota.strict_json("not JSON")
        with self.assertRaises(quota.Denied):
            promotion.request("", -1, "GET", "/actions/runs/1")

    @patch.dict(os.environ, {enforcement.FLAG: "false"})
    def test_repeated_identity_future_generation_and_repeated_release_attempt_are_not_gates(
        self,
    ):
        alert = admission_fixtures.alert() | {
            "starts_at": "2099-01-01T00:00:00.000Z",
            "incident_key": "deliberately-different",
        }
        self.assertEqual(
            len(admission.alerts(json.dumps([alert, alert]), "development")), 2
        )
        client = Mock()
        client.request.return_value = {
            "total_count": 1,
            "workflow_runs": [
                {
                    "id": 123,
                    "run_attempt": 2,
                    "head_sha": "different",
                    "head_branch": "main",
                    "status": "completed",
                    "conclusion": "success",
                }
            ],
        }
        self.assertEqual(promotion.development_run(client, "b" * 40), 123)

    @patch.dict(os.environ, {enforcement.FLAG: "false"})
    def test_release_operation_failures_remain_errors_in_disabled_mode(self):
        client = Mock()
        client.request.return_value = {
            "total_count": 1,
            "workflow_runs": [
                {
                    "id": 123,
                    "head_branch": "main",
                    "status": "completed",
                    "conclusion": "failure",
                }
            ],
        }
        with self.assertRaisesRegex(quota.Denied, "development release failed"):
            promotion.development_run(client, "a" * 40)
        development = {"affected_sha": "a" * 40, "image_digest": "sha256:" + "b" * 64}
        client.token, client.deadline = "fixture", 0
        client.request.side_effect = lambda method, path: (
            {"object": {"sha": "a" * 40}}
            if path == "/git/ref/heads/main"
            else {"id": 123, "status": "completed", "conclusion": "cancelled"}
        )
        dispatch = {
            "workflow_run_id": 123,
            "run_url": promotion.GITHUB + "/actions/runs/123",
            "html_url": "https://github.com/alanlima/pawlocal/actions/runs/123",
        }
        with (
            patch.object(promotion, "wait_development", return_value=development),
            patch.object(promotion, "request", return_value=dispatch),
            patch.object(promotion, "deployed_release") as fallback,
        ):
            with self.assertRaisesRegex(quota.Denied, "production release failed"):
                promotion.promote(client, "a" * 40)
            fallback.assert_not_called()

    @patch.dict(os.environ, {enforcement.FLAG: "false"})
    def test_deletion_transport_and_more_than_twenty_tree_entries(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original, edited, output = (
                root / name for name in ("original", "edited", "output")
            )
            for folder in (original, edited, output):
                folder.mkdir()
            (original / "README.md").write_text("removed")
            (output / "README.md").write_text("removed")
            metadata = {"base_sha": "a" * 40, "alert": {"incident_key": "b" * 64}}
            raw = candidate.export(original, edited, metadata)
            content = candidate.load(raw, metadata)
            self.assertIsNone(content["README.md"])
            candidate.materialize(content, output)
            self.assertFalse((output / "README.md").exists())
            broker = publisher.Broker(
                "fixture",
                metadata
                | {"alert": metadata["alert"] | {"environment": "development"}},
                "a" * 40,
            )
            self.assertTrue(
                broker.approved(
                    "POST",
                    "/git/trees",
                    {
                        "base_tree": "b" * 40,
                        "tree": [
                            {
                                "path": f"docs/{number}.md",
                                "sha": None,
                                "mode": "100644",
                                "type": "blob",
                            }
                            for number in range(21)
                        ],
                    },
                )
            )

    @patch.dict(os.environ, {enforcement.FLAG: "false"})
    def test_external_merge_waits_for_server_requirements(self):
        client = Mock()
        client.deadline = -1
        client.request.side_effect = [
            {"state": "open", "mergeable": None, "mergeable_state": "blocked"},
            {"state": "open", "mergeable": True, "mergeable_state": "clean"},
            {"state": "open", "mergeable": True, "mergeable_state": "clean"},
            {"object": {"sha": "different"}},
            {"tree": {"sha": "different"}, "parents": []},
        ]
        value = {
            "pr": 1,
            "candidate_sha": "a" * 40,
            "base_sha": "b" * 40,
            "tree_sha": "c" * 40,
            "branch": "fixture",
        }
        with (
            patch.object(
                promotion, "request", return_value={"merged": True, "sha": "a" * 40}
            ) as mutate,
            patch.object(promotion, "pause") as pause,
        ):

            def still_pending(*args):
                mutate.assert_not_called()

            pause.side_effect = still_pending
            self.assertEqual(promotion.merge(client, "fixture", value, {}), "a" * 40)
            pause.assert_called_once()
            mutate.assert_called_once()

    @patch.dict(os.environ, {enforcement.FLAG: "false"})
    def test_publication_merge_release_receipts_and_finalization_disabled(self):
        """Real artifact serialization through phases, mocked remote operations.

        All software verdicts/provenance are deliberately bad; API results and
        source/image identifiers remain usable. No skipped check becomes a pass.
        """
        sha, tree, base = "a" * 40, "b" * 40, "c" * 40
        profile = quota_fixtures.QuotaTests().profile()
        metadata = {
            "run_id": "7",
            "issue": 8,
            "quota_issue": 9,
            "base_sha": base,
            "affected_sha": base,
            "deadline": 1,
            "alert": {
                "environment": "development",
                "incident_key": "d" * 64,
                "service": "api",
            },
            "enforcement": enforcement.evidence(),
        }
        payload = json.dumps(
            {
                "schema": 1,
                "base_sha": base,
                "incident_key": "wrong",
                "files": {"README.md": base64.b64encode(b"actual bytes").decode()},
            }
        ).encode()
        checked = {
            "tree_sha": tree,
            "timestamp": int(time.time()),
            "message": "actual commit",
            "candidate_passed": None,
            "affected_reproduced": None,
            "main_reproduced": None,
        }
        reviewed = {"verdict": "fail", "findings": ["fixture finding"]}
        artifacts = {
            "candidate.json": payload,
            "checks.json": json.dumps(checked).encode(),
            "review.json": json.dumps(reviewed).encode(),
        }
        remote = Mock()
        remote.request.return_value = {}

        def broker_request(method, path, body=None):
            if path == "/git/commits/" + base:
                return {"tree": {"sha": base}}
            if path == "/git/blobs":
                return {"sha": "bad-policy-digest"}
            if path == "/git/trees":
                return {"sha": tree}
            if path == "/git/commits":
                return {"sha": sha}
            if path == "/pulls":
                self.assertIn("Incident enforcement is disabled", body["body"])
                return {
                    "number": 12,
                    "head": {"sha": sha},
                    "base": {"ref": "main"},
                    "state": "open",
                }
            return {}

        broker = Mock()
        broker.branch = "incident/development/" + "d" * 16
        broker.request.side_effect = broker_request
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "outputs"
            output.touch()
            (root / "oncall-publisher-token.json").write_text('{"token":"fixture"}')
            env = {
                "RUNNER_TEMP": directory,
                "GITHUB_WORKSPACE": directory,
                "GITHUB_OUTPUT": str(output),
                "GH_TOKEN": "fixture",
                "INCIDENT_DEADLINE": "1",
                "PINNED_CANDIDATE_SHA": sha,
                "ADMISSION_SHA256": "bad",
                "PUBLICATION_SHA256": "bad",
                "FIXER_RESULT": "failure",
                "CHECKS_RESULT": "failure",
                "REVIEWER_RESULT": "failure",
                "CANDIDATE_ELIGIBLE": "false",
                "PROFILE_SHA256": "bad",
                "CANDIDATE_SHA256": "bad",
                "CHECKS_SHA256": "bad",
                "REVIEW_SHA256": "bad",
            }
            with (
                patch.dict(os.environ, env),
                patch.object(publisher, "context", return_value=(metadata, profile)),
                patch.object(publisher, "GitHub", return_value=remote),
                patch.object(publisher, "Broker", return_value=broker),
                patch.object(
                    publisher,
                    "download",
                    side_effect=lambda name, expected: {
                        key: artifacts[key] for key in expected
                    },
                ),
                patch.object(
                    Path, "stat", return_value=SimpleNamespace(st_mode=0o600, st_uid=0)
                ),
                patch.object(publisher.os, "getuid", return_value=0, create=True),
            ):
                publisher.main()
            published = json.loads(
                (root / "oncall-publication/publication.json").read_bytes()
            )
            self.assertFalse(published["enforcement"]["enabled"])
            self.assertIsNone(checked["candidate_passed"])
            merged = Mock()
            merged.deadline = 1
            merged.request.return_value = {
                "tree": {"sha": "different"},
                "parents": [],
                "state": "open",
                "mergeable": True,
                "mergeable_state": "clean",
            }
            with (
                patch.dict(os.environ, env),
                patch.object(
                    promotion, "request", return_value={"merged": True, "sha": sha}
                ),
                patch.object(
                    promotion,
                    "candidate_ci",
                    side_effect=AssertionError("CI policy must skip"),
                ),
                patch.object(
                    promotion,
                    "candidate_authorization",
                    side_effect=AssertionError("authorization policy must skip"),
                ),
            ):
                actual_sha = promotion.merge(merged, "fixture", published, metadata)
                self.assertEqual(actual_sha, sha)
                release = {
                    "affected_sha": sha,
                    "image_digest": "sha256:" + "e" * 64,
                    "deployment_id": 4,
                    "deployment_run": 5,
                }
                with (
                    patch.object(promotion, "development_run", return_value=5),
                    patch.object(promotion, "deployed_release", return_value=release),
                ):
                    actual_release = promotion.wait_development(
                        merged, sha, lambda: None
                    )
                proof = promotion.recover(
                    merged,
                    "development",
                    actual_release,
                    profile,
                    metadata,
                    lambda: None,
                )
                receipts.write(
                    "development",
                    metadata,
                    published,
                    {"release": release, "recovery": proof, "merged_sha": sha},
                )
                receipt = (root / "oncall-development/receipt.json").read_bytes()
                with patch.object(
                    receipts, "download", return_value={"receipt.json": receipt}
                ):
                    value = receipts.read("development", "f" * 64, metadata, published)
                self.assertFalse(value["recovery"]["recovery_verified"])
                dispatch = {
                    "workflow_run_id": 6,
                    "run_url": promotion.GITHUB + "/actions/runs/6",
                    "html_url": "https://github.com/alanlima/pawlocal/actions/runs/6",
                }
                production_release = release | {"deployment_run": 6}
                merged.token = "fixture"
                merged.request.side_effect = lambda method, path, body=None: (
                    {"object": {"sha": "different"}}
                    if path == "/git/ref/heads/main"
                    else {
                        "id": 6,
                        "status": "completed",
                        "conclusion": "success",
                        "run_attempt": 2,
                    }
                )
                with (
                    patch.object(promotion, "wait_development", return_value=release),
                    patch.object(promotion, "request", return_value=dispatch),
                    patch.object(
                        promotion, "deployed_release", return_value=production_release
                    ),
                ):
                    actual_production = promotion.promote(
                        merged, sha, expected_development={"different": True}
                    )
                self.assertEqual(actual_production, production_release)
                production_proof = promotion.recover(
                    merged,
                    "production",
                    actual_production,
                    profile,
                    metadata,
                    lambda: None,
                )
                self.assertFalse(production_proof["recovery_verified"])
                receipts.write(
                    "production",
                    metadata,
                    published,
                    {
                        "release": actual_production,
                        "recovery": production_proof,
                        "merged_sha": sha,
                    },
                )
                production_receipt = (
                    root / "oncall-production/receipt.json"
                ).read_bytes()
                with patch.object(
                    receipts,
                    "download",
                    return_value={"receipt.json": production_receipt},
                ):
                    os.environ["PRODUCTION_SHA256"] = "f" * 64
                    self.assertEqual(
                        finalize.complete(merged, metadata, profile, published),
                        (sha, 6),
                    )
        calls, summary, error = finalizer_fixtures.FinalizerTests().run_finalizer(
            PAWLOCAL_ONCALL_ENFORCE_GUARDS="false",
            ADMITTED="true",
            PROMOTER_RESULT="success",
            PUBLICATION_SHA256="b" * 64,
        )
        self.assertIsNone(error)
        self.assertIn("RELEASE_COMPLETED_UNVERIFIED", summary)
        self.assertFalse(any(method == "PATCH" for method, _, _ in calls))


if __name__ == "__main__":
    unittest.main()
