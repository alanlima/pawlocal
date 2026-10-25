"""Build reproducible Grafana dashboard definitions from the #225 signal contract."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SELECTOR = 'environment=~"$environment",service=~"$service",release=~"$release"'
BASE = "pawlocal_api_requests_total"
OWNER = "pawlocal-managed-226"


def metric(name, labels=""):
    return name + "{" + SELECTOR + ("," + labels if labels else "") + "}"


def panel(
    title, query, unit="short", datasource="METRICS", kind="timeseries", description=""
):
    return {
        "title": title,
        "type": kind,
        "description": description,
        "datasource": {
            "type": {
                "METRICS": "prometheus",
                "USAGE": "prometheus",
                "LOGS": "loki",
                "TRACES": "tempo",
            }[datasource],
            "uid": f"__{datasource}_UID__",
        },
        "targets": [
            {
                "refId": "A",
                "expr": query,
                "legendFormat": "{{route}}{{dependency}}{{signal}}{{release}}",
            }
        ]
        if datasource in ("METRICS", "USAGE")
        else [{"refId": "A", "expr": query}]
        if datasource == "LOGS"
        else [{"refId": "A", "queryType": "traceql", "query": query}],
        "fieldConfig": {
            "defaults": {"unit": unit, "noValue": "NO DATA / UNKNOWN"},
            "overrides": [],
        },
        "options": {"legend": {"displayMode": "table", "placement": "bottom"}},
    }


def build():
    request_rate = f"sum by (route) (rate({metric(BASE)}[5m]))"
    p95 = f"histogram_quantile(0.95, sum by (le, route) (rate({metric('pawlocal_api_duration_seconds_bucket')}[5m])))"
    error_rate = f"sum by (route) (rate({metric(BASE, 'outcome="error"')}[5m]))"
    dependency_rate = f"sum by (dependency, outcome) (rate({metric('pawlocal_dependency_requests_total')}[5m]))"
    dependency_p95 = f"histogram_quantile(0.95, sum by (le, dependency) (rate({metric('pawlocal_dependency_duration_seconds_bucket')}[5m])))"
    probe = 'probe_success{job=~"pawlocal-$environment-search-detail"}'
    logs = '{service_name=~"$service"} | json | environment=~"$environment" | release=~"$release"'
    dashboards = {
        "journey": [
            panel("Search and details requests", request_rate, "reqps"),
            panel("API p95 latency", p95, "s"),
            panel("External search to details success", probe, "bool"),
            panel("API errors by route", error_rate, "reqps"),
        ],
        "application": [
            panel("Request volume by route", request_rate, "reqps"),
            panel("p95 route latency", p95, "s"),
            panel(
                "Status classes",
                f"sum by (status_class) (rate({metric(BASE)}[5m]))",
                "reqps",
            ),
            panel("Recent safe application logs", logs, datasource="LOGS", kind="logs"),
        ],
        "dependencies": [
            panel("Dependency request outcomes", dependency_rate, "reqps"),
            panel("Dependency p95 latency", dependency_p95, "s"),
            panel(
                "Dependency errors",
                f"sum by (dependency) (rate({metric('pawlocal_dependency_requests_total', 'outcome="error"')}[5m]))",
                "reqps",
            ),
            panel(
                "Safe dependency logs",
                logs + ' | operation="query"',
                datasource="LOGS",
                kind="logs",
            ),
        ],
        "releases": [
            panel(
                "Request rate by immutable release digest",
                f"sum by (release) (rate({metric(BASE)}[5m]))",
                "reqps",
            ),
            panel(
                "p95 latency by release",
                f"histogram_quantile(0.95, sum by (le, release) (rate({metric('pawlocal_api_duration_seconds_bucket')}[5m])))",
                "s",
            ),
            panel(
                "Errors by release",
                f"sum by (release) (rate({metric(BASE, 'outcome="error"')}[5m]))",
                "reqps",
            ),
        ],
        "telemetry": [
            panel(
                "Completed exports by signal",
                f"sum by (signal) (rate({metric('pawlocal_telemetry_exports_total')}[10m]))",
                "ops",
            ),
            panel(
                "Export failures (may be absent before first failure)",
                f"sum by (signal) (rate({metric('pawlocal_telemetry_export_failures_total')}[10m]))",
                "ops",
            ),
            panel(
                "Missing API telemetry: 1 means absent",
                f"absent_over_time({metric(BASE)}[10m])",
                "bool",
            ),
            panel(
                "Account active metric series (shared quota)",
                "sum(grafanacloud_instance_active_series)",
                datasource="USAGE",
            ),
            panel(
                "Account active log streams",
                "sum(grafanacloud_logs_instance_active_streams)",
                datasource="USAGE",
            ),
            panel(
                "Account trace bytes per second",
                "sum(grafanacloud_traces_instance_bytes_received_per_second)",
                "Bps",
                datasource="USAGE",
            ),
        ],
        "incidents": [
            panel("External journey success", probe, "bool"),
            panel("Failing routes", error_rate, "reqps"),
            panel("Redacted logs and trace IDs", logs, datasource="LOGS", kind="logs"),
            panel(
                "Related traces",
                '{ resource.service.name = "$service" && resource.deployment.environment.name = "$environment" && resource.service.version =~ "$release" }',
                datasource="TRACES",
                kind="table",
                description="Sampled traces for the selected environment and release. Open a result in Explore or copy its trace ID into Trace ID for the waterfall below. Request logs with trace_sampled=false intentionally have no stored trace; older logs omit this field.",
            ),
            panel(
                "Selected trace waterfall",
                "$traceId",
                datasource="TRACES",
                kind="traces",
                description="Enter a sampled trace ID in the Trace ID box above. Inspect browser, API, application and database spans when those components exported the same trace.",
            ),
        ],
    }
    result = {}
    for name, panels in dashboards.items():
        for index, item in enumerate(panels):
            item["id"] = index + 1
            item["gridPos"] = {
                "x": (index % 2) * 12,
                "y": (index // 2) * 9,
                "w": 12,
                "h": 9,
            }
        result[name] = {
            "id": None,
            "uid": f"pawlocal-{name}",
            "title": f"PawLocal {name.title()}",
            "schemaVersion": 39,
            "version": 0,
            "tags": [OWNER],
            "editable": False,
            "refresh": "1m",
            "time": {"from": "now-1h", "to": "now"},
            "description": "Source-controlled #226. Missing data is unknown, never zero/healthy. Release is the deployed sha256 image digest. Authorization is enforced by datasource/token scopes, not dashboard variables.",
            "links": [
                {
                    "title": "Incident triage",
                    "type": "link",
                    "url": "/d/pawlocal-incidents",
                    "includeVars": True,
                },
                {
                    "title": "Metrics / logs / traces Explore",
                    "type": "link",
                    "url": "/explore",
                    "includeVars": False,
                },
                {
                    "title": "Account quota and usage",
                    "type": "link",
                    "url": "/a/grafana-billing-usage-app/usage",
                },
            ],
            "templating": {
                "list": [
                    {
                        "name": "environment",
                        "type": "query",
                        "datasource": {"type": "prometheus", "uid": "__METRICS_UID__"},
                        "query": f"label_values({BASE}, environment)",
                        "current": {"text": "development", "value": "development"},
                        "refresh": 1,
                    },
                    {
                        "name": "service",
                        "type": "constant",
                        "query": "pawlocal-api",
                        "current": {"text": "pawlocal-api", "value": "pawlocal-api"},
                    },
                    {
                        "name": "release",
                        "type": "query",
                        "datasource": {"type": "prometheus", "uid": "__METRICS_UID__"},
                        "query": f'label_values({BASE}{{environment=~"$environment",service="pawlocal-api"}}, release)',
                        "includeAll": True,
                        "allValue": ".+",
                        "current": {"text": "All", "value": "$__all"},
                        "refresh": 2,
                    },
                ]
            },
            "annotations": {"list": []},
            "panels": panels,
        }
        if name == "incidents":
            result[name]["templating"]["list"].append(
                {
                    "name": "traceId",
                    "label": "Trace ID",
                    "type": "textbox",
                    "query": "",
                    "current": {"text": "", "value": ""},
                }
            )
    return result


if __name__ == "__main__":
    for name, definition in build().items():
        (ROOT / "dashboards" / f"{name}.json").write_text(
            json.dumps(definition, indent=2) + "\n", encoding="utf-8"
        )
