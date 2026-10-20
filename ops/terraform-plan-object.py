"""Transfer a Terraform saved plan through a private, tightly scoped S3 prefix."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path


def metadata_key(key: str) -> str:
    return f"{key}.metadata.json"


def scoped_key(bucket: str, key: str, environment: str) -> None:
    if not bucket.strip():
        raise ValueError("S3 bucket name is required")
    if not re.fullmatch(rf"plans/{re.escape(environment)}/[0-9]+/[0-9]+/tfplan", key):
        raise ValueError("Plan object key is outside its environment's pawlocal/plans prefix")


def make_client():
    try:
        import boto3
    except ImportError as exc:
        raise RuntimeError("boto3 is required for private S3 plan transfer") from exc
    return boto3.client("s3")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    upload = commands.add_parser("upload")
    _common(upload, with_file=True, with_metadata=True)

    download = commands.add_parser("download")
    _common(download, with_file=True, with_metadata=True)

    return parser.parse_args()


def _common(parser: argparse.ArgumentParser, *, with_file: bool, with_metadata: bool) -> None:
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--key", required=True)
    parser.add_argument("--environment", choices=("development", "production", "identity"), required=True)
    parser.add_argument("--state-key", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--repository-id", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--run-attempt", required=True)
    parser.add_argument("--sha256", required=True)
    if with_file:
        parser.add_argument("--file", required=True)


def expected_metadata(args: argparse.Namespace) -> dict[str, str]:
    expected_state_key = {
        "development": "pawlocal/development/terraform.tfstate",
        "production": "pawlocal/production/terraform.tfstate",
        "identity": "pawlocal/identity/terraform.tfstate",
    }[args.environment]
    if args.state_key != expected_state_key:
        raise ValueError("Terraform state key does not match the selected environment")
    if not re.fullmatch(r"[0-9a-f]{40}", args.commit):
        raise ValueError("Commit must be a full lowercase SHA-1")
    if not re.fullmatch(r"[0-9]+", args.run_id) or not re.fullmatch(r"[0-9]+", args.run_attempt):
        raise ValueError("Workflow run id and attempt must be numeric")
    if not re.fullmatch(r"[0-9]+", args.repository_id):
        raise ValueError("GitHub repository id must be numeric")
    if not re.fullmatch(r"[0-9a-f]{64}", args.sha256):
        raise ValueError("Plan digest must be a lowercase SHA-256")
    return {
        "environment": args.environment,
        "state_key": args.state_key,
        "commit": args.commit,
        "repository_id": args.repository_id,
        "run_id": args.run_id,
        "run_attempt": args.run_attempt,
        "sha256": args.sha256,
    }


def verify_metadata(stored: dict[str, str], expected: dict[str, str]) -> None:
    if stored != expected:
        raise ValueError("Stored plan metadata does not match this workflow run and commit")


def upload_plan_object(args: argparse.Namespace) -> None:
    scoped_key(args.bucket, args.key, args.environment)
    metadata = expected_metadata(args)
    plan_path = Path(args.file)
    plan_bytes = plan_path.read_bytes()
    digest_hasher = hashlib.sha256(plan_bytes)
    digest = digest_hasher.hexdigest()
    if digest != args.sha256:
        raise ValueError("Local saved-plan digest does not match the workflow output")

    client = make_client()
    encoded_metadata = json.dumps(metadata, sort_keys=True)
    encoded_metadata_bytes = encoded_metadata.encode("utf-8")
    client.put_object(
        Bucket=args.bucket,
        Key=args.key,
        Body=plan_bytes,
        ServerSideEncryption="AES256",
        Metadata={key.replace("_", "-"): value for key, value in metadata.items()},
    )
    client.put_object(
        Bucket=args.bucket,
        Key=metadata_key(args.key),
        Body=encoded_metadata_bytes,
        ContentType="application/json",
        ServerSideEncryption="AES256",
    )
    print(f"Stored private plan object {args.key}; sha256={digest}")


def download_plan_object(args: argparse.Namespace) -> None:
    scoped_key(args.bucket, args.key, args.environment)
    metadata = expected_metadata(args)
    client = make_client()
    response = client.get_object(Bucket=args.bucket, Key=metadata_key(args.key))
    stored_metadata = json.loads(response["Body"].read())
    verify_metadata(stored_metadata, metadata)

    response = client.get_object(Bucket=args.bucket, Key=args.key)
    body = response["Body"].read()
    digest_hasher = hashlib.sha256(body)
    digest = digest_hasher.hexdigest()
    if digest != args.sha256:
        raise ValueError("Downloaded plan digest does not match the reviewed plan")

    destination = Path(args.file)
    destination.parent.mkdir(parents=True, exist_ok=True)
    file_descriptor, temporary_name = tempfile.mkstemp(prefix=".tfplan-", dir=destination.parent)
    try:
        with os.fdopen(file_descriptor, "wb") as temporary_file:
            temporary_file.write(body)
        os.replace(temporary_name, destination)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)
    print(f"Retrieved matching private plan object {args.key}; sha256={digest}")


def main() -> None:
    args = parse_args()
    if args.command in {"upload", "download"}:
        expected_metadata(args)
    if args.command == "upload":
        upload_plan_object(args)
    else:
        download_plan_object(args)


if __name__ == "__main__":
    main()
