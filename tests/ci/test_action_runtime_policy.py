from __future__ import annotations

import re
import unittest
from pathlib import Path
from typing import Any, Iterator

import yaml


WORKFLOWS = Path(".github/workflows")

EXPECTED_HOSTED_JOBS = {
    ("grafana-access-check.yml", "validate-access"),
    ("incident-responder.yml", "preflight"),
    ("incident-responder.yml", "fixer"),
    ("incident-responder.yml", "checks"),
    ("incident-responder.yml", "reviewer"),
    ("incident-responder.yml", "publisher"),
    ("incident-responder.yml", "merge"),
    ("incident-responder.yml", "promote"),
    ("backend-ci.yml", "backend"),
    ("compose-ci.yml", "compose"),
    ("deploy-production.yml", "verify-production"),
    ("development-dsql-seed.yml", "seed"),
    ("frontend-deploy.yml", "frontend"),
    ("frontend-production-deploy.yml", "disabled"),
    ("fullstack-release.yml", "publish"),
    ("fullstack-release.yml", "verify-development"),
    ("rollback-development.yml", "disabled"),
    ("cleanup-destroyed-configuration.yml", "cleanup"),
    ("reconcile-environment.yml", "validate"),
    ("reconcile-environment.yml", "reconcile"),
    ("terraform-ci.yml", "terraform"),
    ("terraform-iam-bootstrap.yml", "plan"),
    ("terraform-iam-bootstrap.yml", "apply"),
    ("terraform-current-stack-operations.yml", "disabled"),
    ("terraform-environment.yml", "apply"),
    ("terraform-environment.yml", "plan"),
    ("terraform-environment.yml", "production-eligibility"),
    ("terraform-environment-destroy.yml", "destroy-apply"),
    ("terraform-environment-destroy.yml", "destroy-plan"),
    ("terraform-environment-destroy.yml", "prepare-apply"),
    ("terraform-environment-destroy.yml", "prepare-plan"),
    ("workflow-validation.yml", "action-runtime-smoke"),
    ("workflow-validation.yml", "configuration-recovery"),
    ("workflow-validation.yml", "validate"),
}

REQUIRED_ACTION_MAJORS = {
    "actions/checkout": "v7",
    "actions/github-script": "v9",
    "actions/setup-node": "v7",
    "actions/setup-python": "v7",
    "actions/upload-artifact": "v7",
    "aws-actions/configure-aws-credentials": "v6",
    "docker/build-push-action": "v7",
    "docker/login-action": "v4",
    "docker/setup-buildx-action": "v4",
    "hashicorp/setup-terraform": "v4",
}

PINNED_ACTIONS = {"openai/codex-action": "c05cfd74ad95c626cdf05c6685e62becc3bf7813"}


def workflow_files() -> list[Path]:
    return sorted((*WORKFLOWS.glob("*.yml"), *WORKFLOWS.glob("*.yaml")))


def step_action_references(workflow: dict[str, Any]) -> Iterator[tuple[str, str]]:
    """Yield every step-level external action reference and its location.

    Job-level ``uses`` entries call reusable workflows and are intentionally outside
    this JavaScript action-runtime policy. Local actions are also repository-owned,
    so only external step references are returned.
    """

    for job_name, job in workflow.get("jobs", {}).items():
        if not isinstance(job, dict):
            continue
        for step_number, step in enumerate(job.get("steps", []), start=1):
            if not isinstance(step, dict) or "uses" not in step:
                continue
            uses = step["uses"]
            location = f"job {job_name!r}, step {step_number}"
            if not isinstance(uses, str):
                raise AssertionError(f"{location} has a non-string uses value: {uses!r}")
            if uses.startswith("./"):
                continue
            yield uses, location


def validate_action_reference(uses: str, location: str) -> tuple[str, str]:
    """Validate one external action as an approved root action at an exact major."""

    if uses == "openai/codex-action@" + PINNED_ACTIONS["openai/codex-action"]:
        if "incident-responder.yml:" not in location:
            raise AssertionError("Pinned Codex Action is reviewed only in incident-responder.yml")
        return "openai/codex-action", PINNED_ACTIONS["openai/codex-action"]
    match = re.fullmatch(
        r"(?P<action>[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)@(?P<revision>v\d+)",
        uses,
    )
    if match is None:
        raise AssertionError(
            f"{location} must use an approved owner/repository@vN reference; "
            f"subpaths, floating refs, SHAs, and unsupported external forms are "
            f"not reviewed by this policy: {uses!r}"
        )

    action = match.group("action")
    revision = match.group("revision")
    if action not in REQUIRED_ACTION_MAJORS:
        raise AssertionError(
            f"{location} uses unreviewed external action family {action!r}"
        )
    expected = REQUIRED_ACTION_MAJORS[action]
    if revision != expected:
        raise AssertionError(f"{location} must use {action}@{expected}, found {uses!r}")
    return action, revision


class ActionRuntimePolicyTests(unittest.TestCase):
    def test_every_github_hosted_job_is_pinned_to_ubuntu_24_04(self) -> None:
        hosted_jobs: set[tuple[str, str]] = set()

        for path in workflow_files():
            workflow = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
            for job_name, job in workflow.get("jobs", {}).items():
                if not isinstance(job, dict) or "runs-on" not in job:
                    continue
                hosted_jobs.add((path.name, job_name))
                self.assertEqual(
                    job["runs-on"],
                    "ubuntu-24.04",
                    f"{path}:{job_name} must not follow a floating runner label",
                )

        self.assertEqual(hosted_jobs, EXPECTED_HOSTED_JOBS)

    def test_every_external_action_uses_its_node_24_compatible_major(self) -> None:
        references: dict[str, list[tuple[str, str]]] = {
            action: [] for action in (REQUIRED_ACTION_MAJORS | PINNED_ACTIONS)
        }

        for path in workflow_files():
            workflow = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
            for uses, location in step_action_references(workflow):
                action, actual_major = validate_action_reference(
                    uses, f"{path}:{location}"
                )
                references[action].append((path.name, actual_major))

        for action, found in references.items():
            with self.subTest(action=action):
                self.assertTrue(found, f"Expected at least one {action} reference")

    def test_download_artifact_exception_remains_evidence_based(self) -> None:
        references = []
        for path in workflow_files():
            workflow = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
            for uses, _location in step_action_references(workflow):
                if uses.startswith("actions/download-artifact@"):
                    references.append(path.name)
        self.assertEqual(references, [])

    def test_quoted_external_reference_cannot_bypass_family_policy(self) -> None:
        workflow = yaml.safe_load(
            "jobs:\n  test:\n    steps:\n      - uses: 'unreviewed/action@v1'\n"
        )
        references = list(step_action_references(workflow))
        self.assertEqual(references, [("unreviewed/action@v1", "job 'test', step 1")])
        with self.assertRaisesRegex(AssertionError, "unreviewed external action family"):
            validate_action_reference(*references[0])

    def test_external_action_subpath_is_rejected(self) -> None:
        with self.assertRaisesRegex(AssertionError, "subpaths"):
            validate_action_reference(
                "actions/checkout/internal@v7", "regression fixture"
            )

    def test_non_major_external_action_refs_are_rejected(self) -> None:
        for revision in ("main", "v7.0.1", "0123456789abcdef"):
            with self.subTest(revision=revision):
                with self.assertRaisesRegex(AssertionError, "floating refs, SHAs"):
                    validate_action_reference(
                        f"actions/checkout@{revision}", "regression fixture"
                    )

    def test_workflow_validation_exercises_github_script_on_node_24(self) -> None:
        source = (WORKFLOWS / "workflow-validation.yml").read_text(
            encoding="utf-8-sig"
        )
        self.assertIn("uses: actions/github-script@v9", source)
        self.assertIn("process.version.startsWith('v24.')", source)

    def test_runtime_smoke_artifact_is_unique_per_run_attempt(self) -> None:
        source = (WORKFLOWS / "workflow-validation.yml").read_text(
            encoding="utf-8-sig"
        )
        self.assertIn(
            "name: action-runtime-policy-${{ github.run_id }}-${{ github.run_attempt }}",
            source,
        )


if __name__ == "__main__":
    unittest.main()
