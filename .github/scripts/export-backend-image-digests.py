#!/usr/bin/env python3
"""Export immutable backend images from Terraform's environment_targets output."""

from __future__ import annotations

import json
import os
import pathlib
import re
import sys


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("Usage: export-backend-image-digests.py <terraform-output-json>")

    targets = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
    if not isinstance(targets, dict):
        raise SystemExit("Terraform environment_targets output has no target map")

    images: dict[str, str] = {}
    for environment in ("development", "production"):
        target = targets.get(environment)
        image = target.get("api_backend_image") if isinstance(target, dict) else None
        if not isinstance(image, str) or not re.fullmatch(
            r"ghcr\.io/alanlima/pawlocal-api@sha256:[0-9a-f]{64}", image
        ):
            raise SystemExit(
                f"Terraform environment_targets has no valid immutable API image for {environment}"
            )
        images[environment] = image

    environment_file = os.environ.get("GITHUB_ENV")
    if not environment_file:
        raise SystemExit("GITHUB_ENV is not set; cannot export Terraform variable")
    value = json.dumps(images, separators=(",", ":"))
    with pathlib.Path(environment_file).open("a", encoding="utf-8") as target:
        target.write(f"TF_VAR_backend_image_digests={value}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
