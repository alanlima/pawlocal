"""Narrow actionlint 1.7.12 adapter for GitHub's documented queue:max key.

Validate the exact responder concurrency policy independently, then remove only
that one line from stdin sent to actionlint. All other syntax/security findings
and every other workflow remain fully linted. Remove adapter after linter support.
"""

import subprocess
from pathlib import Path

import yaml

TARGET = Path(".github/workflows/incident-responder.yml")


def compatible(raw):
    value = yaml.safe_load(raw)
    expected = {
        "group": "pawlocal-oncall-global-quota",
        "cancel-in-progress": False,
        "queue": "max",
    }
    if value.get("concurrency") != expected or raw.count("  queue: max\n") != 1:
        raise ValueError(
            "Responder requires independently validated global queue:max/cancel:false policy"
        )
    return raw.replace("  queue: max\n", "", 1)


def main():
    raw = TARGET.read_text()
    sanitized = compatible(raw)
    others = sorted(
        str(path) for path in Path(".github/workflows").glob("*.y*ml") if path != TARGET
    )
    subprocess.run(["actionlint", *others], check=True)
    subprocess.run(
        ["actionlint", "-stdin-filename", str(TARGET), "-"],
        input=sanitized.encode(),
        check=True,
    )


if __name__ == "__main__":
    main()
