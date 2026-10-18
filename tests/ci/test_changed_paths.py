from __future__ import annotations

import unittest
from pathlib import Path

from scripts.ci.aggregate_results import COMPONENT_RESULTS, required_status_succeeds
from scripts.ci.classify_changed_paths import CHECKS, classify_paths


class ChangedPathTests(unittest.TestCase):
    def assert_checks(self, paths: list[str], expected: set[str]) -> None:
        self.assertEqual(
            {name for name, enabled in classify_paths(paths).items() if enabled},
            expected,
        )

    def test_docs_only_changes_skip_every_component_and_workflow_job(self) -> None:
        self.assert_checks(
            ["README.md", "docs/testing.md", "backend/README.md", "frontend/guide.mdx"],
            set(),
        )

    def test_frontend_only_change_runs_frontend(self) -> None:
        self.assert_checks(["frontend/src/App.tsx"], {"frontend"})

    def test_backend_only_change_runs_backend(self) -> None:
        self.assert_checks(["backend/app/main.py"], {"backend"})

    def test_compose_observability_and_root_configuration_paths(self) -> None:
        self.assert_checks(["docker-compose.yml"], {"compose"})
        self.assert_checks([".dockerignore"], {"compose"})
        self.assert_checks(["compose.yaml"], {"compose"})
        self.assert_checks(["observability/grafana/dashboard.json"], {"compose"})
        self.assert_checks([".env.example"], {"compose"})

    def test_root_dependency_manifests_run_their_component_checks(self) -> None:
        self.assert_checks(["package-lock.json"], {"frontend"})
        self.assert_checks(["pyproject.toml"], {"backend"})

    def test_shared_contract_runs_frontend_backend_and_compose(self) -> None:
        self.assert_checks(["openapi.yaml"], {"frontend", "backend", "compose"})

    def test_terraform_only_change_runs_terraform(self) -> None:
        self.assert_checks(["infra/terraform/main.tf"], {"terraform"})

    def test_workflow_change_runs_workflow_validation(self) -> None:
        self.assert_checks([".github/workflows/ci.yml"], set(CHECKS))
        self.assert_checks(
            [".github/workflows/frontend-production-deploy.yml"],
            {"frontend", "workflows"},
        )

    def test_mixed_changes_run_the_union_of_affected_checks(self) -> None:
        self.assert_checks(
            ["frontend/src/App.tsx", "backend/app/main.py", "infra/terraform/main.tf"],
            {"frontend", "backend", "terraform"},
        )

    def test_manual_dispatch_runs_the_full_suite(self) -> None:
        self.assertEqual(classify_paths([], run_all=True), dict.fromkeys(CHECKS, True))

    def test_frontend_deployment_workflow_only_triggers_for_frontend_or_itself(self) -> None:
        workflow = Path(".github/workflows/frontend-production-deploy.yml").read_text()
        self.assertIn('      - "frontend/**"', workflow)
        self.assertIn(
            '      - ".github/workflows/frontend-production-deploy.yml"', workflow
        )
        self.assertNotIn('      - "README.md"', workflow)
        self.assertNotIn('      - "docs/**"', workflow)
        self.assertIn("  workflow_dispatch:", workflow)

    def test_frontend_pull_request_workflow_does_not_trigger_for_docs_only(self) -> None:
        workflow = Path(".github/workflows/frontend-deploy.yml").read_text()
        self.assertIn("  pull_request:", workflow)
        self.assertIn('      - "frontend/**"', workflow)
        self.assertIn('      - ".github/workflows/frontend-deploy.yml"', workflow)
        self.assertIn(
            '      - ".github/workflows/frontend-production-deploy.yml"', workflow
        )
        self.assertNotIn('      - "README.md"', workflow)
        self.assertNotIn('      - "docs/**"', workflow)

    def test_docs_only_changes_pass_the_required_status_with_skipped_components(self) -> None:
        results = {name: "skipped" for name in COMPONENT_RESULTS}
        results["CHANGES_RESULT"] = "success"
        self.assertTrue(required_status_succeeds(results))

    def test_aggregate_fails_if_path_detection_or_an_applicable_job_fails(self) -> None:
        results = {name: "skipped" for name in COMPONENT_RESULTS}
        results["CHANGES_RESULT"] = "success"
        results["BACKEND_RESULT"] = "failure"
        self.assertFalse(required_status_succeeds(results))
        results["BACKEND_RESULT"] = "skipped"
        results["CHANGES_RESULT"] = "failure"
        self.assertFalse(required_status_succeeds(results))


if __name__ == "__main__":
    unittest.main()
