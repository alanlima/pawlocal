#!/usr/bin/env python3
"""Print a small, redacted Terraform plan failure summary for GitHub Actions."""

from __future__ import annotations

import pathlib
import re
import sys


def sanitize(value: str) -> str:
    """Remove likely secret or account-specific values from a diagnostic headline."""
    value = re.sub(r"arn:[^\s,;]+", "[REDACTED_ARN]", value)
    value = re.sub(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b", "[REDACTED_AWS_KEY]", value)
    value = re.sub(r"\b\d{12}\b", "[REDACTED_ACCOUNT]", value)
    value = re.sub(r'"[^"\r\n]*"|\'[^\'\r\n]*\'', "[REDACTED_VALUE]", value)
    value = re.sub(
        r"(?i)(access[_ -]?key(?:_id)?|secret(?:[_ -]?access)?[_ -]?key|session[_ -]?token|password|client[_ -]?secret|private[_ -]?key)\s*[:=]\s*\S+",
        r"\1=[REDACTED]",
        value,
    )
    value = re.sub(r"\b[A-Za-z0-9+/]{40,}={0,2}\b", "[REDACTED_TOKEN]", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value[:400]


def main() -> int:
    if len(sys.argv) != 2:
        print("Terraform diagnostic log unavailable; provider details were withheld.")
        return 0

    try:
        text = pathlib.Path(sys.argv[1]).read_text(encoding="utf-8", errors="replace")
    except OSError:
        print("Terraform diagnostic log unavailable; provider details were withheld.")
        return 0

    diagnostics = re.findall(r"(?m)^Error:\s*(.*)$", text)
    if not diagnostics:
        print("No standard Terraform error heading was found; provider details were withheld.")
    for index, summary in enumerate(diagnostics[:3], start=1):
        print(f"Diagnostic {index}: {sanitize(summary)}")

    variable_names = re.findall(
        r'The root module input variable "([A-Za-z_][A-Za-z0-9_]*)" is not set', text
    )
    for name in sorted(set(variable_names)):
        print(f"Missing Terraform input variable: {name}")

    address = re.search(r"(?m)^\s+with\s+([^\s,]+),\s*$", text)
    location = re.search(r"(?m)^\s+on\s+([^\s]+)\s+line\s+(\d+),", text)
    if address:
        print(f"Resource address: {sanitize(address.group(1))}")
    if location:
        print(f"Configuration location: {location.group(1)}:{location.group(2)}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
