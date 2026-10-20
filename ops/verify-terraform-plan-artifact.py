#!/usr/bin/env python3
"""Verify a downloaded Terraform plan or review artifact against its run output."""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path


def digest_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", required=True, type=Path)
    parser.add_argument("--expected-sha256", required=True)
    args = parser.parse_args()
    if len(args.expected_sha256) != 64 or any(
        char not in "0123456789abcdef" for char in args.expected_sha256.lower()
    ):
        print("Invalid expected SHA-256", file=sys.stderr)
        return 1
    try:
        actual = digest_file(args.file)
    except OSError as exc:
        print(f"Unable to read artifact: {exc}", file=sys.stderr)
        return 1
    if actual != args.expected_sha256.lower():
        print("Terraform plan artifact SHA-256 mismatch", file=sys.stderr)
        return 1
    print("Terraform plan artifact SHA-256 verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
