from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import zipfile


PLANNED_SOURCE = "export const marker = 'reviewed-plan';\n"
CHANGED_SOURCE = "export const marker = 'changed-after-plan';\n"

TERRAFORM_CONFIGURATION = """
terraform {
  required_version = "= 1.14.3"

  required_providers {
    archive = {
      source  = "hashicorp/archive"
      version = "= 2.8.1"
    }
  }
}

resource "archive_file" "lambda" {
  type                    = "zip"
  source_content          = file("${path.module}/index.mjs")
  source_content_filename = "index.mjs"
  output_file_mode        = "0666"
  output_path             = "${path.root}/.terraform/lambda.zip"
}

output "archive_sha256" {
  value = archive_file.lambda.output_sha256
}
""".lstrip()


def run_terraform(directory: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["terraform", *arguments],
        cwd=directory,
        check=False,
        capture_output=True,
        text=True,
        env={**os.environ, "TF_IN_AUTOMATION": "true"},
    )
    if result.returncode != 0:
        raise AssertionError(
            f"terraform {' '.join(arguments)} failed in {directory}\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    return result


def verify_archive(archive_path: Path, expected_sha256: str) -> None:
    if not archive_path.is_file():
        raise AssertionError(f"saved-plan apply did not create {archive_path}")

    actual_sha256 = hashlib.sha256(archive_path.read_bytes()).hexdigest()
    if actual_sha256 != expected_sha256:
        raise AssertionError(
            f"archive digest mismatch: expected {expected_sha256}, got {actual_sha256}"
        )


@unittest.skipUnless(
    os.environ.get("PAWLOCAL_RUN_TERRAFORM_ARCHIVE_INTEGRATION") == "1",
    "set PAWLOCAL_RUN_TERRAFORM_ARCHIVE_INTEGRATION=1 to run Terraform integration",
)
class CognitoArchiveSavedPlanTests(unittest.TestCase):
    def setUp(self) -> None:
        if shutil.which("terraform") is None:
            self.skipTest("terraform is required for the saved-plan integration test")

    def test_apply_runner_creates_exact_archive_from_reviewed_saved_plan(self) -> None:
        with tempfile.TemporaryDirectory(prefix="pawlocal-cognito-archive-") as temporary:
            root = Path(temporary)
            plan_workspace = root / "plan"
            apply_workspace = root / "apply"
            changed_apply_workspace = root / "changed-apply"
            plan_workspace.mkdir()
            apply_workspace.mkdir()
            changed_apply_workspace.mkdir()

            (plan_workspace / "main.tf").write_text(
                TERRAFORM_CONFIGURATION, encoding="utf-8"
            )
            (plan_workspace / "index.mjs").write_text(
                PLANNED_SOURCE, encoding="utf-8", newline=""
            )

            run_terraform(plan_workspace, "init", "-backend=false", "-input=false")
            run_terraform(
                plan_workspace,
                "plan",
                "-input=false",
                "-out=tfplan",
            )
            self.assertFalse(
                (plan_workspace / ".terraform/lambda.zip").exists(),
                "planning must not create the apply-time Lambda archive",
            )

            shutil.copy2(plan_workspace / "main.tf", apply_workspace / "main.tf")
            shutil.copy2(
                plan_workspace / ".terraform.lock.hcl",
                apply_workspace / ".terraform.lock.hcl",
            )
            shutil.copy2(plan_workspace / "tfplan", apply_workspace / "tfplan")
            (apply_workspace / "index.mjs").write_text(
                PLANNED_SOURCE, encoding="utf-8", newline=""
            )

            run_terraform(apply_workspace, "init", "-backend=false", "-input=false")
            run_terraform(
                apply_workspace,
                "apply",
                "-input=false",
                "-auto-approve",
                "tfplan",
            )

            archive_path = apply_workspace / ".terraform/lambda.zip"
            terraform_output = json.loads(
                run_terraform(apply_workspace, "output", "-json").stdout
            )
            expected_sha256 = terraform_output["archive_sha256"]["value"]
            verify_archive(archive_path, expected_sha256)

            with zipfile.ZipFile(archive_path) as archive:
                self.assertEqual(archive.namelist(), ["index.mjs"])
                self.assertEqual(
                    archive.read("index.mjs").decode("utf-8"), PLANNED_SOURCE
                )

            archive_path.write_bytes(b"tampered")
            with self.assertRaisesRegex(AssertionError, "archive digest mismatch"):
                verify_archive(archive_path, expected_sha256)

            archive_path.unlink()
            with self.assertRaisesRegex(AssertionError, "did not create"):
                verify_archive(archive_path, expected_sha256)

            shutil.copy2(
                plan_workspace / "main.tf", changed_apply_workspace / "main.tf"
            )
            shutil.copy2(
                plan_workspace / ".terraform.lock.hcl",
                changed_apply_workspace / ".terraform.lock.hcl",
            )
            shutil.copy2(
                plan_workspace / "tfplan", changed_apply_workspace / "tfplan"
            )
            (changed_apply_workspace / "index.mjs").write_text(
                CHANGED_SOURCE, encoding="utf-8", newline=""
            )
            run_terraform(
                changed_apply_workspace, "init", "-backend=false", "-input=false"
            )
            with self.assertRaisesRegex(AssertionError, "inconsistent result"):
                run_terraform(
                    changed_apply_workspace,
                    "apply",
                    "-input=false",
                    "-auto-approve",
                    "tfplan",
                )


if __name__ == "__main__":
    unittest.main()
