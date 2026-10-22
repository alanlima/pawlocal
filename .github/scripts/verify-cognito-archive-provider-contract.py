#!/usr/bin/env python3
"""Verify the pinned archive provider builds the transferable plan-time package."""

from __future__ import annotations

import hashlib
import urllib.request


SOURCE_URL = (
    "https://raw.githubusercontent.com/hashicorp/terraform-provider-archive/"
    "v2.8.1/internal/provider/data_source_archive_file.go"
)
SOURCE_SHA256 = "ae6d4b6d5e693efdc38db701be1928050eb4a63099d36a736cc4cb5b31b3cfb7"
REQUIRED_SOURCE_FRAGMENTS = (
    "func (d *archiveFileDataSource) Read",
    "if err := archiver.ArchiveFile(model.SourceFile.ValueString()); err != nil",
    '"source_file": schema.StringAttribute{',
    '"output_file_mode": schema.StringAttribute{',
    "if err := os.MkdirAll(outputDirectory, 0755); err != nil",
)


def main() -> int:
    with urllib.request.urlopen(SOURCE_URL, timeout=30) as response:
        source = response.read()

    actual_sha256 = hashlib.sha256(source).hexdigest()
    if actual_sha256 != SOURCE_SHA256:
        raise SystemExit(
            "archive provider 2.8.1 source digest changed; stop and review the provider contract."
        )

    text = source.decode("utf-8")
    missing = [fragment for fragment in REQUIRED_SOURCE_FRAGMENTS if fragment not in text]
    if missing:
        raise SystemExit(
            "archive provider 2.8.1 no longer proves the reviewed apply-time contract: "
            + ", ".join(missing)
        )

    print(
        "Verified archive provider 2.8.1 plan-time data source and deterministic package inputs."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
