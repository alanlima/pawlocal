"""Validate only reviewed public operator bindings before Terraform saves inputs."""

from __future__ import annotations

import json
import os
import re
from urllib.parse import urlsplit


def validate(raw, account, region):
    if len(raw.encode("utf-8")) > 8192:
        raise ValueError("Hosted bindings are too large")

    def unique(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("Duplicate hosted field")
            result[key] = value
        return result

    value = json.loads(raw, object_pairs_hook=unique)
    if value is None:
        return
    required = {"stack_url"}
    if (
        not isinstance(value, dict)
        or not required <= value.keys()
        or set(value) - required - {"enabled", "frontend_enabled", "stack_slug", "faro_app_name", "kms_key_arn"}
    ):
        raise ValueError("Unknown or missing public hosted field")
    if type(value.get("enabled", False)) is not bool or (
        "frontend_enabled" in value and type(value["frontend_enabled"]) is not bool
    ):
        raise ValueError("Hosted mode must be boolean")
    if "stack_slug" in value and (
        not isinstance(value["stack_slug"], str)
        or not re.fullmatch(r"[a-z0-9-]+", value["stack_slug"])
    ):
        raise ValueError("Invalid Grafana stack slug")
    if "faro_app_name" in value and (
        not isinstance(value["faro_app_name"], str)
        or not re.fullmatch(r"[a-z0-9-]+", value["faro_app_name"])
    ):
        raise ValueError("Invalid Faro application name")
    paths = {
        "stack_url": r"/?",
    }
    for name, path in paths.items():
        text = value.get(name)
        if not isinstance(text, str) or any(c in text for c in "\r\n\x00"):
            raise ValueError("Invalid public hosted endpoint")
        url = urlsplit(text)
        if (
            url.scheme != "https"
            or not url.hostname
            or not url.hostname.endswith(".grafana.net")
            or url.username
            or url.password
            or url.port is not None
            or url.query
            or url.fragment
            or not re.fullmatch(path, url.path)
        ):
            raise ValueError("Invalid public hosted endpoint")
    key = value.get("kms_key_arn")
    if key is not None and (
        not isinstance(key, str)
        or not re.fullmatch(
            rf"arn:aws:kms:{re.escape(region)}:{re.escape(account)}:key/[0-9a-f-]{{36}}",
            key,
        )
    ):
        raise ValueError("Use an existing exact matching KMS key")


if __name__ == "__main__":
    try:
        validate(
            os.environ.get("TF_VAR_hosted_observability", "null"),
            os.environ["PAWLOCAL_AWS_ACCOUNT_ID"],
            os.environ["AWS_REGION"],
        )
    except (ValueError, TypeError, KeyError):
        raise SystemExit(
            "Invalid public hosted observability operator configuration"
        ) from None
    print(
        "Validated public hosted observability bindings; no secret payloads accepted."
    )
