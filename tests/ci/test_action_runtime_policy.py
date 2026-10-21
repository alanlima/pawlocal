from __future__ import annotations

import re
import unittest
from pathlib import Path

import yaml


WORKFLOWS = Path(".github/workflows")

EXPECTED_HOSTED_JOBS = {
    ("backend-ci.yml", "backend"),
    ("compose-ci.yml", "compose"),
    ("deploy-production.yml", "verify-production"),
    ("development-dsql-seed.yml", "seed"),
    ("frontend-deploy.yml", "frontend"),
    ("frontend-production-deploy.yml", "disabled"),
    ("fullstack-release.yml", "publish"),
    ("fullstack-release.yml", "verify-development"),
    ("rollback-development.yml", "disabled"),
    ("terraform-ci.yml", "terraform"),
    ("terraform-current-stack-operations.yml", "disabled"),
    ("terraform-environment.yml", "apply"),
    ("terraform-environment.yml", "plan"),
    ("terraform-environment.yml", "production-eligibility"),
    ("workflow-validation.yml", "action-runtime-smoke"),
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


def workflow_files() -> list[Path]:
    return sorted((*WORKFLOWS.glob("*.yml"), *WORKFLOWS.glob("*.yaml")))


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
            action: [] for action in REQUIRED_ACTION_MAJORS
        }
        unexpected_actions: set[str] = set()

        for path in workflow_files():
            source = path.read_text(encoding="utf-8-sig")
            for action, actual_major in re.findall(
                r"(?m)^\s*(?:-\s*)?uses:\s+([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)@(v\d+)\s*$",
                source,
            ):
                if action not in REQUIRED_ACTION_MAJORS:
                    unexpected_actions.add(action)
                    continue
                references[action].append((path.name, actual_major))
                self.assertEqual(
                    actual_major,
                    REQUIRED_ACTION_MAJORS[action],
                    f"{path} must use {action}@{REQUIRED_ACTION_MAJORS[action]}",
                )

        self.assertEqual(
            unexpected_actions,
            set(),
            "Every direct external action must be reviewed and added to the policy",
        )

        for action, found in references.items():
            with self.subTest(action=action):
                self.assertTrue(found, f"Expected at least one {action} reference")

    def test_download_artifact_exception_remains_evidence_based(self) -> None:
        references = [
            path.name
            for path in workflow_files()
            if re.search(
                r"(?m)^\s*uses:\s+actions/download-artifact@",
                path.read_text(encoding="utf-8-sig"),
            )
        ]
        self.assertEqual(references, [])

    def test_workflow_validation_exercises_github_script_on_node_24(self) -> None:
        source = (WORKFLOWS / "workflow-validation.yml").read_text(
            encoding="utf-8-sig"
        )
        self.assertIn("uses: actions/github-script@v9", source)
        self.assertIn("process.version.startsWith('v24.')", source)


if __name__ == "__main__":
    unittest.main()
