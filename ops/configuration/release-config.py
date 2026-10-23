"""Project a same-run public snapshot into the hosted release consumer contract."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from urllib.parse import urlsplit

from reconcile import FRONTEND_FIELDS, validate_values


def grafana_url(value, path):
    if not isinstance(value, str):
        raise TypeError("Missing hosted endpoint")
    url = urlsplit(value)
    if (
        url.scheme != "https"
        or not url.hostname
        or not url.hostname.endswith(".grafana.net")
        or url.username
        or url.password
        or url.port is not None
        or url.query
        or url.fragment
        or any(c in value for c in "\r\n\x00")
        or not re.fullmatch(path, url.path)
    ):
        raise ValueError("Invalid hosted endpoint")
    return value


def project(values, environment):
    if not isinstance(values, dict) or any(
        not isinstance(k, str) or not isinstance(v, str) for k, v in values.items()
    ):
        raise ValueError("Invalid public consumer snapshot")
    if not FRONTEND_FIELDS <= values.keys():
        return {}
    validate_values(
        {k: v for k, v in values.items() if k in FRONTEND_FIELDS}, environment
    )
    mode = values.get("VITE_TELEMETRY_ENABLED")
    if mode is None or values.get("PAWLOCAL_TELEMETRY_ENABLED") is None:
        return {}
    if mode not in {"true", "false"} or values["PAWLOCAL_TELEMETRY_ENABLED"] != mode:
        raise ValueError("Hosted release telemetry modes differ")
    result = {k: values[k] for k in FRONTEND_FIELDS}
    result["VITE_TELEMETRY_ENABLED"] = mode
    if mode == "true":
        result["VITE_FARO_COLLECTOR_URL"] = grafana_url(
            values.get("VITE_FARO_COLLECTOR_URL"), r"/collect/[A-Za-z0-9_-]+"
        )
        grafana_url(values.get("OTEL_EXPORTER_OTLP_ENDPOINT"), r"/otlp/?")
        if not re.fullmatch(
            r"[0-9]{1,20}", values.get("PAWLOCAL_GRAFANA_OTLP_INSTANCE_ID", "")
        ):
            raise ValueError("Missing verified OTLP instance identifier")
    return result


if __name__ == "__main__":
    try:
        value = project(
            json.loads(os.environ["RECONCILED_CONFIGURATION"]),
            os.environ["SELECTED_ENVIRONMENT"],
        )
        with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as output:
            output.write(
                "frontend_config=" + json.dumps(value, separators=(",", ":")) + "\n"
            )
    except (ValueError, KeyError, TypeError, OSError):
        raise SystemExit("Release consumer configuration is invalid") from None
