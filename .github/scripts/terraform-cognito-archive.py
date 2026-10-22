#!/usr/bin/env python3
"""Restore or remove the plan-bound Cognito Lambda archive at its exact path."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile


ARCHIVE_NAME = "cognito-pre-sign-up.zip"
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def archive_relative_path(environment: str) -> Path:
    if environment not in {"development", "production"}:
        raise SystemExit("Environment must be development or production")
    return Path(
        f".terraform/pawlocal-{environment}-cognito-pre-signup.zip"
    )


def digest(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise SystemExit(f"Required Cognito archive is missing or unsafe: {path}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def expected_digest(metadata_path: Path, environment: str) -> str:
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    archive = metadata.get("cognito_archive")
    expected = {
        "name": ARCHIVE_NAME,
        "terraform_path": archive_relative_path(environment).as_posix(),
    }
    if not isinstance(archive, dict) or any(
        archive.get(key) != value for key, value in expected.items()
    ):
        raise SystemExit("Saved plan has no matching Cognito archive contract")
    archive_digest = archive.get("sha256")
    if not isinstance(archive_digest, str) or not SHA256_PATTERN.fullmatch(
        archive_digest
    ):
        raise SystemExit("Saved plan Cognito archive digest is invalid")
    return archive_digest


def archive_paths(
    download_directory: Path, terraform_root: Path, environment: str
) -> tuple[Path, Path]:
    root = terraform_root.resolve()
    destination = (root / archive_relative_path(environment)).resolve()
    if root not in destination.parents:
        raise SystemExit("Cognito archive destination escaped the Terraform root")
    return download_directory / ARCHIVE_NAME, destination


def restore(
    download_directory: Path,
    metadata_path: Path,
    terraform_root: Path,
    environment: str,
) -> None:
    source, destination = archive_paths(
        download_directory, terraform_root, environment
    )
    planned_digest = expected_digest(metadata_path, environment)
    if digest(source) != planned_digest:
        raise SystemExit("Downloaded Cognito archive digest mismatch")

    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        dir=destination.parent, prefix=f".{destination.name}.", delete=False
    ) as temporary:
        temporary_path = Path(temporary.name)
    try:
        shutil.copyfile(source, temporary_path)
        os.chmod(temporary_path, 0o600)
        if digest(temporary_path) != planned_digest:
            raise SystemExit("Restored Cognito archive digest mismatch")
        os.replace(temporary_path, destination)
    finally:
        temporary_path.unlink(missing_ok=True)

    if digest(destination) != planned_digest:
        raise SystemExit("Cognito archive changed after atomic restoration")
    print(destination)


def cleanup(
    download_directory: Path, terraform_root: Path, environment: str
) -> None:
    source, destination = archive_paths(
        download_directory, terraform_root, environment
    )
    source.unlink(missing_ok=True)
    destination.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("restore", "cleanup"):
        command_parser = subparsers.add_parser(command)
        command_parser.add_argument(
            "--environment",
            choices=("development", "production"),
            required=True,
        )
        command_parser.add_argument("--terraform-root", type=Path, required=True)
        command_parser.add_argument("--download-directory", type=Path, required=True)
        if command == "restore":
            command_parser.add_argument("--metadata", type=Path, required=True)
    args = parser.parse_args()

    if args.command == "restore":
        restore(
            args.download_directory,
            args.metadata,
            args.terraform_root,
            args.environment,
        )
    else:
        cleanup(args.download_directory, args.terraform_root, args.environment)


if __name__ == "__main__":
    main()
