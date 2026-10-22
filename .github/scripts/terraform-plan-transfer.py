"""Transfer opaque Terraform plan files through the private bootstrap S3 bucket."""
from __future__ import annotations

import argparse
from pathlib import Path

import boto3


def upload(bucket: str, prefix: str, plan_path: Path, metadata_path: Path) -> None:
    client = boto3.client("s3")
    for source, name in ((plan_path, "tfplan"), (metadata_path, "plan-metadata.json")):
        client.upload_file(
            str(source),
            bucket,
            f"{prefix.rstrip('/')}/{name}",
            ExtraArgs={"ServerSideEncryption": "AES256"},
        )


def download(bucket: str, prefix: str, directory: Path, metadata_name: str) -> None:
    client = boto3.client("s3")
    directory.mkdir(parents=True, exist_ok=True)
    for remote_name, local_name in (("tfplan", "tfplan"), ("plan-metadata.json", metadata_name)):
        client.download_file(bucket, f"{prefix.rstrip('/')}/{remote_name}", str(directory / local_name))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("direction", choices=("upload", "download"))
    parser.add_argument("bucket")
    parser.add_argument("prefix")
    parser.add_argument("directory_or_plan")
    parser.add_argument("metadata_path_or_name")
    args = parser.parse_args()
    if args.direction == "upload":
        upload(args.bucket, args.prefix, Path(args.directory_or_plan), Path(args.metadata_path_or_name))
    else:
        download(args.bucket, args.prefix, Path(args.directory_or_plan), args.metadata_path_or_name)


if __name__ == "__main__":
    main()
