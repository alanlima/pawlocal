from __future__ import annotations

import argparse
import contextlib
import copy
import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
import urllib.parse
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / ".github/scripts/reconcile-environment-outputs.py"
ALLOWLIST = ROOT / ".github/generated-output-allowlist.json"
WORKFLOW = ROOT / ".github/workflows/terraform-environment.yml"


def load_module():
    spec = importlib.util.spec_from_file_location("output_reconciliation", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load reconciliation helper")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def output(value):
    return {"value": value, "type": "dynamic", "sensitive": False}


def states(environment: str = "development", phase: str = "ready") -> tuple[dict, dict]:
    principal = f"arn:aws:iam::000000000000:role/example-{environment}-principal"
    runtime = f"arn:aws:iam::000000000000:role/example-{environment}-runtime"
    bootstrap_principal = principal
    bootstrap_runtime = runtime
    environment_runtime = runtime
    if phase == "foundation":
        bootstrap_principal = None
        bootstrap_runtime = None
        environment_runtime = None
    elif phase == "bootstrap-handoff":
        environment_runtime = None
    elif phase == "stale-bootstrap":
        bootstrap_principal = "arn:aws:iam::000000000000:role/example-stale-principal"
        environment_runtime = None
    bootstrap = {
        "version": 4,
        "lineage": "example-bootstrap-lineage",
        "serial": 7,
        "outputs": {
            "terraform_role_arns": output(
                {
                    f"{environment}-plan": f"arn:aws:iam::000000000000:role/example-{environment}-plan",
                    f"{environment}-apply": f"arn:aws:iam::000000000000:role/example-{environment}-apply",
                }
            ),
            "aws_account_id": output("000000000000"),
            "plan_transfer_bucket_name": output("example-private-plan-bucket"),
            "identity_app_role_arns": output(
                {
                    f"{environment}_frontend": f"arn:aws:iam::000000000000:role/example-{environment}-publisher",
                    f"{environment}_runtime": bootstrap_runtime,
                }
            ),
            "runtime_lightsail_principal_arns": output({environment: bootstrap_principal}),
        },
        "resources": [{"type": "example_bootstrap_resource"}],
    }
    targets = {
        "environment": environment,
        "frontend_url": f"https://{environment}.example.invalid",
        "api_base_url": f"https://api-{environment}.example.invalid/api/v1",
        "api_health_url": f"https://api-{environment}.example.invalid/health",
        "frontend_bucket": f"example-{environment}-bucket",
        "cloudfront_distribution_id": f"EXAMPLE{environment.upper()}",
        "cloudfront_distribution_arn": f"arn:aws:cloudfront::000000000000:distribution/example-{environment}",
        "cloudfront_oac_arn": f"arn:aws:cloudfront::000000000000:origin-access-control/example-{environment}",
        "lightsail_principal_arn": principal,
        "runtime_role_arn": environment_runtime,
        "cognito_client_id": f"example-{environment}-client",
        "cognito_domain": f"https://auth-{environment}.example.invalid",
        "cognito_redirect_uri": f"https://{environment}.example.invalid/auth/callback",
        "cognito_logout_uri": f"https://{environment}.example.invalid/",
        "cognito_scopes": "openid email profile",
    }
    environment_state = {
        "version": 4,
        "lineage": f"example-{environment}-lineage",
        "serial": 11,
        "outputs": {"environment_targets": output(targets)},
        "resources": [{"type": "example_environment_resource"}],
    }
    return bootstrap, environment_state


class FakeClient:
    def __init__(self):
        self.variables: dict[tuple[str, str], str] = {}
        self.secrets: dict[str, set[str]] = {"development": set(), "production": set()}
        self.fail_once: set[tuple[str, str]] = set()
        self.ignore_writes: set[tuple[str, str]] = set()
        self.workflow_runs: list[dict] = []
        self.deployments: list[dict] = []
        self.statuses: dict[int, list[dict]] = {}

    def request(self, method, path, payload=None, allowed=(200,)):
        module = sys.modules["output_reconciliation"]
        decoded = urllib.parse.unquote(path)
        if "/variables" in decoded:
            before, after = decoded.split("/variables", 1)
            environment = before.split("/environments/", 1)[1]
            name = after.lstrip("/") or None
            key = (environment, name or "")
            if name and key in self.fail_once:
                self.fail_once.remove(key)
                raise module.ReconciliationError("simulated API failure")
            if method == "GET" and name:
                if key not in self.variables:
                    return module.ApiResponse(404, None)
                return module.ApiResponse(200, {"name": name, "value": self.variables[key]})
            if method == "POST":
                key = (environment, payload["name"])
                if key not in self.ignore_writes:
                    self.variables[key] = payload["value"]
                return module.ApiResponse(201, None)
            if method == "PATCH":
                if key not in self.ignore_writes:
                    self.variables[key] = payload["value"]
                return module.ApiResponse(204, None)
            if method == "DELETE":
                self.variables.pop(key, None)
                return module.ApiResponse(204, None)
        if "/secrets" in decoded:
            before, after = decoded.split("/secrets", 1)
            environment = before.split("/environments/", 1)[1]
            name = after.split("?", 1)[0].lstrip("/") or None
            if method == "GET":
                return module.ApiResponse(200, {"secrets": [{"name": item} for item in sorted(self.secrets[environment])]})
            if method == "DELETE" and name:
                self.secrets[environment].discard(name)
                return module.ApiResponse(204, None)
        if "/actions/workflows/" in decoded:
            return module.ApiResponse(200, {"workflow_runs": self.workflow_runs})
        if method == "GET" and decoded.endswith("/statuses?per_page=100"):
            deployment_id = int(decoded.rsplit("/", 2)[1])
            return module.ApiResponse(200, self.statuses.get(deployment_id, []))
        if method == "GET" and "/deployments?" in decoded:
            return module.ApiResponse(200, self.deployments)
        raise AssertionError((method, decoded, payload, allowed))


class OutputReconciliationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.module = load_module()
        self.allowlist = self.module.load_allowlist(ALLOWLIST)

    def plan(self, environment="development", phase="ready"):
        bootstrap, environment_state = states(environment, phase)
        return self.module.build_plan(self.allowlist, environment, "reconcile", bootstrap, environment_state)

    def test_fixed_mapping_supports_development_and_production(self) -> None:
        for environment in ("development", "production"):
            with self.subTest(environment=environment):
                plan = self.plan(environment)
                targets = {entry["target"] for entry in plan["entries"]}
                self.assertEqual(targets, {environment, f"{environment}-plan", f"{environment}-apply"})
                self.assertFalse(plan["optional_first_stage_missing"])
                self.assertEqual(len(plan["entries"]), 24)

    def test_allowlist_rejects_unknown_output_target_and_variable(self) -> None:
        for field, value in (
            ("output", "unapproved_output"),
            ("targets", ["other-environment"]),
            ("variable", "UNAPPROVED_VARIABLE"),
        ):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as directory:
                changed = copy.deepcopy(self.allowlist)
                changed["mappings"][0][field] = value
                path = Path(directory) / "allowlist.json"
                path.write_text(json.dumps(changed), encoding="utf-8")
                with self.assertRaises(self.module.ReconciliationError):
                    self.module.load_allowlist(path)

    def test_cross_environment_state_is_rejected(self) -> None:
        bootstrap, production_state = states("production")
        with self.assertRaises(self.module.ReconciliationError):
            self.module.build_plan(self.allowlist, "development", "reconcile", bootstrap, production_state)

    def test_runtime_handoff_stays_incomplete_until_both_states_match(self) -> None:
        foundation = self.plan(phase="foundation")
        bootstrap_handoff = self.plan(phase="bootstrap-handoff")
        stale = self.plan(phase="stale-bootstrap")
        ready = self.plan(phase="ready")
        runtime_values = lambda plan: {
            entry["value"] for entry in plan["entries"] if entry["variable"] == "PAWLOCAL_RUNTIME_ROLE_ARN"
        }
        self.assertEqual(runtime_values(foundation), {None})
        self.assertEqual(runtime_values(stale), {None})
        self.assertNotEqual(runtime_values(bootstrap_handoff), {None})
        self.assertTrue(foundation["optional_first_stage_missing"])
        self.assertTrue(bootstrap_handoff["optional_first_stage_missing"])
        self.assertTrue(stale["optional_first_stage_missing"])
        self.assertFalse(ready["optional_first_stage_missing"])

    def test_destroy_invalidation_requires_empty_state_and_deletes_only_dependents(self) -> None:
        bootstrap, environment_state = states()
        with self.assertRaises(self.module.ReconciliationError):
            self.module.build_plan(self.allowlist, "development", "invalidate", bootstrap, environment_state)
        environment_state["resources"] = []
        plan = self.module.build_plan(self.allowlist, "development", "invalidate", bootstrap, environment_state)
        self.assertTrue(plan["entries"])
        self.assertTrue(all(entry["value"] is None for entry in plan["entries"]))
        self.assertEqual(
            {entry["variable"] for entry in plan["entries"]},
            set(self.allowlist["destroy_invalidation_variables"]),
        )
        self.assertNotIn("PAWLOCAL_DEPLOY_ROLE_ARN", {entry["variable"] for entry in plan["entries"]})

    def test_noop_drift_and_readback_mismatch(self) -> None:
        client = FakeClient()
        key = ("development", "PAWLOCAL_PUBLIC_BASE_URL")
        client.variables[key] = "https://development.example.invalid"
        self.assertEqual(
            self.module.set_variable(client, "example/repository", *key, "https://development.example.invalid"),
            "no-change",
        )
        self.assertEqual(
            self.module.set_variable(client, "example/repository", *key, "https://changed.example.invalid"),
            "updated",
        )
        client.ignore_writes.add(key)
        with self.assertRaises(self.module.ReconciliationError):
            self.module.set_variable(client, "example/repository", *key, "https://another.example.invalid")

    def test_partial_failure_rerun_converges(self) -> None:
        client = FakeClient()
        key = ("development", "VITE_API_BASE_URL")
        client.fail_once.add(key)
        with self.assertRaises(self.module.ReconciliationError):
            self.module.set_variable(client, "example/repository", *key, "https://api.example.invalid/api/v1")
        self.assertEqual(
            self.module.set_variable(client, "example/repository", *key, "https://api.example.invalid/api/v1"),
            "created",
        )

    def test_authentication_failure_is_value_free(self) -> None:
        with self.assertRaisesRegex(self.module.ReconciliationError, "authentication"):
            self.module.GitHubClient("")

    def test_state_change_during_reconciliation_fails_closed(self) -> None:
        bootstrap, environment_state = states()
        plan = self.module.build_plan(self.allowlist, "development", "reconcile", bootstrap, environment_state)
        changed = copy.deepcopy(environment_state)
        changed["serial"] += 1
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = {name: root / f"{name}.json" for name in ("plan", "evidence", "bootstrap", "environment")}
            paths["plan"].write_text(json.dumps(plan), encoding="utf-8")
            evidence = self.module.initial_evidence("development", "reconcile", "sha256:" + "0" * 64)
            evidence.update({"status": "mutated", "results": [], "failure": False})
            paths["evidence"].write_text(json.dumps(evidence), encoding="utf-8")
            paths["bootstrap"].write_text(json.dumps(bootstrap), encoding="utf-8")
            paths["environment"].write_text(json.dumps(changed), encoding="utf-8")
            args = argparse.Namespace(
                allowlist=str(ALLOWLIST), environment="development", repository="example/repository",
                token="example-token", api_url="https://example.invalid", plan=str(paths["plan"]),
                evidence=str(paths["evidence"]), bootstrap_state=str(paths["bootstrap"]),
                environment_state=str(paths["environment"]),
            )
            with mock.patch.object(self.module, "GitHubClient", return_value=FakeClient()):
                self.assertEqual(self.module.command_verify(args), 1)
            result = json.loads(paths["evidence"].read_text(encoding="utf-8"))
            self.assertFalse(result["ready"])
            self.assertTrue(result["failure"])

    def test_prepare_output_and_evidence_never_log_values(self) -> None:
        bootstrap, environment_state = states()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bootstrap_path = root / "bootstrap.json"
            environment_path = root / "environment.json"
            bootstrap_path.write_text(json.dumps(bootstrap), encoding="utf-8")
            environment_path.write_text(json.dumps(environment_state), encoding="utf-8")
            args = argparse.Namespace(
                allowlist=str(ALLOWLIST), environment="development", mode="reconcile",
                bootstrap_state=str(bootstrap_path), environment_state=str(environment_path),
                backend_bucket="example-state-bucket", plan=str(root / "plan.json"),
                evidence=str(root / "evidence.json"),
            )
            stream = io.StringIO()
            with mock.patch.dict(os.environ, {"GITHUB_SHA": "a" * 40}, clear=False), contextlib.redirect_stdout(stream):
                self.assertEqual(self.module.command_prepare(args), 0)
            combined = stream.getvalue() + (root / "evidence.json").read_text(encoding="utf-8")
            for raw in (
                "example-state-bucket", "example-development-bucket",
                "api-development.example.invalid", "000000000000", "example-development-runtime",
            ):
                self.assertNotIn(raw, combined)

    def test_missing_state_fails_closed_with_value_free_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            args = argparse.Namespace(
                allowlist=str(ALLOWLIST), environment="production", mode="reconcile",
                bootstrap_state=str(root / "missing-bootstrap.json"),
                environment_state=str(root / "missing-environment.json"),
                backend_bucket="example-state-bucket", plan=str(root / "plan.json"),
                evidence=str(root / "evidence.json"),
            )
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(self.module.command_prepare(args), 1)
            evidence = json.loads((root / "evidence.json").read_text(encoding="utf-8"))
            self.assertTrue(evidence["failure"])
            self.assertFalse(evidence["ready"])
            self.assertEqual(evidence["status"], "invalid-input")

    def test_latest_pending_record_invalidates_older_ready_record(self) -> None:
        client = FakeClient()
        ready = {
            "record_type": self.module.RECORD_TYPE,
            "record_schema_version": 1,
            "environment": "development",
            "source_commit": "a" * 40,
            "ready": True,
            "status": "ready",
            "staged_handoff_complete": True,
            "backend_fingerprint": "sha256:" + "1" * 64,
            "bootstrap_state_revision": "sha256:" + "2" * 64,
            "environment_state_revision": "sha256:" + "3" * 64,
            "configuration_digest": "sha256:" + "4" * 64,
            "verified_configuration_digest": "sha256:" + "4" * 64,
            "legacy_cleanup_digest": "sha256:" + "5" * 64,
        }
        client.deployments = [
            {"id": 10, "payload": ready, "creator": {"login": "example-reconciler[bot]", "type": "Bot"}},
            {"id": 11, "payload": {**ready, "ready": False, "status": "pending-terraform"}, "creator": {"login": "github-actions[bot]", "type": "Bot"}},
        ]
        client.statuses = {
            10: [{"state": "success", "creator": {"login": "example-reconciler[bot]"}}],
            11: [{"state": "pending", "creator": {"login": "github-actions[bot]"}}],
        }
        args = argparse.Namespace(
            environment="development", repository="example/repository", token="example-token",
            api_url="https://example.invalid", expected_source_commit="a" * 40,
        )
        with mock.patch.object(self.module, "GitHubClient", return_value=client), self.assertRaises(
            self.module.ReconciliationError
        ):
            self.module.command_gate(args)
        client.deployments = client.deployments[:1]
        with mock.patch.object(self.module, "GitHubClient", return_value=client):
            self.assertEqual(self.module.command_gate(args), 0)
        client.deployments[0]["creator"] = {"login": "github-actions[bot]", "type": "Bot"}
        client.statuses[10][0]["creator"] = {"login": "github-actions[bot]"}
        with mock.patch.object(self.module, "GitHubClient", return_value=client), self.assertRaises(
            self.module.ReconciliationError
        ):
            self.module.command_gate(args)

    def test_final_legacy_cleanup_is_idempotent_and_read_back(self) -> None:
        client = FakeClient()
        client.variables[("development", "PAWLOCAL_DEPLOY_MODE")] = "example-legacy-mode"
        client.secrets["development"].add("PAWLOCAL_DEPLOY_SSH_PRIVATE_KEY")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            proof = self.module.prove_legacy_unused(self.allowlist, ROOT)
            proof_path = root / "proof.json"
            proof_path.write_text(json.dumps(proof), encoding="utf-8")
            evidence_path = root / "evidence.json"
            evidence = self.module.initial_evidence("development", "reconcile", "sha256:" + "0" * 64)
            evidence.update({"status": "ready", "ready": True, "failure": False})
            evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
            args = argparse.Namespace(
                allowlist=str(ALLOWLIST), environment="development", repository="example/repository",
                token="example-token", api_url="https://example.invalid", root=str(ROOT),
                legacy_proof=str(proof_path), evidence=str(evidence_path),
            )
            with mock.patch.object(self.module, "GitHubClient", return_value=client), mock.patch.dict(
                os.environ, {"GITHUB_RUN_ID": "example-current-run"}, clear=False
            ):
                self.assertEqual(self.module.command_cleanup_legacy(args), 0)
            self.assertNotIn(("development", "PAWLOCAL_DEPLOY_MODE"), client.variables)
            self.assertNotIn("PAWLOCAL_DEPLOY_SSH_PRIVATE_KEY", client.secrets["development"])
            result = json.loads(evidence_path.read_text(encoding="utf-8"))
            self.assertTrue(result["legacy_cleanup_digest"].startswith("sha256:"))

    def test_legacy_cleanup_proof_excludes_seed_and_checks_inflight_runs(self) -> None:
        proof = self.module.prove_legacy_unused(self.allowlist, ROOT)
        self.assertTrue(proof["unused"])
        client = FakeClient()
        client.workflow_runs = [{"id": 22}]
        with mock.patch.dict(os.environ, {"GITHUB_RUN_ID": "11"}, clear=False):
            self.assertEqual(self.module.active_release_run_ids(client, "example/repository"), {"22"})
        seed = (ROOT / ".github/workflows/development-dsql-seed.yml").read_text(encoding="utf-8")
        self.assertIn("PAWLOCAL_DSQL_ENDPOINT", seed)

    def test_workflow_serializes_mutation_and_invalidates_before_apply(self) -> None:
        workflow = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("group: pawlocal-terraform-${{ inputs.environment }}", workflow)
        self.assertIn("cancel-in-progress: false", workflow)
        pending = workflow.index("Invalidate older reconciliation readiness before Terraform mutation")
        apply = workflow.index('apply_command=(terraform -chdir="$TF_ROOT" apply')
        reconcile = workflow.index("  reconcile:")
        self.assertLess(pending, apply)
        self.assertLess(apply, reconcile)
        self.assertIn("environment: ${{ format('{0}-reconcile', inputs.environment) }}", workflow)
        self.assertIn("permission-environments: write", workflow)
        self.assertIn("PAWLOCAL_RECONCILIATION_APP_PRIVATE_KEY", workflow)


if __name__ == "__main__":
    unittest.main()
