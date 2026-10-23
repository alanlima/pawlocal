"""Fixed bounded Grafana Stack queries and model-facing allowlisted summaries.

Uses a distinct read-only Stack service-account token, never a Cloud Access
Policy token or the administrator provisioning credential. Free-tier Viewer
may be stack-wide: this broker, not folder labels, enforces payload scope.
"""

import json
import math
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

from quota import Denied, strict_json
from quota_gateway import NoRedirect


def number(value, maximum=1e9):
    try:
        result = float(value)
    except (ValueError, TypeError):
        return None
    return result if math.isfinite(result) and 0 <= result <= maximum else None


def frames(value):
    if not isinstance(value, dict) or set(value.get("results", {})) != {"A"}:
        raise Denied("unknown datasource result")
    result = value["results"]["A"]
    if (
        result.get("error")
        or result.get("status", 200) != 200
        or not isinstance(result.get("frames"), list)
        or len(result["frames"]) > 20
    ):
        raise Denied("datasource unavailable or result bound")
    for frame in result["frames"]:
        fields = frame.get("schema", {}).get("fields")
        values = frame.get("data", {}).get("values")
        if (
            not isinstance(fields, list)
            or not isinstance(values, list)
            or len(fields) != len(values)
            or len(fields) > 32
            or any(
                not isinstance(column, list) or len(column) > 20 for column in values
            )
        ):
            raise Denied("unknown or excessive dataframe")
    return result["frames"]


def summarize(signal, response):
    result = []
    for frame in frames(response):
        fields = frame["schema"]["fields"]
        values = frame["data"]["values"]
        if signal == "metrics":
            for field, column in zip(fields, values):
                if field.get("type") != "number":
                    continue
                labels = field.get("labels", {})
                metric = labels.get("diagnostic")
                if metric not in {
                    "api_requests",
                    "api_p95_seconds",
                    "dependency_requests",
                    "dependency_p95_seconds",
                }:
                    continue
                if (
                    metric.startswith("dependency_")
                    and labels.get("operation") != "query"
                ):
                    continue
                for sample in column:
                    value = number(sample)
                    if value is not None:
                        result.append(
                            {
                                "metric": metric,
                                "operation": "query"
                                if metric.startswith("dependency_")
                                else None,
                                "value": value,
                                "outcome": labels.get("outcome")
                                if labels.get("outcome") in {"success", "error"}
                                else "other",
                                "status_class": labels.get("status_class")
                                if labels.get("status_class")
                                in {"2xx", "3xx", "4xx", "5xx"}
                                else "other",
                            }
                        )
        elif signal == "logs":
            for field, column in zip(fields, values):
                if field.get("name") not in {"Line", "line"}:
                    continue
                for line in column:
                    if not isinstance(line, str) or len(line) > 2048:
                        raise Denied("log line bound")
                    parts = line.split("|")
                    if len(parts) != 7:
                        raise Denied("unsupported log projection")
                    event, operation, outcome, status, duration, trace_id, error = parts
                    result.append(
                        {
                            "event": event
                            if event
                            in {
                                "api.request.started",
                                "api.request.completed",
                                "api.synthetic_failure",
                                "db.query.started",
                                "db.query.completed",
                                "db.query.failed",
                            }
                            else "other",
                            "operation": operation
                            if operation
                            in {"http_request", "query", "search", "detail"}
                            else "other",
                            "outcome": outcome
                            if outcome in {"success", "error"}
                            else "other",
                            "http_status": int(status)
                            if re.fullmatch(r"[1-5]\d\d", status)
                            else None,
                            "duration_ms": number(duration, 600000),
                            "trace_id": trace_id
                            if re.fullmatch(r"[0-9a-f]{32}", trace_id)
                            else None,
                            "error": error
                            if error
                            in {
                                "unhandled_api_error",
                                "api_request_failed",
                                "database_timeout",
                                "database_unavailable",
                                "synthetic_db_timeout",
                                "synthetic_db_error",
                            }
                            else "other",
                        }
                    )
        else:
            by_name = {
                field.get("name"): column for field, column in zip(fields, values)
            }
            traces = by_name.get("traceID", by_name.get("traceId", []))
            durations = by_name.get("durationMs", by_name.get("duration", []))
            for index, trace in enumerate(traces):
                if isinstance(trace, str) and re.fullmatch(r"[0-9a-f]{32}", trace):
                    result.append(
                        {
                            "trace_id": trace,
                            "duration_ms": number(durations[index], 600000)
                            if index < len(durations)
                            else None,
                        }
                    )
        if len(result) > 20:
            raise Denied("summary row bound")
    return {
        "status": "samples" if result else "no_samples_unknown_health",
        "rows": result,
    }


def gather(trusted, stack_url, token, alert, release, deadline, opener=None):
    environment = alert["environment"]
    service = alert.get("service", "")
    digest = release["image_digest"]
    if not isinstance(service, str) or not re.fullmatch(r"[a-z][a-z0-9-]{0,99}", service) or environment not in {"development", "production"} or not re.fullmatch(
        r"sha256:[0-9a-f]{64}", digest
    ):
        raise Denied("diagnostic scope invalid")
    parsed = urllib.parse.urlsplit(stack_url)
    if (
        parsed.scheme != "https"
        or not re.fullmatch(r"[a-z0-9-]+\.grafana\.net", parsed.netloc)
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
        or not token
    ):
        raise Denied("read-only Stack auth/URL unavailable")
    binding = strict_json(
        (Path(trusted) / "observability/grafana/cloud/bindings.json").read_bytes()
    )
    selected = binding.get("environments", {}).get(environment, {})
    if (
        binding.get("version") != 1
        or selected.get("enabled") is not True
        or not selected.get("approval")
        or (selected.get("stack") or {}).get("url", "").rstrip("/")
        != stack_url.rstrip("/")
    ):
        raise Denied("approved datasource bindings missing")
    sources = selected.get("datasources", {})
    if set(sources) != {"metrics", "logs", "traces"} or any(
        not isinstance(sources[name], dict)
        or not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", str(sources[name].get("uid", "")))
        for name in sources
    ):
        raise Denied("exact datasource UIDs missing")
    end = int(time.time() * 1000)
    start = end - 10 * 60 * 1000
    selector = f'environment="{environment}",service="{service}",release="{digest}"'
    expressions = {
        "metrics": {
            "expr": " or ".join(
                [
                    f'label_replace(sum by(outcome)(increase(pawlocal_api_requests_total{{{selector}}}[5m])),"diagnostic","api_requests","","")',
                    f'label_replace(histogram_quantile(0.95,sum by(le)(rate(pawlocal_api_duration_seconds_bucket{{{selector}}}[5m]))),"diagnostic","api_p95_seconds","","")',
                    f'label_replace(sum by(operation,outcome)(increase(pawlocal_dependency_requests_total{{{selector}}}[5m])),"diagnostic","dependency_requests","","")',
                    f'label_replace(histogram_quantile(0.95,sum by(le,operation)(rate(pawlocal_dependency_duration_seconds_bucket{{{selector}}}[5m]))),"diagnostic","dependency_p95_seconds","","")',
                ]
            ),
            "instant": True,
            "range": False,
            "format": "time_series",
        },
        "logs": {
            "expr": '{service_name="' + service + '"} | json | environment="'
            + environment
            + '" | release="'
            + digest
            + '" | line_format "{{.event_code}}|{{.operation}}|{{.outcome}}|{{.http_status}}|{{.duration_ms}}|{{.trace_id}}|{{.error_code}}"',
            "queryType": "range",
            "maxLines": 20,
            "direction": "backward",
        },
        "traces": {
            "query": '{ resource.service.name = "' + service + '" && resource.deployment.environment.name = "'
            + environment
            + '" && resource.service.version = "'
            + digest
            + '" }',
            "queryType": "traceql",
            "limit": 20,
            "spss": 3,
        },
    }
    result = {
        "environment": environment,
        "release": digest,
        "window_seconds": 600,
        "signals": {},
    }
    types = {"metrics": "prometheus", "logs": "loki", "traces": "tempo"}
    for signal, expression in expressions.items():
        if time.time() >= deadline:
            raise Denied("diagnostic deadline exhausted")
        payload = {
            "from": str(start),
            "to": str(end),
            "queries": [
                {
                    "refId": "A",
                    "datasource": {
                        "uid": sources[signal]["uid"],
                        "type": types[signal],
                    },
                    "maxDataPoints": 20,
                    "intervalMs": 30000,
                    **expression,
                }
            ],
        }
        request = urllib.request.Request(
            stack_url.rstrip("/") + "/api/ds/query",
            data=json.dumps(payload).encode(),
            method="POST",
            headers={
                "Authorization": "Bearer " + token,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        with (opener or urllib.request.build_opener(NoRedirect)).open(
            request, timeout=min(15, deadline - time.time())
        ) as response:
            raw = response.read(256 * 1024 + 1)
            if response.status != 200 or len(raw) > 256 * 1024:
                raise Denied("diagnostic query unavailable/bound")
            result["signals"][signal] = summarize(signal, strict_json(raw))
    return result
