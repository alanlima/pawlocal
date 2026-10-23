import importlib.util
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "incident_workflow_lint", ROOT / ".github/scripts/lint-workflows.py"
)
lint = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(lint)


class IncidentWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.raw = (ROOT / ".github/workflows/incident-responder.yml").read_text()
        self.workflow = yaml.safe_load(self.raw)

    def test_queue_adapter_validates_exact_contract_and_changes_only_one_line(self):
        self.assertEqual(
            lint.compatible(self.raw), self.raw.replace("  queue: max\n", "", 1)
        )
        for before, after in (
            ("queue: max", "queue: single"),
            ("cancel-in-progress: false", "cancel-in-progress: true"),
            ("group: pawlocal-oncall-global-quota", "group: per-environment"),
            ("  queue: max\n", ""),
        ):
            with self.subTest(before=before), self.assertRaises(ValueError):
                lint.compatible(self.raw.replace(before, after))

    def test_model_executions_have_no_app_query_production_or_write_capability(self):
        jobs = self.workflow["jobs"]
        for name in ("fixer", "reviewer"):
            job = jobs[name]
            self.assertEqual(
                job["permissions"], {"contents": "read", "actions": "read"}
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
        self.assertEqual(writers, ["preflight", "publisher", "promote"])
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

    def test_profile_has_no_model_or_budget_default_in_workflow(self):
        self.assertIn("vars.PAWLOCAL_ONCALL_MODEL_PROFILE", self.raw)
        self.assertNotIn("gpt-", self.raw)
        self.assertNotIn("||", self.raw)


if __name__ == "__main__":
    unittest.main()
