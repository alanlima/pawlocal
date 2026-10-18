"""Fail the stable CI status when detection or an applicable check fails."""

from __future__ import annotations

import os
import sys

COMPONENT_RESULTS = (
    "FRONTEND_RESULT",
    "BACKEND_RESULT",
    "COMPOSE_RESULT",
    "TERRAFORM_RESULT",
    "WORKFLOW_RESULT",
)


def required_status_succeeds(results: dict[str, str]) -> bool:
    if results.get("CHANGES_RESULT") != "success":
        return False
    return all(results.get(name) in {"success", "skipped"} for name in COMPONENT_RESULTS)


def main() -> None:
    results = {name: os.environ.get(name, "") for name in COMPONENT_RESULTS}
    results["CHANGES_RESULT"] = os.environ.get("CHANGES_RESULT", "")
    if not required_status_succeeds(results):
        print("Path detection failed or an applicable check failed/cancelled.", file=sys.stderr)
        raise SystemExit(1)
    print("All applicable checks passed; intentionally skipped jobs are accepted.")


if __name__ == "__main__":
    main()
