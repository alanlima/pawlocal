from __future__ import annotations

import hashlib
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock
import zipfile


ROOT = Path(__file__).resolve().parents[2]
METADATA_SCRIPT = ROOT / ".github/scripts/terraform-plan-metadata.py"
ARCHIVE_HELPER = ROOT / ".github/scripts/terraform-cognito-archive.py"
TRANSFER_HELPER = ROOT / ".github/scripts/terraform-plan-transfer.py"
ARCHIVE_NAME = "cognito-pre-sign-up.zip"
TERRAFORM_ARCHIVE = Path(
    ".terraform/pawlocal-development-cognito-pre-signup.zip"
)
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

data "archive_file" "lambda" {
  type             = "zip"
  source_file      = "${path.module}/index.mjs"
  output_file_mode = "0666"
  output_path      = "${path.root}/.terraform/pawlocal-development-cognito-pre-signup.zip"
}
""".lstrip()

DEPENDENT_CONSUMER = """

resource "terraform_data" "lambda_consumer" {
  input = data.archive_file.lambda.output_sha256

  provisioner "local-exec" {
    interpreter = ["python", "-c"]
    command     = "import pathlib,sys; sys.exit(0 if pathlib.Path(r'${data.archive_file.lambda.output_path}').is_file() else 23)"
  }
}
"""


def load_script(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(
        name, path
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load Cognito archive helper")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class CognitoArchiveTransferTests(unittest.TestCase):
    def test_private_transfer_uses_fixed_keys_and_sse(self) -> None:
        fake_boto3 = types.SimpleNamespace(client=mock.Mock())
        with mock.patch.dict(sys.modules, {"boto3": fake_boto3}):
            module = load_script(TRANSFER_HELPER, "terraform_plan_transfer")
        client = mock.Mock()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            download = root / "download"
            plan = root / "tfplan"
            metadata = root / "metadata.json"
            archive = root / "lambda.zip"
            for path in (plan, metadata, archive):
                path.write_bytes(b"test")
            with mock.patch.object(module.boto3, "client", return_value=client):
                module.upload(
                    "bucket",
                    "plans/run",
                    plan,
                    metadata,
                    archive,
                )
                module.download(
                    "bucket",
                    "plans/run",
                    download,
                    "metadata.json",
                    True,
                )
                with self.assertRaisesRegex(SystemExit, "Missing plan transfer artifact"):
                    module.upload(
                        "bucket",
                        "plans/missing",
                        plan,
                        metadata,
                        root / "missing.zip",
                    )

        self.assertEqual(
            [call.args[2] for call in client.upload_file.call_args_list],
            [
                "plans/run/tfplan",
                "plans/run/plan-metadata.json",
                "plans/run/cognito-pre-sign-up.zip",
            ],
        )
        for call in client.upload_file.call_args_list:
            self.assertEqual(call.kwargs["ExtraArgs"], {"ServerSideEncryption": "AES256"})
        self.assertEqual(
            [call.args[1] for call in client.download_file.call_args_list],
            [
                "plans/run/tfplan",
                "plans/run/plan-metadata.json",
                "plans/run/cognito-pre-sign-up.zip",
            ],
        )


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


def metadata_arguments() -> list[str]:
    return [
        "--environment",
        "development",
        "--state-key",
        "pawlocal/development/terraform.tfstate",
        "--account-id",
        "1" * 12,
        "--backend-bucket",
        "private-state",
        "--backend-region",
        "test-region-1",
        "--commit",
        "a" * 40,
        "--repository-id",
        "1",
        "--run-id",
        "2",
        "--run-attempt",
        "1",
    ]


def run_metadata(
    mode: str, plan: Path, metadata: Path, archive: Path
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(METADATA_SCRIPT),
            mode,
            str(plan),
            str(metadata),
            *metadata_arguments(),
            "--archive",
            str(archive),
        ],
        check=False,
        capture_output=True,
        text=True,
    )


def write_configuration(directory: Path, *, dependent: bool) -> None:
    source = TERRAFORM_CONFIGURATION
    if dependent:
        source += DEPENDENT_CONSUMER
    (directory / "main.tf").write_text(source, encoding="utf-8")
    (directory / "index.mjs").write_text(
        PLANNED_SOURCE, encoding="utf-8", newline=""
    )


def prepare_apply_workspace(
    plan_workspace: Path,
    apply_workspace: Path,
    download_directory: Path,
    plan_name: str,
) -> Path:
    for name in ("main.tf", "index.mjs", ".terraform.lock.hcl", plan_name):
        shutil.copy2(plan_workspace / name, apply_workspace / name)
    run_terraform(apply_workspace, "init", "-backend=false", "-input=false")

    plan_archive = plan_workspace / TERRAFORM_ARCHIVE
    metadata = plan_workspace / "plan-metadata.json"
    result = run_metadata(
        "create", plan_workspace / plan_name, metadata, plan_archive
    )
    if result.returncode != 0:
        raise AssertionError(result.stderr)
    download_directory.mkdir()
    shutil.copy2(plan_workspace / plan_name, download_directory / "tfplan")
    shutil.copy2(metadata, download_directory / "plan-metadata.json")
    shutil.copy2(plan_archive, download_directory / ARCHIVE_NAME)

    result = run_metadata(
        "verify",
        download_directory / "tfplan",
        download_directory / "plan-metadata.json",
        download_directory / ARCHIVE_NAME,
    )
    if result.returncode != 0:
        raise AssertionError(result.stderr)
    return download_directory / "plan-metadata.json"


@unittest.skipUnless(
    os.environ.get("PAWLOCAL_RUN_TERRAFORM_ARCHIVE_INTEGRATION") == "1",
    "set PAWLOCAL_RUN_TERRAFORM_ARCHIVE_INTEGRATION=1 to run Terraform integration",
)
class CognitoArchiveSavedPlanTests(unittest.TestCase):
    def setUp(self) -> None:
        if shutil.which("terraform") is None:
            self.skipTest("terraform is required for the saved-plan integration test")
        self.archive_helper = load_script(
            ARCHIVE_HELPER, "terraform_cognito_archive"
        )

    def test_initial_apply_restores_exact_plan_archive_and_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="pawlocal-cognito-archive-") as temporary:
            root = Path(temporary)
            plan_workspace = root / "plan"
            apply_workspace = root / "apply"
            download_directory = root / "download"
            plan_workspace.mkdir()
            apply_workspace.mkdir()
            write_configuration(plan_workspace, dependent=True)

            run_terraform(plan_workspace, "init", "-backend=false", "-input=false")
            run_terraform(
                plan_workspace, "plan", "-input=false", "-out=tfplan"
            )
            plan_archive = plan_workspace / TERRAFORM_ARCHIVE
            self.assertTrue(plan_archive.is_file())

            metadata = prepare_apply_workspace(
                plan_workspace,
                apply_workspace,
                download_directory,
                "tfplan",
            )
            (apply_workspace / "index.mjs").write_text(
                CHANGED_SOURCE, encoding="utf-8", newline=""
            )
            self.archive_helper.restore(
                download_directory, metadata, apply_workspace, "development"
            )
            restored_archive = apply_workspace / TERRAFORM_ARCHIVE
            with zipfile.ZipFile(restored_archive) as archive:
                self.assertEqual(archive.read("index.mjs").decode(), PLANNED_SOURCE)
            run_terraform(
                apply_workspace,
                "apply",
                "-input=false",
                "-auto-approve",
                str(download_directory / "tfplan"),
            )

            downloaded_archive = download_directory / ARCHIVE_NAME
            downloaded_archive.write_bytes(b"tampered")
            verify = run_metadata(
                "verify", download_directory / "tfplan", metadata, downloaded_archive
            )
            self.assertNotEqual(verify.returncode, 0)
            with self.assertRaisesRegex(SystemExit, "digest mismatch"):
                self.archive_helper.restore(
                    download_directory, metadata, apply_workspace, "development"
                )

            downloaded_archive.unlink()
            with self.assertRaisesRegex(SystemExit, "missing or unsafe"):
                self.archive_helper.restore(
                    download_directory, metadata, apply_workspace, "development"
                )
            downloaded_archive.write_bytes(b"cleanup marker")
            self.archive_helper.cleanup(
                download_directory, apply_workspace, "development"
            )
            self.assertFalse(downloaded_archive.exists())
            self.assertFalse(restored_archive.exists())

    def test_retry_with_unchanged_archive_state_restores_before_dependent_create(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(prefix="pawlocal-cognito-retry-") as temporary:
            root = Path(temporary)
            plan_workspace = root / "plan"
            apply_workspace = root / "apply"
            download_directory = root / "download"
            plan_workspace.mkdir()
            apply_workspace.mkdir()
            write_configuration(plan_workspace, dependent=False)

            run_terraform(plan_workspace, "init", "-backend=false", "-input=false")
            run_terraform(
                plan_workspace, "apply", "-input=false", "-auto-approve"
            )
            (plan_workspace / TERRAFORM_ARCHIVE).unlink()
            write_configuration(plan_workspace, dependent=True)
            run_terraform(
                plan_workspace, "plan", "-input=false", "-out=retry.tfplan"
            )
            self.assertTrue((plan_workspace / TERRAFORM_ARCHIVE).is_file())

            metadata = prepare_apply_workspace(
                plan_workspace,
                apply_workspace,
                download_directory,
                "retry.tfplan",
            )
            shutil.copy2(
                plan_workspace / "terraform.tfstate",
                apply_workspace / "terraform.tfstate",
            )
            self.assertFalse((apply_workspace / TERRAFORM_ARCHIVE).exists())
            self.archive_helper.restore(
                download_directory, metadata, apply_workspace, "development"
            )
            run_terraform(
                apply_workspace,
                "apply",
                "-input=false",
                "-auto-approve",
                str(download_directory / "tfplan"),
            )

    def test_final_destroy_apply_does_not_need_transferred_archive(self) -> None:
        with tempfile.TemporaryDirectory(prefix="pawlocal-cognito-destroy-") as temporary:
            root = Path(temporary)
            plan_workspace = root / "plan"
            apply_workspace = root / "apply"
            plan_workspace.mkdir()
            apply_workspace.mkdir()
            write_configuration(plan_workspace, dependent=True)

            run_terraform(plan_workspace, "init", "-backend=false", "-input=false")
            run_terraform(
                plan_workspace, "apply", "-input=false", "-auto-approve"
            )
            (plan_workspace / TERRAFORM_ARCHIVE).unlink()
            run_terraform(
                plan_workspace,
                "plan",
                "-destroy",
                "-input=false",
                "-out=destroy.tfplan",
            )
            self.assertTrue((plan_workspace / TERRAFORM_ARCHIVE).is_file())

            for name in (
                "main.tf",
                "index.mjs",
                ".terraform.lock.hcl",
                "terraform.tfstate",
                "destroy.tfplan",
            ):
                shutil.copy2(plan_workspace / name, apply_workspace / name)
            run_terraform(apply_workspace, "init", "-backend=false", "-input=false")
            self.assertFalse((apply_workspace / TERRAFORM_ARCHIVE).exists())
            run_terraform(
                apply_workspace,
                "apply",
                "-input=false",
                "-auto-approve",
                "destroy.tfplan",
            )


if __name__ == "__main__":
    unittest.main()
