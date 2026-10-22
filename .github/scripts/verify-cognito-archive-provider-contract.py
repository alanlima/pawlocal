#!/usr/bin/env python3
"""Verify the pinned archive provider can build reviewed content during apply."""

from __future__ import annotations

import hashlib
import urllib.request


SOURCE_URL = (
    "https://raw.githubusercontent.com/hashicorp/terraform-provider-archive/"
    "v2.8.1/internal/provider/resource_archive_file.go"
)
SOURCE_SHA256 = "a1dd2f10f07fc9ab62ade82e4f2048fbb34ef94b7bb9b0bf69e7a234e54e174a"
REQUIRED_SOURCE_FRAGMENTS = (
    "func (d *archiveFileResource) Create",
    "resp.Diagnostics.Append(updateModel(ctx, &model)...)",
    '"source_content": schema.StringAttribute{',
    '"source_content_filename": schema.StringAttribute{',
    "stringplanmodifier.RequiresReplace()",
    '"output_file_mode": schema.StringAttribute{',
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
        "Verified archive provider 2.8.1 apply-time resource and replacement-sensitive content inputs."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
