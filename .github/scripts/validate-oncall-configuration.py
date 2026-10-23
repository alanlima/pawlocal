"""Reject unknown/private operator fields before Terraform records raw inputs."""

from __future__ import annotations

import json
import os
import re


def validate(raw: str, account: str, region: str) -> None:
    if len(raw.encode("utf-8")) > 8192:
        raise ValueError("ONCALL_CONFIGURATION_TOO_LARGE")

    def unique(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("ONCALL_DUPLICATE_FIELD")
            result[key] = value
        return result

    try:
        value = json.loads(raw, object_pairs_hook=unique)
    except (ValueError, TypeError) as error:
        raise ValueError("ONCALL_INVALID_JSON") from error
    if value is None:
        return
    required = {"app_id", "installation_id", "repository_id", "allowed_services", "allowed_alerts"}
    if not isinstance(value, dict) or not required.issubset(value) or set(value) - required - {"kms_key_arn"}:
        raise ValueError("ONCALL_UNKNOWN_OR_MISSING_FIELDS")
    for name in ("app_id", "installation_id", "repository_id"):
        item = value[name]
        if not isinstance(item, str) or not re.fullmatch(r"[1-9][0-9]{0,15}", item):
            raise ValueError("ONCALL_INVALID_NUMERIC_ID")
    if int(value["repository_id"]) > 9007199254740991:
        raise ValueError("ONCALL_UNSAFE_REPOSITORY_ID")
    for name in ("allowed_services", "allowed_alerts"):
        items = value[name]
        if not isinstance(items, list) or not 1 <= len(items) <= 10:
            raise ValueError("ONCALL_INVALID_ALLOWLIST")
        if not all(isinstance(item, str) and re.fullmatch(r"[a-z][a-z0-9-]{0,99}", item) for item in items):
            raise ValueError("ONCALL_INVALID_ALLOWLIST")
        if len(items) != len(set(items)):
            raise ValueError("ONCALL_DUPLICATE_ALLOWLIST")
    key = value.get("kms_key_arn")
    if key is not None and (not isinstance(key, str) or not re.fullmatch(
        rf"arn:aws:kms:{re.escape(region)}:{re.escape(account)}:key/[0-9a-f-]{{36}}", key
    )):
        raise ValueError("ONCALL_INVALID_KEY_ARN")


if __name__ == "__main__":
    try:
        validate(os.environ.get("TF_VAR_oncall_receiver", "null"), os.environ["PAWLOCAL_AWS_ACCOUNT_ID"], os.environ["AWS_REGION"])
    except (ValueError, KeyError) as error:
        # Codes refer to schema fields, never echo raw operator JSON/private data.
        raise SystemExit("Invalid optional on-call operator configuration: " + str(error)) from None
    print("Validated optional public on-call operator configuration.")
