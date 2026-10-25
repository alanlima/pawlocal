import os
from unittest.mock import patch
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


@patch.dict(os.environ, {'PAWLOCAL_ONCALL_ENFORCE_GUARDS': 'true'})
class IncidentWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.raw = (ROOT / ".github/workflows/incident-responder.yml").read_text()
        self.workflow = yaml.safe_load(self.raw)

    def test_global_queue_has_exact_required_contract(self):
        self.assertEqual(
            self.workflow["concurrency"],
            {"group": "pawlocal-oncall-global-quota", "cancel-in-progress": False, "queue": "max"},
        )

    def test_environment_override_is_resolved_at_runtime_then_pinned_for_every_phase(self):
        flag = "PAWLOCAL_ONCALL_ENFORCE_GUARDS"
        self.assertNotIn(flag, self.workflow.get("env", {}))
        preflight = self.workflow["jobs"]["preflight"]
        self.assertEqual(preflight["environment"], "oncall-${{ inputs.environment }}")
        self.assertNotIn("if", preflight)
        resolver = next(step for step in preflight["steps"] if step.get("id") == "enforcement")
        self.assertIn("vars."+flag, resolver["env"][flag])
        self.assertIn("python ops/incident-response/enforcement.py", resolver["run"])
        self.assertEqual(preflight["outputs"]["enforce_guards"], "${{ steps.enforcement.outputs.enforce_guards }}")
        for name, job in self.workflow["jobs"].items():
            if name != "preflight":
                with self.subTest(phase=name):
                    self.assertEqual(job["env"][flag], "${{ needs.preflight.outputs.enforce_guards }}")

    def test_direct_lint_exception_preserves_other_errors(self):
        ci = yaml.safe_load((ROOT / ".github/workflows/workflow-validation.yml").read_text())
        steps = [step for job in ci["jobs"].values() for step in job.get("steps", [])]
        script = next(step["run"] for step in steps if step.get("name") == "Lint workflow syntax and security")
        self.assertEqual(script, "actionlint")
        config = (ROOT / ".github/actionlint.yaml").read_text()
        self.assertEqual(yaml.safe_load(config), {"paths": {
            ".github/workflows/incident-responder.yml": {"ignore": [
                '^unexpected key "queue" for "concurrency" section\\. expected one of "cancel-in-progress", "group"$'
            ]}
        }})
        self.assertFalse((ROOT / ".github/scripts/lint-workflows.py").exists())
        if not shutil.which("actionlint"):
            if os.environ.get("GITHUB_ACTIONS") == "true":
                self.fail("Hosted lint regression requires installed actionlint")
            self.skipTest("actionlint is not installed locally")
        with tempfile.TemporaryDirectory() as temporary:
            repository = Path(temporary)
            (repository / ".git").mkdir()
            workflows = repository / ".github/workflows"
            workflows.mkdir(parents=True)
            (repository / ".github/actionlint.yaml").write_text(config)
            path = workflows / "incident-responder.yml"
            for extra, accepted in (("", True), ("    unexpected-job-key: true\n", False)):
                path.write_text(
                    "name: Fixture\non: push\nconcurrency:\n  group: fixture\n  queue: max\njobs:\n  fixture:\n    runs-on: ubuntu-24.04\n"
                    + extra + "    steps:\n      - run: echo fixture\n"
                )
                result = subprocess.run(
                    ["actionlint", str(path)],
                    check=False, capture_output=True, cwd=repository,
                )
                self.assertEqual(result.returncode == 0, accepted)
            path.write_text(path.read_text().replace("    unexpected-job-key: true\n", ""))
            other = workflows / "ordinary.yml"
            path.rename(other)
            result = subprocess.run(["actionlint", str(other)], check=False, capture_output=True, cwd=repository)
            self.assertNotEqual(result.returncode, 0)

    def test_model_executions_have_no_app_query_production_or_write_capability(self):
        jobs = self.workflow["jobs"]
        for name in ("fixer", "reviewer"):
            job = jobs[name]
            self.assertEqual(
                job["permissions"],
                {"contents": "read", "actions": "read", "issues": "read"},
            )
            self.assertIn("INCIDENT_DEADLINE", job["env"])
            model = [
                step
                for step in job["steps"]
                if step.get("uses", "").startswith("openai/codex-action@")
            ]
            self.assertEqual(len(model), 1)
            step = model[0]
            self.assertEqual(step["with"]["codex-version"], "0.163.0")
            self.assertEqual(step["with"]["safety-strategy"], "unprivileged-user")
            self.assertEqual(step["with"]["codex-user"], "oncall")
            self.assertEqual(
                step["with"]["responses-api-endpoint"],
                "http://127.0.0.1:8765/v1/responses",
            )
            self.assertEqual(
                step["with"]["openai-api-key"],
                "${{ steps.runtime.outputs.local_token }}",
            )
            self.assertEqual(step["env"]["ACTIONS_RUNTIME_TOKEN"], "")
            self.assertNotIn("secrets.", str(step))
            self.assertNotIn("PAWLOCAL_GRAFANA_QUERY_TOKEN", str(job))
            self.assertNotIn("PUBLISHER_APP_PRIVATE_KEY", str(job))

    def test_only_trusted_preflight_publisher_write_issues_and_neither_executes_candidate(
        self,
    ):
        jobs = self.workflow["jobs"]
        writers = [
            name
            for name, job in jobs.items()
            if job.get("permissions", {}).get("issues") == "write"
        ]
        self.assertEqual(writers, ["preflight", "publisher", "finalize"])
        for name in writers:
            self.assertFalse(
                any(
                    step.get("uses", "").startswith("openai/")
                    for step in jobs[name]["steps"]
                )
            )
        self.assertEqual(
            jobs["publisher"]["needs"], ["preflight", "fixer", "checks", "reviewer"]
        )
        self.assertIn("!cancelled()", jobs["publisher"]["if"])
        self.assertIn("needs.fixer.outputs.candidate_sha256 != ''", jobs["publisher"]["if"])
        self.assertIn("always()", jobs["finalize"]["if"])
        self.assertIn("vars.PAWLOCAL_GRAFANA_URL", self.raw)
        self.assertNotIn("vars.PAWLOCAL_GRAFANA_STACK_URL", self.raw)

    def test_merge_and_promotion_have_separate_credentials_and_no_candidate_execution(
        self,
    ):
        jobs = self.workflow["jobs"]
        self.assertEqual(jobs["merge"]["permissions"]["contents"], "read")
        self.assertEqual(jobs["merge"]["permissions"]["actions"], "read")
        self.assertEqual(jobs["promote"]["permissions"]["actions"], "write")
        self.assertNotIn("PUBLISHER_APP_PRIVATE_KEY", str(jobs["promote"]))
        for name in ("merge", "promote"):
            self.assertIn("PROMOTION_DEADLINE", jobs[name]["env"])
            self.assertFalse(
                any(
                    step.get("uses", "").startswith("openai/")
                    for step in jobs[name]["steps"]
                )
            )
            self.assertFalse(
                any("candidate" in step.get("run", "") for step in jobs[name]["steps"])
            )

    def test_failed_model_steps_always_show_bounded_trusted_gateway_diagnostics(self):
        for name in ("fixer", "reviewer"):
            steps = self.workflow["jobs"][name]["steps"]
            model_index = next(i for i, step in enumerate(steps) if step.get("uses", "").startswith("openai/codex-action@"))
            diagnostic = steps[model_index + 1]
            self.assertEqual(diagnostic["name"], "Show quota gateway failure diagnostics")
            self.assertEqual(diagnostic["if"], "always()")
            self.assertIn('$RUNNER_TEMP/oncall-trusted/gateway-diagnostics.jsonl', diagnostic["run"])
            self.assertIn('head -c 65536 "$diagnostics"', diagnostic["run"])
            self.assertNotIn("inputs.", diagnostic["run"])
            self.assertNotIn("secrets.", str(diagnostic))

    def test_profile_has_no_model_or_budget_default_in_workflow(self):
        self.assertIn("vars.PAWLOCAL_ONCALL_MODEL_PROFILE", self.raw)
        self.assertNotIn("gpt-", self.raw)
        self.assertNotIn("PAWLOCAL_ONCALL_MODEL_PROFILE ||", self.raw)

    def test_recovery_receipts_gate_promotion_and_always_finalizer(self):
        jobs = self.workflow["jobs"]
        development, production, finalizer = (
            jobs[name] for name in ("development_recovery", "promote", "finalize")
        )
        self.assertEqual(development["environment"], "oncall-development")
        self.assertEqual(production["environment"], "oncall-production")
        self.assertIn("development_recovery", production["needs"])
        self.assertIn("development_sha256", production["if"])
        self.assertIn("always()", finalizer["if"])
        self.assertEqual(set(finalizer["needs"]), set(jobs) - {"finalize"})
        for job in (development, production):
            self.assertIn(
                "needs.publisher.outputs.promotion_deadline",
                job["env"]["PROMOTION_DEADLINE"],
            )
            self.assertEqual(
                job["env"]["RECOVERY_API_BASE_URL"], "${{ vars.VITE_API_BASE_URL }}"
            )
            self.assertEqual(
                job["env"]["RECOVERY_FRONTEND_ORIGIN"],
                "${{ vars.PAWLOCAL_PUBLIC_BASE_URL }}",
            )
        self.assertIn("PRODUCTION_SHA256", finalizer["env"])
        self.assertIn("DEVELOPMENT_SHA256", finalizer["env"])
        self.assertNotIn("secrets.", str(finalizer))
        self.assertNotIn("id-token", str(finalizer))


if __name__ == "__main__":
    unittest.main()


@patch.dict(os.environ, {'PAWLOCAL_ONCALL_ENFORCE_GUARDS': 'true'})
class IncidentUsageWorkflowTests(unittest.TestCase):
    def test_always_reports_no_claim_failures_and_skipped_models_without_mutation(self):
        jobs = yaml.safe_load((ROOT / ".github/workflows/incident-responder.yml").read_text())["jobs"]
        self.assertEqual(len(jobs), 9)
        self.assertEqual(jobs["finalize"]["if"], "always() && (needs.preflight.outputs.enforce_guards != 'true' || (github.ref == 'refs/heads/main' && github.run_attempt == 1))")
        finalizer = next(step for step in jobs["finalize"]["steps"] if step.get("run") == "python ops/incident-response/finalize.py")
        self.assertEqual(finalizer["if"], "needs.preflight.outputs.issue != ''")
        for name in ("preflight", "fixer", "reviewer", "finalize"):
            step = next(step for step in jobs[name]["steps"] if "usage_summary.py" in step.get("run", ""))
            self.assertEqual(step["if"], "always()")
        summary = jobs["finalize"]["steps"][-1]
        self.assertIn("needs.preflight.outputs.usage_limits", summary["env"]["USAGE_LIMITS"])
        self.assertIn("needs.fixer.outputs.usage", summary["env"]["FIXER_USAGE"])
        self.assertIn("needs.reviewer.result", summary["env"]["REVIEWER_RESULT"])
