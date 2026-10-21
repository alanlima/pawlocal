#!/usr/bin/env python3
"""Print a small, opt-in, redacted Terraform failure summary for GitHub Actions."""

from __future__ import annotations

import argparse
import os
import pathlib
import re
import sys


PHASE_MESSAGES = {
    "apply": "Terraform apply failed; raw provider output was withheld.",
    "plan": "Terraform planning failed; raw provider output was withheld.",
}


def sanitize(value: str) -> str:
    """Remove likely secret, infrastructure, and account-specific values."""
    value = re.sub(
        r"(?i)(access[_ -]?key(?:_id)?|secret(?:[_ -]?access)?[_ -]?key|session[_ -]?token|password|client[_ -]?secret|private[_ -]?key)\s*[:=]\s*\S+",
        r"\1=[REDACTED]",
        value,
    )
    value = re.sub(r"arn:[^\s,;]+", "[REDACTED_ARN]", value)
    value = re.sub(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b", "[REDACTED_AWS_KEY]", value)
    value = re.sub(r"\b\d{12}\b", "[REDACTED_ACCOUNT]", value)
    value = re.sub(r"(?i)https?://[^\s,;]+", "[REDACTED_URL]", value)
    value = re.sub(
        r"(?i)\b(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}\b",
        "[REDACTED_HOSTNAME]",
        value,
    )
    value = re.sub(r"\bsha256:[0-9a-fA-F]{64}\b|\b[0-9a-fA-F]{64}\b", "[REDACTED_DIGEST]", value)
    value = re.sub(
        r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}\b",
        "[REDACTED_IDENTIFIER]",
        value,
    )
    value = re.sub(r"\bE[A-Z0-9]{10,}\b", "[REDACTED_RESOURCE_ID]", value)
    value = re.sub(r"(?i)\bplans/[A-Za-z0-9._/-]+", "[REDACTED_PLAN_METADATA]", value)
    value = re.sub(r'"[^"\r\n]*"|\'[^\'\r\n]*\'', "[REDACTED_VALUE]", value)
    value = re.sub(
        r"(?i)\b(bucket|distribution|origin access control|oac|certificate|resource(?:\s*id)?|request\s*id|host\s*id)\s*[:=]\s*[^\s,;]+",
        r"\1=[REDACTED_RESOURCE]",
        value,
    )
    value = re.sub(r"\(([A-Za-z0-9][A-Za-z0-9._:/-]{2,})\)", "([REDACTED_RESOURCE])", value)
    value = re.sub(r"\b[A-Za-z0-9+/]{40,}={0,2}\b", "[REDACTED_TOKEN]", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value[:400]


def generic_explanation(text: str) -> str | None:
    """Return only a fixed explanation for a recognized provider failure class."""
    lowered = text.lower()
    if "accessdenied" in lowered or "not authorized" in lowered or "unauthorized" in lowered:
        return "The provider request was not authorized."
    if "timeout" in lowered or "timed out" in lowered or "waiting for" in lowered:
        return "Terraform timed out while waiting for the resource operation."
    if "throttl" in lowered or "toomanyrequests" in lowered:
        return "The provider request was throttled."
    if "alreadyexists" in lowered or "already exists" in lowered:
        return "The requested resource already exists."
    if "conflict" in lowered:
        return "The provider reported a conflicting resource state."
    return None


def print_sanitized_diagnostics(text: str) -> None:
    diagnostics = re.findall(r"(?m)^Error:\s*(.*)$", text)
    if not diagnostics:
        print("No standard Terraform error heading was found; provider details were withheld.")
    for index, summary in enumerate(diagnostics[:3], start=1):
        print(f"Diagnostic {index}: {sanitize(summary)}")

    operation = re.search(r"operation error\s+([A-Za-z0-9]+):\s*([A-Za-z0-9]+)", text, re.IGNORECASE)
    if operation:
        print(f"AWS operation: {operation.group(1)} {operation.group(2)}")

    error_code = re.search(r"api error\s+([A-Za-z][A-Za-z0-9._-]*)", text, re.IGNORECASE)
    if error_code:
        print(f"AWS error code: {error_code.group(1)}")

    status_code = re.search(r"StatusCode:\s*(\d{3})", text)
    if status_code:
        print(f"HTTP status: {status_code.group(1)}")

    explanation = generic_explanation(text)
    if explanation:
        print(f"Explanation: {explanation}")

    variable_names = re.findall(
        r'The root module input variable "([A-Za-z_][A-Za-z0-9_]*)" is not set', text
    )
    for name in sorted(set(variable_names)):
        print(f"Missing Terraform input variable: {name}")

    location = re.search(r"(?m)^\s+on\s+([^\s]+)\s+line\s+(\d+),", text)
    if location:
        print(f"Configuration file: {pathlib.PurePosixPath(location.group(1)).name}:{location.group(2)}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("log", type=pathlib.Path)
    parser.add_argument("--phase", choices=sorted(PHASE_MESSAGES), required=True)
    args = parser.parse_args()

    print(PHASE_MESSAGES[args.phase])
    if os.environ.get("PAWLOCAL_TERRAFORM_DIAGNOSTIC_LOGS") != "true":
        return 0

    try:
        text = args.log.read_text(encoding="utf-8", errors="replace")
    except OSError:
        print("Terraform diagnostic log unavailable; provider details were withheld.")
        return 0

    print_sanitized_diagnostics(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
