from __future__ import annotations

import fnmatch
import re
import unittest
from pathlib import Path

WORKFLOWS = Path(".github/workflows")


def workflow_paths(workflow: str, event: str | None = None) -> list[str]:
    """Collect path patterns from automatic pull_request and push triggers."""
    lines = (WORKFLOWS / workflow).read_text(encoding="utf-8-sig").splitlines()
    patterns: list[str] = []
    in_event = False
    in_paths = False
    for line in lines:
        event_match = re.match(r"^  (pull_request|push):\s*$", line)
        if event_match:
            in_event = event is None or event_match.group(1) == event
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


def matches(workflow: str, path: str, event: str | None = None) -> bool:
    included = False
    for pattern in workflow_paths(workflow, event):
        if pattern.startswith("!"):
            if fnmatch.fnmatchcase(path, pattern[1:]):
                included = False
        elif fnmatch.fnmatchcase(path, pattern):
            included = True
    return included


class WorkflowPathTests(unittest.TestCase):
    def test_reconciliation_outputs_trigger_development_release_in_both_events(self) -> None:
        workflow = "fullstack-release.yml"
        for event in ("pull_request", "push"):
            with self.subTest(event=event):
                self.assertTrue(
                    matches(workflow, "infra/terraform/modules/pawlocal-environment/outputs.tf", event)
                )
                for path in (
                    "infra/terraform/modules/pawlocal-environment/main.tf",
                    "infra/terraform/modules/pawlocal-environment/iam.tf",
                    "infra/terraform/iam-bootstrap/outputs.tf",
                    "infra/terraform/iam-bootstrap/main.tf",
                    "infra/terraform/environments/production/outputs.tf",
                    "infra/terraform/environments/production/main.tf",
                ):
                    with self.subTest(path=path):
                        self.assertFalse(matches(workflow, path, event))

    def test_development_seed_dispatch_relies_on_environment_approval(self) -> None:
        workflow = (WORKFLOWS / "development-dsql-seed.yml").read_text(
            encoding="utf-8-sig"
        )
        dispatch_config = workflow.split("  workflow_dispatch:", 1)[1].split(
            "\n\npermissions:", 1
        )[0]
        seed_job = workflow.split("  seed:\n", 1)[1].split("    steps:\n", 1)[0]
        target_guard = workflow.split(
            "      - name: Confirm the development-only target", 1
        )[1].split("      - name: Set up Python", 1)[0]

        self.assertNotIn("inputs:", dispatch_config)
        self.assertNotIn("confirm_seed", workflow)
        self.assertIn("if: github.ref == 'refs/heads/main'", seed_job)
        self.assertIn("environment: development-seed", seed_job)
        self.assertIn(
            '[[ "$GITHUB_REF" == "refs/heads/main" ]]',
            target_guard,
        )

    def test_development_seed_masks_live_targets_before_use(self) -> None:
        workflow = (WORKFLOWS / "development-dsql-seed.yml").read_text(
            encoding="utf-8-sig"
        )
        job_env = workflow.split("    env:\n", 1)[1].split("\n    steps:\n", 1)[0]
        guard = workflow.split("      - name: Confirm the development-only target", 1)[1].split(
            "      - name: Set up Python", 1
        )[0]
        oidc = workflow.split(
            "      - name: Configure development app-role credentials with GitHub OIDC", 1
        )[1].split("      - name: Seed the fixed development catalog", 1)[0]
        seed = workflow.split("      - name: Seed the fixed development catalog", 1)[1].split(
            "      - name: Verify seeded records through development API", 1
        )[0]
        api = workflow.split(
            "      - name: Verify seeded records through development API", 1
        )[1].split("      - name: Upload seed outcome", 1)[0]

        self.assertNotIn("vars.", workflow)
        for name in (
            "PAWLOCAL_AWS_ACCOUNT_ID",
            "PAWLOCAL_DSQL_SEED_ROLE_ARN",
            "PAWLOCAL_DSQL_ENDPOINT",
            "PAWLOCAL_API_HEALTH_URL",
            "PAWLOCAL_DATABASE_URL",
        ):
            self.assertNotIn(name, job_env)
        for name in (
            "PAWLOCAL_AWS_ACCOUNT_ID",
            "PAWLOCAL_DSQL_SEED_ROLE_ARN",
            "PAWLOCAL_DSQL_ENDPOINT",
            "PAWLOCAL_API_HEALTH_URL",
        ):
            self.assertIn(f"{name}: ${{{{ secrets.{name} }}}}", guard)
        self.assertIn("printf '::add-mask::%s\\n' \"$api_host\"", guard)
        self.assertIn("role-to-assume: ${{ secrets.PAWLOCAL_DSQL_SEED_ROLE_ARN }}", oidc)
        self.assertIn("mask-aws-account-id: true", oidc)
        self.assertIn(
            "PAWLOCAL_EXPECTED_DSQL_ENDPOINT: ${{ secrets.PAWLOCAL_DSQL_ENDPOINT }}",
            seed,
        )
        self.assertIn(
            "PAWLOCAL_DSQL_ENDPOINT: ${{ secrets.PAWLOCAL_DSQL_ENDPOINT }}",
            seed,
        )
        self.assertIn("PAWLOCAL_DATABASE_URL=\"auroradsql+psycopg://", seed)
        self.assertLess(
            seed.index("printf '::add-mask::%s\\n' \"$PAWLOCAL_DATABASE_URL\""),
            seed.index("export PAWLOCAL_DATABASE_URL"),
        )
        self.assertIn(
            "PAWLOCAL_API_HEALTH_URL: ${{ secrets.PAWLOCAL_API_HEALTH_URL }}",
            api,
        )

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

    def test_production_promotion_uses_matching_environment_state(self) -> None:
        workflow = (WORKFLOWS / "deploy-production.yml").read_text(encoding="utf-8")
        self.assertIn("uses: ./.github/workflows/terraform-environment.yml", workflow)
        self.assertIn("environment: production", workflow)
        self.assertIn("release_only: true", workflow)
        self.assertIn("ref: ${{ inputs.release_commit }}", workflow)
        self.assertNotIn("pawlocal/terraform.tfstate", workflow)

    def test_production_ancestry_gate_precedes_any_terraform_plan(self) -> None:
        workflow = (WORKFLOWS / "terraform-environment.yml").read_text()
        eligibility = workflow.index("  production-eligibility:")
        ancestry_gate = workflow.index("compareCommitsWithBasehead")
        plan = workflow.index("  plan:")
        self.assertLess(eligibility, ancestry_gate)
        self.assertLess(ancestry_gate, plan)
        self.assertIn("needs: production-eligibility", workflow[plan:])
        self.assertIn("basehead: `${commit}...main`", workflow)

        promotion = (WORKFLOWS / "deploy-production.yml").read_text()
        self.assertNotIn("git fetch --no-tags --depth=1", promotion)
        self.assertNotIn("git merge-base --is-ancestor", promotion)
        self.assertIn('test "$(git rev-parse HEAD)" = "$RELEASE_COMMIT"', promotion)

    def test_production_promotion_requires_expected_successful_workflow_and_validated_evidence(self) -> None:
        workflow = (WORKFLOWS / "terraform-environment.yml").read_text()
        self.assertIn("workflow_id: 'fullstack-release.yml'", workflow)
        self.assertIn("github.rest.actions.listWorkflowRuns", workflow)
        self.assertIn("run.head_branch === 'main'", workflow)
        self.assertIn("run.event === 'push'", workflow)
        self.assertIn("run.conclusion === 'success'", workflow)
        self.assertIn("statuses.data.reduce((value, item)", workflow)
        self.assertIn("latest?.state === 'success'", workflow)
        self.assertIn("payload.backend_image === image", workflow)
        self.assertIn("payload.evidence_validated === true", workflow)
        self.assertIn("payload.manifest_schema_version === 2", workflow)
        self.assertIn("payload.evidence_schema_version === 1", workflow)
        self.assertIn("payload.release_commit === commit", workflow)
        self.assertIn("payload.release_manifest_digest", workflow)
        self.assertIn("payload.verification_evidence_digest", workflow)
        self.assertIn("payload.running_image_digest === payload.backend_image_digest", workflow)
        self.assertIn("successfulRunIds.has(workflowRun)", workflow)
        self.assertIn("payload.database_provider === 'aurora_dsql'", workflow)
        self.assertIn("payload.public_endpoint_health?.api === true", workflow)
        self.assertIn("payload.database_query_smoke?.result === 'valid_place_page'", workflow)
        self.assertIn("environment: 'development'", workflow)
        self.assertIn("matching validated full-stack release evidence", workflow)

    def test_development_evidence_is_validated_before_it_is_recorded(self) -> None:
        workflow = (WORKFLOWS / "fullstack-release.yml").read_text()
        validation = workflow.index("- name: Validate development verification evidence")
        record = workflow.index("- name: Record successful verified development deployment")
        self.assertLess(validation, record)
        self.assertIn("--evidence release/development-verification.json", workflow[validation:record])
        for field in (
            "record_schema_version",
            "manifest_schema_version",
            "evidence_schema_version",
            "evidence_validated",
            "workflow_run_attempt",
            "release_manifest_digest",
            "verification_evidence_digest",
            "backend_image_digest",
            "running_image_digest",
            "frontend_artifact_digest",
            "public_endpoint_health",
            "database_query_smoke",
        ):
            with self.subTest(field=field):
                self.assertIn(field, workflow[record:])


if __name__ == "__main__":
    unittest.main()
