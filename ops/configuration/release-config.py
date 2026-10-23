"""Project a same-run public snapshot into the hosted release consumer contract."""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

from reconcile import FRONTEND_FIELDS, validate_values


def grafana_url(value, path, field_name="hosted endpoint"):
    if not isinstance(value, str):
        raise TypeError(f"Missing {field_name}")
    if any(c in value for c in "\r\n\x00"):
        raise ValueError(f"{field_name} must not contain control characters")
    url = urlsplit(value)
    if url.scheme != "https":
        raise ValueError(f"{field_name} must use https scheme (got {url.scheme!r})")
    if not url.hostname or not url.hostname.endswith(".grafana.net"):
        raise ValueError(f"{field_name} host must end with .grafana.net (got {url.hostname!r})")
    if url.username or url.password:
        raise ValueError(f"{field_name} must not contain credentials")
    if url.port is not None:
        raise ValueError(f"{field_name} must not specify a custom port")
    if url.query or url.fragment:
        raise ValueError(f"{field_name} must not contain query or fragment")
    if not re.fullmatch(path, url.path):
        raise ValueError(
            f"{field_name} path {url.path!r} does not match expected pattern {path!r}"
        )
    return value


def project(values, environment):
    if not isinstance(values, dict) or any(
        not isinstance(k, str) or not isinstance(v, str) for k, v in values.items()
    ):
        raise ValueError("Invalid public consumer snapshot: must be a dict of strings")
    if not FRONTEND_FIELDS <= values.keys():
        return {}
    validate_values(
        {k: v for k, v in values.items() if k in FRONTEND_FIELDS}, environment
    )
    mode = values.get("VITE_TELEMETRY_ENABLED")
    if mode is None or values.get("PAWLOCAL_TELEMETRY_ENABLED") is None:
        return {}
    backend = values["PAWLOCAL_TELEMETRY_ENABLED"]
    if mode not in {"true", "false"}:
        raise ValueError(f"VITE_TELEMETRY_ENABLED must be 'true' or 'false', got {mode!r}")
    if backend not in {"true", "false"}:
        raise ValueError(f"PAWLOCAL_TELEMETRY_ENABLED must be 'true' or 'false', got {backend!r}")
    result = {k: values[k] for k in FRONTEND_FIELDS}
    result["VITE_TELEMETRY_ENABLED"] = mode
    result["PAWLOCAL_TELEMETRY_ENABLED"] = backend
    if mode == "true":
        result["VITE_FARO_COLLECTOR_URL"] = grafana_url(
            values.get("VITE_FARO_COLLECTOR_URL"),
            r"/collect/[A-Za-z0-9_-]+",
            field_name="VITE_FARO_COLLECTOR_URL",
        )
    if backend == "true":
        grafana_url(
            values.get("OTEL_EXPORTER_OTLP_ENDPOINT"),
            r"(/otlp)?/?",
            field_name="OTEL_EXPORTER_OTLP_ENDPOINT",
        )
        instance_id = values.get("PAWLOCAL_GRAFANA_OTLP_INSTANCE_ID", "")
        if not re.fullmatch(r"[0-9]{1,20}", instance_id):
            raise ValueError(
                f"Missing or invalid verified OTLP instance identifier (PAWLOCAL_GRAFANA_OTLP_INSTANCE_ID): {instance_id!r}"
            )
    return result


if __name__ == "__main__":
    try:
        raw_config = os.environ.get("RECONCILED_CONFIGURATION")
        if not raw_config:
            raise KeyError("RECONCILED_CONFIGURATION")
        env_name = os.environ.get("SELECTED_ENVIRONMENT")
        if not env_name:
            raise KeyError("SELECTED_ENVIRONMENT")
        value = project(json.loads(raw_config), env_name)
        output_file = os.environ.get("GITHUB_OUTPUT")
        if not output_file:
            raise KeyError("GITHUB_OUTPUT")
        with Path(output_file).open("a", encoding="utf-8") as output:
            output.write(
                "frontend_config=" + json.dumps(value, separators=(",", ":")) + "\n"
            )
    except KeyError as exc:
        sys.exit(f"Release consumer configuration error: missing environment variable {exc}")
    except (ValueError, TypeError, json.JSONDecodeError, OSError) as exc:
        sys.exit(f"Release consumer configuration is invalid: {exc}")
