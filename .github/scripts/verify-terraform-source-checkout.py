from __future__ import annotations

import os
import subprocess
import sys


def git(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *arguments],
        check=False,
        capture_output=True,
        text=True,
    )


def main() -> int:
    expected = os.environ.get("GITHUB_SHA", "")
    head = git("rev-parse", "HEAD")
    if not expected or head.returncode != 0 or head.stdout.strip() != expected:
        print("Terraform source checkout does not match the reviewed commit.", file=sys.stderr)
        return 1

    if git("diff", "--quiet", "--exit-code").returncode != 0:
        print("Terraform source checkout has uncommitted tracked changes.", file=sys.stderr)
        return 1
    if git("diff", "--cached", "--quiet", "--exit-code").returncode != 0:
        print("Terraform source checkout has staged tracked changes.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
