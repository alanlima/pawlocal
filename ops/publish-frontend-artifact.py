#!/usr/bin/env python3
"""Publish a verified static release archive using AWS SDK APIs only."""

from __future__ import annotations

import argparse
import hashlib
import mimetypes
import os
import re
import tarfile
from pathlib import PurePosixPath


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", required=True)
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--distribution-id", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--digest", required=True)
    return parser.parse_args()


def archive_files(archive_path: str) -> dict[str, tuple[bytes, str]]:
    files: dict[str, tuple[bytes, str]] = {}
    with tarfile.open(archive_path, "r:gz") as archive:
        for member in archive.getmembers():
            if member.isdir():
                continue
            if not member.isfile():
                raise ValueError("Frontend archive contains a non-regular file")
            path = PurePosixPath(member.name)
            if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
                raise ValueError("Frontend archive contains an unsafe object path")
            stream = archive.extractfile(member)
            if stream is None:
                raise ValueError("Frontend archive file contents could not be read")
            content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            files[path.as_posix()] = (stream.read(), content_type)
    if not files:
        raise ValueError("Frontend archive contains no files")
    return files


def publish(args: argparse.Namespace) -> None:
    if not re.fullmatch(r"[0-9a-f]{40}", args.commit):
        raise ValueError("Commit must be a full lowercase SHA-1")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", args.digest):
        raise ValueError("Frontend digest must be a lowercase SHA-256")
    if not re.fullmatch(r"[A-Z0-9]+", args.distribution_id):
        raise ValueError("CloudFront distribution id is invalid")
    if not re.fullmatch(r"[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]", args.bucket):
        raise ValueError("S3 bucket name is invalid")

    archive_bytes = open(args.archive, "rb").read()
    actual_digest = "sha256:" + hashlib.sha256(archive_bytes).hexdigest()
    if actual_digest != args.digest:
        raise ValueError("Frontend archive digest does not match the release manifest")
    files = archive_files(args.archive)

    try:
        import boto3
    except ImportError as exc:
        raise RuntimeError("boto3 is required for frontend artifact publishing") from exc

    region = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION")
    s3 = boto3.client("s3", region_name=region)
    cloudfront = boto3.client("cloudfront", region_name="us-east-1")

    expected_keys = set(files)
    existing_keys: set[str] = set()
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=args.bucket):
        existing_keys.update(
            item["Key"] for item in page.get("Contents", [])
            if not item["Key"].startswith("releases/")
        )

    stale = sorted(existing_keys - expected_keys)
    for start in range(0, len(stale), 1000):
        batch = stale[start:start + 1000]
        if batch:
            s3.delete_objects(Bucket=args.bucket, Delete={"Objects": [{"Key": key} for key in batch], "Quiet": True})

    for key, (body, content_type) in files.items():
        s3.put_object(
            Bucket=args.bucket,
            Key=key,
            Body=body,
            ContentType=content_type,
            ServerSideEncryption="AES256",
        )

    archive_key = f"releases/{args.commit}/{args.digest.removeprefix('sha256:')}.tar.gz"
    s3.put_object(
        Bucket=args.bucket,
        Key=archive_key,
        Body=archive_bytes,
        ContentType="application/gzip",
        ServerSideEncryption="AES256",
        Metadata={"commit": args.commit, "sha256": args.digest.removeprefix("sha256:")},
    )
    cloudfront.create_invalidation(
        DistributionId=args.distribution_id,
        InvalidationBatch={
            "Paths": {"Quantity": 1, "Items": ["/*"]},
            "CallerReference": f"{args.commit}-{args.digest.removeprefix('sha256:')}",
        },
    )
    print(f"Published verified frontend artifact {args.digest}")


def main() -> None:
    args = parse_args()
    try:
        publish(args)
    except (ValueError, OSError, tarfile.TarError) as exc:
        raise SystemExit(f"Frontend publish failed: {exc}") from exc


if __name__ == "__main__":
    main()
