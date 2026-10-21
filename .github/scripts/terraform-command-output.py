#!/usr/bin/env python3
"""Run Terraform with either captured output or live pseudo-terminal diagnostics."""

from __future__ import annotations

import argparse
import os
import shlex
import subprocess
from pathlib import Path


def run_command(log_path: Path, command: list[str]) -> int:
    if os.environ.get("PAWLOCAL_TERRAFORM_DIAGNOSTIC_LOGS") == "true":
        completed = subprocess.run(
            [
                "script",
                "--quiet",
                "--return",
                f"--command={shlex.join(command)}",
                str(log_path),
            ],
            check=False,
        )
        return completed.returncode

    with log_path.open("wb") as captured:
        completed = subprocess.run(
            command,
            check=False,
            stdout=captured,
            stderr=subprocess.STDOUT,
        )
    return completed.returncode


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--log", type=Path, required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()

    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        parser.error("a command is required after --")
    return run_command(args.log, command)


if __name__ == "__main__":
    raise SystemExit(main())
