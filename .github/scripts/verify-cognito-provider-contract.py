#!/usr/bin/env python3
"""Verify the reviewed AWS provider log-group refresh request at its pinned source tag."""

from __future__ import annotations

import hashlib
import urllib.request


SOURCE_URL = (
    "https://raw.githubusercontent.com/hashicorp/terraform-provider-aws/"
    "v6.69.1/internal/service/logs/group.go"
)
SOURCE_SHA256 = "71cf1453c4ac176ae80aa02d4d067be6ad41e38f6731351c5ba23abb49840467"
REQUIRED_REFRESH_REQUEST = "LogGroupNamePrefix: aws.String(name),"


def main() -> int:
    with urllib.request.urlopen(SOURCE_URL, timeout=30) as response:
        source = response.read()

    actual_sha256 = hashlib.sha256(source).hexdigest()
    if actual_sha256 != SOURCE_SHA256:
        raise SystemExit(
            "AWS provider 6.69.1 log-group source digest changed; stop and review the provider contract."
        )

    text = source.decode("utf-8")
    if REQUIRED_REFRESH_REQUEST not in text:
        raise SystemExit(
            "AWS provider 6.69.1 no longer proves the deterministic LogGroupNamePrefix refresh request."
        )

    print("Verified AWS provider 6.69.1 deterministic LogGroupNamePrefix refresh request.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
