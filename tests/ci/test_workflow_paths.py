from __future__ import annotations

import fnmatch
import re
import unittest
from pathlib import Path

WORKFLOWS = Path(".github/workflows")


def workflow_paths(workflow: str) -> list[str]:
    """Collect path patterns from automatic pull_request and push triggers."""
    lines = (WORKFLOWS / workflow).read_text(encoding="utf-8-sig").splitlines()
    patterns: list[str] = []
    in_event = False
    in_paths = False
    for line in lines:
        if re.match(r"^  (pull_request|push):\s*$", line):
            in_event = True
            in_paths = False
            continue
        if in_event and re.match(r"^  [A-Za-z_][A-Za-z0-9_-]*:\s*$", line):
            in_event = False
            in_paths = False
        if in_event and re.match(r"^    paths:\s*$", line):
            in_paths = True
            continue
        if in_paths:
            match = re.match(r'^\s+-\s+["\']?([^"\']+)["\']?\s*$', line)
            if match:
                patterns.append(match.group(1))
            elif line.strip() and not line.startswith("      "):
                in_paths = False
    return patterns


def matches(workflow: str, path: str) -> bool:
    included = False
    for pattern in workflow_paths(workflow):
        if pattern.startswith("!"):
            if fnmatch.fnmatchcase(path, pattern[1:]):
                included = False
        elif fnmatch.fnmatchcase(path, pattern):
            included = True
    return included


class WorkflowPathTests(unittest.TestCase):
    def test_docs_only_changes_do_not_trigger_any_automatic_workflow(self) -> None:
        workflows = (
            "frontend-deploy.yml",
            "backend-ci.yml",
            "compose-ci.yml",
            "terraform-ci.yml",
            "workflow-validation.yml",
            "frontend-production-deploy.yml",
        )
        for workflow in workflows:
            with self.subTest(workflow=workflow):
                self.assertFalse(matches(workflow, "README.md"))
                self.assertFalse(matches(workflow, "docs/testing.md"))
                self.assertFalse(matches(workflow, "frontend/README.md"))
                self.assertFalse(matches(workflow, "backend/README.md"))
                self.assertFalse(matches(workflow, "infra/terraform/README.md"))
                self.assertFalse(matches(workflow, "observability/README.md"))
                self.assertFalse(matches(workflow, ".github/workflows/README.md"))

    def test_component_paths_trigger_only_their_component_workflow(self) -> None:
        cases = {
            "frontend/src/App.tsx": "frontend-deploy.yml",
            "backend/app/main.py": "backend-ci.yml",
            "infra/terraform/main.tf": "terraform-ci.yml",
            ".env.example": "compose-ci.yml",
            "observability/grafana/dashboard.json": "compose-ci.yml",
        }
        workflows = (
            "frontend-deploy.yml",
            "backend-ci.yml",
            "compose-ci.yml",
            "terraform-ci.yml",
        )
        for path, expected in cases.items():
            with self.subTest(path=path):
                self.assertEqual([w for w in workflows if matches(w, path)], [expected])

    def test_shared_root_inputs_trigger_relevant_checks(self) -> None:
        expected = {
            "openapi.yaml": {"frontend-deploy.yml", "backend-ci.yml", "compose-ci.yml"},
            "package-lock.json": {"frontend-deploy.yml"},
            "pyproject.toml": {"backend-ci.yml"},
            ".dockerignore": {"compose-ci.yml"},
            "frontend/Dockerfile": {"frontend-deploy.yml", "compose-ci.yml"},
            "frontend/.dockerignore": {"frontend-deploy.yml", "compose-ci.yml"},
            "backend/Dockerfile": {"backend-ci.yml", "compose-ci.yml"},
            "backend/.dockerignore": {"backend-ci.yml", "compose-ci.yml"},
        }
        workflows = (
            "frontend-deploy.yml",
            "backend-ci.yml",
            "compose-ci.yml",
            "terraform-ci.yml",
        )
        for path, expected_workflows in expected.items():
            with self.subTest(path=path):
                self.assertEqual(
                    {workflow for workflow in workflows if matches(workflow, path)},
                    expected_workflows,
                )

    def test_local_action_changes_trigger_workflow_validation(self) -> None:
        self.assertEqual(workflow_paths("workflow-validation.yml").count(".github/actions/**"), 2)
        for path in (
            ".github/actions/deploy/action.yml",
            ".github/actions/deploy/index.js",
            ".github/actions/deploy/lib/publish.js",
        ):
            with self.subTest(path=path):
                self.assertTrue(matches("workflow-validation.yml", path))

    def test_workflow_changes_trigger_validation_and_affected_frontend_check(self) -> None:
        path = ".github/workflows/frontend-production-deploy.yml"
        self.assertTrue(matches("workflow-validation.yml", path))
        self.assertTrue(matches("frontend-deploy.yml", path))

    def test_production_deploy_is_scoped_to_frontend_related_inputs(self) -> None:
        self.assertTrue(matches("frontend-production-deploy.yml", "frontend/src/App.tsx"))
        self.assertTrue(matches("frontend-production-deploy.yml", "openapi.yaml"))
        self.assertTrue(matches("frontend-production-deploy.yml", "package-lock.json"))
        self.assertTrue(matches("frontend-production-deploy.yml", ".github/workflows/frontend-production-deploy.yml"))
        self.assertFalse(matches("frontend-production-deploy.yml", "README.md"))
        self.assertFalse(matches("frontend-production-deploy.yml", "docs/testing.md"))

    def test_manual_ci_dispatch_calls_every_validation_workflow(self) -> None:
        ci = (WORKFLOWS / "ci.yml").read_text(encoding="utf-8-sig")
        self.assertIn("  workflow_dispatch:", ci)
        for workflow in (
            "frontend-deploy.yml",
            "backend-ci.yml",
            "compose-ci.yml",
            "terraform-ci.yml",
            "workflow-validation.yml",
        ):
            self.assertIn(f"uses: ./.github/workflows/{workflow}", ci)

    def test_component_workflows_support_manual_reuse(self) -> None:
        for workflow in (
            "frontend-deploy.yml",
            "backend-ci.yml",
            "compose-ci.yml",
            "terraform-ci.yml",
            "workflow-validation.yml",
        ):
            with self.subTest(workflow=workflow):
                self.assertIn("  workflow_call:", (WORKFLOWS / workflow).read_text())

    def test_component_workflow_concurrency_uses_caller_workflow_identity(self) -> None:
        for workflow, component in (
            ("frontend-deploy.yml", "pawlocal-frontend-"),
            ("backend-ci.yml", "pawlocal-backend-"),
        ):
            with self.subTest(workflow=workflow):
                text = (WORKFLOWS / workflow).read_text()
                self.assertIn("github.workflow", text)
                self.assertIn("github.event.pull_request.number || github.ref", text)
                self.assertIn(component, text)
                self.assertNotIn("github.run_id", text)

    def test_release_schema_and_validator_changes_trigger_workflow_validation(self) -> None:
        for path in (
            "ops/release-manifest.schema.json",
            "ops/deployment-evidence.schema.json",
            "ops/validate-release-metadata.py",
            "tests/ci/test_release_metadata.py",
        ):
            with self.subTest(path=path):
                self.assertTrue(matches("workflow-validation.yml", path))

    def test_historical_production_promotion_uses_current_deployment_tooling(self) -> None:
        workflow = (WORKFLOWS / "deploy-production.yml").read_text(encoding="utf-8")
        release_checkout = workflow.index("name: Check out selected release source")
        tooling_checkout = workflow.index("name: Check out current deployment tooling")
        self.assertLess(release_checkout, tooling_checkout)
        self.assertIn("ref: ${{ github.workflow_sha }}", workflow)
        self.assertIn("path: deployment-tools", workflow)
        self.assertIn("ref: ${{ inputs.release_commit }}", workflow)
        self.assertIn(
            "bash deployment-tools/ops/terraform-lightsail-container-deploy.sh production",
            workflow,
        )
        adapter = Path("ops/terraform-lightsail-container-deploy.sh").read_text(encoding="utf-8")
        self.assertIn('script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"', adapter)
        self.assertIn('root="$script_dir/../infra/terraform"', adapter)

    def test_production_promotion_requires_latest_success_with_matching_release_payload(self) -> None:
        workflow = (WORKFLOWS / "deploy-production.yml").read_text()
        self.assertIn("statuses.data.reduce((latest, status)", workflow)
        self.assertIn("latestStatus.state !== 'success'", workflow)
        self.assertNotIn("statuses.data.find(status => status.state === 'success')", workflow)
        self.assertIn("deployment.payload?.migration_chains?.[provider]", workflow)
        self.assertIn("successPayload.migration_runner === selectedChain.runner", workflow)
        self.assertIn("successPayload.migration_id === selectedChain.migration_id", workflow)
        self.assertIn("successPayload.backend_image_digest === deployment.payload.backend_image_digest", workflow)


if __name__ == "__main__":
    unittest.main()
