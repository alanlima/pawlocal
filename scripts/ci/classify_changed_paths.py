"""Map changed repository paths to the PawLocal CI checks they affect."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Iterable

CHECKS = ("frontend", "backend", "compose", "terraform", "workflows")
DOC_SUFFIXES = (".md", ".mdx")
CI_WORKFLOW = ".github/workflows/ci.yml"
FRONTEND_WORKFLOWS = {
    ".github/workflows/frontend-deploy.yml",
    ".github/workflows/frontend-production-deploy.yml",
}
FRONTEND_MANIFESTS = {
    "package.json",
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
}
BACKEND_MANIFESTS = {
    "pyproject.toml",
    "requirements.txt",
    "poetry.lock",
    "uv.lock",
}
COMPOSE_FILES = {
    ".dockerignore",
    "Dockerfile",
    "docker-compose.yml",
    "docker-compose.yaml",
    "compose.yml",
    "compose.yaml",
}


def normalize_path(path: str) -> str:
    path = path.replace("\\", "/")
    while path.startswith("./"):
        path = path[2:]
    return path


def is_documentation(path: str) -> bool:
    path = path.lower()
    return path.startswith("docs/") or path.endswith(DOC_SUFFIXES)


def classify_paths(paths: Iterable[str], *, run_all: bool = False) -> dict[str, bool]:
    """Return true for each component whose validation can be affected."""
    affected = dict.fromkeys(CHECKS, run_all)
    if run_all:
        return affected

    normalized_paths = {
        normalize_path(path)
        for path in paths
        if path and not is_documentation(normalize_path(path))
    }

    if CI_WORKFLOW in normalized_paths:
        return dict.fromkeys(CHECKS, True)

    for path in normalized_paths:
        if (
            path.startswith("frontend/")
            or path in FRONTEND_MANIFESTS
            or path == "openapi.yaml"
            or path in FRONTEND_WORKFLOWS
        ):
            affected["frontend"] = True
        if (
            path.startswith("backend/")
            or path in BACKEND_MANIFESTS
            or path == "openapi.yaml"
        ):
            affected["backend"] = True
        if (
            path in COMPOSE_FILES
            or path == ".env.example"
            or path.startswith("observability/")
            or path == "openapi.yaml"
        ):
            affected["compose"] = True
        if path.startswith("infra/terraform/"):
            affected["terraform"] = True
        if path.startswith(".github/workflows/") or path.startswith(
            ("scripts/ci/", "tests/ci/")
        ):
            affected["workflows"] = True

    return affected


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--all",
        action="store_true",
        help="mark every check as affected (used for manual dispatch and initial pushes)",
    )
    parser.add_argument(
        "--nul",
        action="store_true",
        help="read NUL-separated paths from stdin, as emitted by git diff --name-only -z",
    )
    args = parser.parse_args()

    if args.all:
        paths: list[str] = []
    else:
        raw = sys.stdin.buffer.read()
        separator = b"\0" if args.nul else b"\n"
        paths = [part.decode("utf-8", errors="surrogateescape") for part in raw.split(separator)]

    for name, enabled in classify_paths(paths, run_all=args.all).items():
        print(f"{name}={'true' if enabled else 'false'}")


if __name__ == "__main__":
    main()
