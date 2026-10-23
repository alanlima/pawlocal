"""Validate only reviewed public operator bindings before Terraform saves inputs."""

from __future__ import annotations

import json
import os
import re
import sys
from urllib.parse import urlsplit

_ALLOWED = {"enabled", "frontend_enabled", "stack_url", "stack_slug", "faro_app_name", "kms_key_arn", "datasources", "metrics_datasource_uid", "logs_datasource_uid", "traces_datasource_uid", "usage_datasource_uid"}
# Fields removed in #260: now auto-discovered by Terraform via grafana_cloud_stack /
# grafana_frontend_o11y_app data sources. Kept here to produce a specific error.
_REMOVED = {"faro_collector_url", "otlp_endpoint", "otlp_instance_id"}


def validate(raw, account, region):
    if len(raw.encode("utf-8")) > 8192:
        raise ValueError("Hosted bindings are too large (limit 8192 bytes)")

    def unique(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError(f"Duplicate hosted field: {key!r}")
            result[key] = value
        return result

    value = json.loads(raw, object_pairs_hook=unique)
    if value is None:
        return

    if not isinstance(value, dict):
        raise ValueError("Hosted observability config must be a JSON object or null")

    unknown = set(value) - _ALLOWED
    removed = unknown & _REMOVED
    truly_unknown = unknown - _REMOVED
    if removed:
        raise ValueError(
            f"Removed hosted field(s) no longer accepted: {', '.join(sorted(removed))}. "
            f"These are now auto-discovered by Terraform via grafana_cloud_stack / "
            f"grafana_frontend_o11y_app data sources (see #260). "
            f"Remove them from PAWLOCAL_HOSTED_OBSERVABILITY_CONFIG."
        )
    if truly_unknown:
        raise ValueError(
            f"Unknown hosted field(s): {', '.join(sorted(truly_unknown))}. "
            f"Allowed: {', '.join(sorted(_ALLOWED))}."
        )

    if type(value.get("enabled", False)) is not bool:
        raise ValueError(
            f"'enabled' must be a boolean (true/false), got: {value['enabled']!r}"
        )
    if "frontend_enabled" in value and type(value["frontend_enabled"]) is not bool:
        raise ValueError(
            f"'frontend_enabled' must be a boolean (true/false), got: {value['frontend_enabled']!r}"
        )

    # stack_url is required only when telemetry is active (backend or frontend).
    # A fully-disabled config object may omit it.
    telemetry_active = value.get("enabled", False) or value.get("frontend_enabled", False)
    if telemetry_active and "stack_url" not in value:
        raise ValueError(
            "'stack_url' is required when 'enabled' or 'frontend_enabled' is true"
        )

    if "stack_slug" in value and (
        not isinstance(value["stack_slug"], str)
        or not re.fullmatch(r"[a-z0-9-]+", value["stack_slug"])
    ):
        raise ValueError(
            f"'stack_slug' must be lowercase alphanumeric with hyphens, got: {value['stack_slug']!r}"
        )

    if "faro_app_name" in value and (
        not isinstance(value["faro_app_name"], str)
        or not re.fullmatch(r"[a-z0-9-]+", value["faro_app_name"])
    ):
        raise ValueError(
            f"'faro_app_name' must be lowercase alphanumeric with hyphens, got: {value['faro_app_name']!r}"
        )

    if "stack_url" in value:
        text = value["stack_url"]
        if not isinstance(text, str) or any(c in text for c in "\r\n\x00"):
            raise ValueError("'stack_url' must be a plain string with no control characters")
        url = urlsplit(text)
        if url.scheme != "https":
            raise ValueError(f"'stack_url' must use https, got scheme: {url.scheme!r}")
        if not url.hostname or not url.hostname.endswith(".grafana.net"):
            raise ValueError(f"'stack_url' hostname must end with .grafana.net, got: {url.hostname!r}")
        if url.username or url.password:
            raise ValueError("'stack_url' must not include credentials")
        if url.port is not None:
            raise ValueError("'stack_url' must not include a port")
        if url.query or url.fragment:
            raise ValueError("'stack_url' must not include a query string or fragment")
        if not re.fullmatch(r"/?", url.path):
            raise ValueError(f"'stack_url' path must be empty or a single slash, got: {url.path!r}")

    key = value.get("kms_key_arn")
    if key is not None and (
        not isinstance(key, str)
        or not re.fullmatch(
            rf"arn:aws:kms:{re.escape(region)}:{re.escape(account)}:key/[0-9a-f-]{{36}}",
            key,
        )
    ):
        raise ValueError(
            f"'kms_key_arn' must be an existing key ARN for account {account} in {region}, got: {key!r}"
        )

    if "datasources" in value:
        ds = value["datasources"]
        if not isinstance(ds, dict):
            raise ValueError("'datasources' must be a JSON object")
        allowed_signals = {"metrics", "logs", "traces", "usage"}
        unknown_signals = set(ds) - allowed_signals
        if unknown_signals:
            raise ValueError(
                f"Unknown signal(s) in 'datasources': {', '.join(sorted(unknown_signals))}. "
                f"Allowed: {', '.join(sorted(allowed_signals))}."
            )
        allowed_binding_keys = {"uid", "name"}
        for sig, binding in ds.items():
            if not isinstance(binding, dict):
                raise ValueError(f"'datasources.{sig}' must be an object")
            unknown_keys = set(binding) - allowed_binding_keys
            if unknown_keys:
                raise ValueError(
                    f"Unknown field(s) in 'datasources.{sig}': {', '.join(sorted(unknown_keys))}. "
                    f"Allowed: {', '.join(sorted(allowed_binding_keys))}."
                )
            if "uid" in binding and not isinstance(binding["uid"], str):
                raise ValueError(f"'datasources.{sig}.uid' must be a string")
            if "name" in binding and not isinstance(binding["name"], str):
                raise ValueError(f"'datasources.{sig}.name' must be a string")

    for field in (
        "metrics_datasource_uid",
        "logs_datasource_uid",
        "traces_datasource_uid",
        "usage_datasource_uid",
    ):
        if field in value and not isinstance(value[field], str):
            raise ValueError(f"'{field}' must be a string")

    return value


def resolve_owning_stack_url(parsed, region):
    recorded_url = ""
    env_name = os.environ.get("PAWLOCAL_ENVIRONMENT", "").strip()
    if env_name:
        import boto3
        from botocore.exceptions import ClientError
        try:
            ssm = boto3.client("ssm", region_name=region)
            param = f"/pawlocal/{env_name}/config/grafana/stack-url"
            resp = ssm.get_parameter(Name=param)
            recorded_url = resp.get("Parameter", {}).get("Value", "").strip().rstrip("/")
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            if code != "ParameterNotFound":
                raise
        except Exception as exc:
            if "ParameterNotFound" not in str(exc):
                raise

    input_url = parsed.get("stack_url", "").strip().rstrip("/") if isinstance(parsed, dict) else ""

    # Resolve recorded owning URL first; require an explicit migration before switching endpoints
    if recorded_url:
        if input_url and input_url != recorded_url:
            raise ValueError(
                f"Configured stack_url ({input_url!r}) differs from recorded owning stack ({recorded_url!r}). "
                f"Dashboards must be migrated or destroyed on the owning stack before switching endpoints."
            )
        return recorded_url

    if input_url:
        return input_url

    url = os.environ.get("PAWLOCAL_GRAFANA_URL", "").strip().rstrip("/")
    if url:
        return url

    return "https://alanlima.grafana.net"

if __name__ == "__main__":
    parsed = None
    try:
        parsed = validate(
            os.environ.get("TF_VAR_hosted_observability", "null"),
            os.environ["PAWLOCAL_AWS_ACCOUNT_ID"],
            os.environ["AWS_REGION"],
        )
    except KeyError as exc:
        sys.exit(
            f"Missing required environment variable: {exc}. "
            f"Expected PAWLOCAL_AWS_ACCOUNT_ID and AWS_REGION to be set."
        )
    except (ValueError, TypeError) as exc:
        sys.exit(
            f"Invalid public hosted observability operator configuration: {exc}\n"
            f"Check the PAWLOCAL_HOSTED_OBSERVABILITY_CONFIG environment variable "
            f"in the plan Environment and see docs/hosted-telemetry-operations.md."
        )
    url = resolve_owning_stack_url(parsed, os.environ["AWS_REGION"])
    if "GITHUB_ENV" in os.environ:
        with open(os.environ["GITHUB_ENV"], "a", encoding="utf-8") as f:
            f.write(f"GRAFANA_URL={url}\n")
    if "GITHUB_OUTPUT" in os.environ:
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as f:
            f.write(f"grafana_url={url}\n")
    print(
        "Validated public hosted observability bindings; no secret payloads accepted."
    )
