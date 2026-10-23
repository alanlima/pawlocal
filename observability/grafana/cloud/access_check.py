"""Read-only metadata checks; never print API payloads, identities or credentials."""

from __future__ import annotations

import os
import re
from pathlib import Path
from urllib.parse import urlsplit

from provision import ProvisionError, Transport, faro_management_url, otlp_http_endpoint

CHECKS = (
    "Cloud stack metadata",
    "Cloud connection metadata",
    "Faro application list",
    "Stack folder list",
    "Stack datasource list",
    "Query token self-permissions metadata",
    "Synthetic probe list",
    "Synthetic check list",
)
SECRETS = {
    "cloud": "GRAFANA_CLOUD_ACCESS_POLICY_TOKEN",
    "stack": "GRAFANA_SERVICE_ACCOUNT_TOKEN",
    "query": "PAWLOCAL_GRAFANA_QUERY_TOKEN",
    "sm": "GRAFANA_SYNTHETIC_MONITORING_TOKEN",
}


def origin(value, pattern, paths=("", "/")):
    if not isinstance(value, str) or any(c.isspace() for c in value):
        raise ProvisionError("Invalid endpoint")
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not re.fullmatch(pattern, parsed.hostname or "")
        or parsed.port is not None
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path not in paths
    ):
        raise ProvisionError("Invalid endpoint")
    return f"https://{parsed.hostname}"


class ReadOnlyTransport(Transport):
    """The provisioning transport's redirect/body/time bounds plus an exact GET allowlist."""

    def __init__(self):
        super().__init__()
        self.allowed = set()

    def request(self, method, url, token, payload=None, stack_id=None, missing=False):
        if method != "GET" or payload is not None or url not in self.allowed:
            raise ProvisionError("Read-only request rejected")
        return super().request(method, url, token, stack_id=stack_id)


def check(stack_url, region, sm_url, credentials, transport=None):
    stack = origin(stack_url, r"[a-z0-9][a-z0-9-]*[.]grafana[.]net")
    if not isinstance(region, str) or not re.fullmatch(r"[a-z0-9-]{1,80}", region):
        raise ProvisionError("Invalid region")
    sm = (
        origin(
            sm_url,
            r"synthetic-monitoring-api-[a-z0-9-]+[.]grafana[.]net",
            ("", "/", "/api/v1", "/api/v1/"),
        )
        if sm_url
        else None
    )
    slug = urlsplit(stack).hostname.split(".")[0]
    transport = transport or ReadOnlyTransport()
    results = {name: "PENDING" for name in CHECKS}

    def get(label, url, credential, shape, stack_id=None):
        token = credentials.get(SECRETS[credential])
        if not isinstance(token, str) or not token.strip():
            return None
        if any(c in token for c in "\r\n\x00"):
            results[label] = "FAIL"
            return None
        transport.allowed.add(url)
        try:
            value = transport.request("GET", url, token, stack_id=stack_id)
            if not shape(value):
                raise ProvisionError("Unexpected metadata shape")
            results[label] = "PASS"
            return value
        except Exception:  # noqa: BLE001 - server/transport diagnostics may contain private content
            results[label] = "FAIL"
            return None

    remote = get(
        CHECKS[0],
        f"https://grafana.com/api/instances/{slug}",
        "cloud",
        lambda value: (
            isinstance(value, dict)
            and type(value.get("id")) is int
            and value["id"] > 0
            and value.get("slug") == slug
            and value.get("url", "").rstrip("/") == stack
            and value.get("regionSlug") == region
        ),
    )
    if remote is not None:
        get(
            CHECKS[1],
            f"https://grafana.com/api/instances/{slug}/connections",
            "cloud",
            lambda value: (
                isinstance(value, dict)
                and isinstance(value.get("otlpHttpUrl"), str)
                and bool(otlp_http_endpoint(value["otlpHttpUrl"]))
            ),
        )
        try:
            faro = faro_management_url(region, remote.get("createdAt"))
            # Only the pinned regional URL derivation can choose this host.
            origin(faro.removesuffix("/faro"), r"faro-api-[a-z0-9.-]+[.]grafana[.]net")
            get(
                CHECKS[2],
                faro + "/api/v1/app",
                "cloud",
                lambda value: isinstance(value, list),
                stack_id=remote["id"],
            )
        except Exception:  # noqa: BLE001 - keep metadata diagnostics private
            results[CHECKS[2]] = "FAIL"
    if remote is not None:
        get(
            CHECKS[3],
            stack + "/api/folders?limit=100",
            "stack",
            lambda value: isinstance(value, list),
        )
        get(
            CHECKS[4],
            stack + "/api/datasources",
            "stack",
            lambda value: isinstance(value, list),
        )
        get(
            CHECKS[5],
            stack + "/api/access-control/user/permissions",
            "query",
            lambda value: (
                isinstance(value, dict)
                and bool(value)
                and all(
                    isinstance(k, str) and isinstance(v, list) for k, v in value.items()
                )
            ),
        )
    if sm:
        get(
            CHECKS[6],
            sm + "/api/v1/probe/list",
            "sm",
            lambda value: isinstance(value, list),
        )
        get(
            CHECKS[7],
            sm + "/api/v1/check/list",
            "sm",
            lambda value: isinstance(value, list),
        )
    return results


def summary(results):
    lines = [
        "# Grafana read-only access check",
        "",
        "| Capability | Result |",
        "|---|---|",
    ]
    lines.extend(f"| {name} | {results[name]} |" for name in CHECKS)
    counts = {
        status: sum(value == status for value in results.values())
        for status in ("PASS", "PENDING", "FAIL")
    }
    lines += [
        "",
        " · ".join(f"{key}: {value}" for key, value in counts.items()),
        "",
        "Metadata-only evidence. No production alert/telemetry queries or mutations were performed. Write grants, per-signal isolation, credential least privilege, Free capacity and complete setup remain unverified. PENDING means missing credentials, missing Synthetic Monitoring backend binding, or a dependent check that could not run.",
    ]
    return "\n".join(lines) + "\n"


def main():
    try:
        if (
            os.environ.get("GITHUB_EVENT_NAME") != "workflow_dispatch"
            or os.environ.get("GITHUB_REF") != "refs/heads/main"
        ):
            raise ProvisionError("Trusted manual main execution required")
        results = check(
            os.environ.get("STACK_URL", ""),
            os.environ.get("STACK_REGION", ""),
            os.environ.get("SM_BACKEND_URL", ""),
            os.environ,
        )
        report = summary(results)
    except Exception:  # noqa: BLE001 - never expose input/credential/server content
        print("Grafana access check: FAIL (invalid request or internal failure)")
        return 1
    print(report)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        Path(os.environ["GITHUB_STEP_SUMMARY"]).write_text(report, encoding="utf-8")
    return int("FAIL" in results.values())


if __name__ == "__main__":
    raise SystemExit(main())
