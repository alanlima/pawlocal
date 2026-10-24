"""Render candidate search SQL as the isolated UID into a kernel-bounded file."""

import os
import runpy
import sys
from pathlib import Path

DIRECTORY = Path("/tmp/pawlocal-oncall-check-work/candidate/backend")
MAX_BYTES = 1024 * 1024


def main():
    import resource

    if Path.cwd() != DIRECTORY:
        raise RuntimeError("fixed candidate backend directory required")
    output = DIRECTORY.parent / "backend-search.sql"
    # Limits apply to this unprivileged process and its descendants only. Every
    # stdout writer, including os.write/subprocess bypasses, reaches this file.
    resource.setrlimit(resource.RLIMIT_FSIZE, (MAX_BYTES + 1, MAX_BYTES + 1))
    descriptor = os.open(
        output, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
    )
    sys.stdout.flush()
    os.dup2(descriptor, 1)
    os.close(descriptor)
    runpy.run_path("scripts/render_dsql_search_query.py", run_name="__main__")
    sys.stdout.flush()
    if output.stat().st_size > MAX_BYTES:
        raise RuntimeError("rendered SQL exceeds byte limit")


if __name__ == "__main__":
    main()
