"""Transfer opaque Terraform plan files through the private bootstrap S3 bucket."""
from __future__ import annotations

import argparse
from pathlib import Path

import boto3


COGNITO_ARCHIVE_NAME = "cognito-pre-sign-up.zip"


def upload(
    bucket: str,
    prefix: str,
    plan_path: Path,
    metadata_path: Path,
    archive_path: Path | None,
) -> None:
    client = boto3.client("s3")
    artifacts = [(plan_path, "tfplan"), (metadata_path, "plan-metadata.json")]
    if archive_path is not None:
        artifacts.append((archive_path, COGNITO_ARCHIVE_NAME))
    missing = [str(source) for source, _ in artifacts if not source.is_file()]
    if missing:
        raise SystemExit("Missing plan transfer artifact: " + ", ".join(missing))
    for source, name in artifacts:
        client.upload_file(
            str(source),
            bucket,
            f"{prefix.rstrip('/')}/{name}",
            ExtraArgs={"ServerSideEncryption": "AES256"},
        )


def download(
    bucket: str,
    prefix: str,
    directory: Path,
    metadata_name: str,
    include_archive: bool,
) -> None:
    client = boto3.client("s3")
    directory.mkdir(parents=True, exist_ok=True)
    artifacts = [("tfplan", "tfplan"), ("plan-metadata.json", metadata_name)]
    if include_archive:
        artifacts.append((COGNITO_ARCHIVE_NAME, COGNITO_ARCHIVE_NAME))
    for remote_name, local_name in artifacts:
        client.download_file(bucket, f"{prefix.rstrip('/')}/{remote_name}", str(directory / local_name))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("direction", choices=("upload", "download"))
    parser.add_argument("bucket")
    parser.add_argument("prefix")
    parser.add_argument("directory_or_plan")
    parser.add_argument("metadata_path_or_name")
    parser.add_argument("--archive", nargs="?", const=COGNITO_ARCHIVE_NAME)
    args = parser.parse_args()
    if args.direction == "upload":
        upload(
            args.bucket,
            args.prefix,
            Path(args.directory_or_plan),
            Path(args.metadata_path_or_name),
            Path(args.archive) if args.archive is not None else None,
        )
    else:
        download(
            args.bucket,
            args.prefix,
            Path(args.directory_or_plan),
            args.metadata_path_or_name,
            args.archive is not None,
        )


if __name__ == "__main__":
    main()
