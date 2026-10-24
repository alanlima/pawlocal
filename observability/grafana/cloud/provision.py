"""Provision only public Grafana folders/Faro applications; never AWS or credentials."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

ENVIRONMENTS = ("development", "production")
MARKER = "pawlocal-cloud-provisioner"
MAX_BODY = 2 * 1024 * 1024
SIGNAL_TYPES = {"metrics": "prometheus", "logs": "loki", "traces": "tempo"}


def datasource_selection(raw):
    """Parse public reviewed selectors, never a credential or datasource payload."""
    require(
        isinstance(raw, str) and len(raw.encode("utf-8")) <= 512,
        "Invalid datasource selector JSON",
    )

    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, "Duplicate datasource selector")
            result[key] = value
        return result

    try:
        result = json.loads(raw, object_pairs_hook=unique) if raw.strip() else {}
    except ValueError as error:
        raise ProvisionError("Invalid datasource selector JSON") from error
    require(
        isinstance(result, dict) and not set(result) - set(SIGNAL_TYPES),
        "Unknown datasource selector signal",
    )
    for uid in result.values():
        require(
            isinstance(uid, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,40}", uid),
            "Invalid datasource selector UID",
        )
    return result


class ProvisionError(Exception):
    pass


class TransportError(ProvisionError):
    """Safe protocol metadata; never include a response body or request credential."""

    def __init__(self, message, category, http_status=None):
        super().__init__(message)
        self.category = category
        self.http_status = http_status


def require(condition, message):
    if not condition:
        raise ProvisionError(message)


def exact_keys(value, keys, label):
    require(
        isinstance(value, dict) and set(value) == set(keys), f"Invalid {label} fields"
    )


def https_url(value, *, origin=False, grafana=False):
    require(
        isinstance(value, str) and not any(c.isspace() for c in value),
        "Invalid HTTPS URL",
    )
    parsed = urlsplit(value)
    require(
        parsed.scheme == "https"
        and parsed.hostname
        and not parsed.username
        and not parsed.password
        and not parsed.query
        and not parsed.fragment,
        "HTTPS URLs cannot contain credentials, query or fragment",
    )
    require(
        not origin or parsed.path in ("", "/"), "Expected an exact origin without path"
    )
    require(
        parsed.hostname != "localhost" and not parsed.hostname.endswith(".localhost"),
        "Hosted origin cannot use localhost",
    )
    require(
        "*" not in value and not parsed.hostname.endswith(".example"),
        "Wildcard/example origins are forbidden",
    )
    if grafana:
        require(
            parsed.hostname.endswith(".grafana.net"),
            "Expected an approved grafana.net host",
        )
    return value.rstrip("/")


def otlp_http_endpoint(value):
    """Cloud connections may return an origin or an already suffixed endpoint."""
    https_url(value, grafana=True)
    parsed = urlsplit(value)
    require(
        parsed.port is None
        and re.fullmatch(
            r"(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?[.])+grafana[.]net",
            parsed.hostname or "",
        )
        and parsed.path in ("", "/", "/otlp", "/otlp/"),
        "Expected a Grafana OTLP origin or exact /otlp endpoint",
    )
    return f"https://{parsed.hostname}/otlp"


def validate_manifest(document):
    allowed_keys = (
        ("version", "environments", "disclaimer")
        if "disclaimer" in document
        else ("version", "environments")
    )
    exact_keys(document, allowed_keys, "manifest")
    if "disclaimer" in document:
        require(
            type(document["disclaimer"]) is str
            and 0 < len(document["disclaimer"]) <= 2000,
            "disclaimer must be a string up to 2000 characters",
        )
    require(
        type(document["version"]) is int and document["version"] == 1,
        "Unsupported manifest version",
    )
    exact_keys(document["environments"], ENVIRONMENTS, "environments")
    for environment, spec in document["environments"].items():
        exact_keys(
            spec,
            ("enabled", "stack", "frontend_origin", "datasources", "approval"),
            environment,
        )
        require(type(spec["enabled"]) is bool, "enabled must be boolean")
        if not spec["enabled"]:
            require(
                all(
                    spec[key] is None
                    for key in ("stack", "frontend_origin", "datasources", "approval")
                ),
                "Disabled template must keep unconfigured bindings null",
            )
            continue
        stack = spec["stack"]
        exact_keys(
            stack,
            (
                "id",
                "slug",
                "url",
                "region",
                "faro_api_url",
                "otlp_endpoint",
                "otlp_instance_id",
            ),
            "stack",
        )
        require(type(stack["id"]) is int and stack["id"] > 0, "Invalid stack ID")
        require(
            isinstance(stack["slug"], str)
            and re.fullmatch(r"[a-z0-9][a-z0-9-]+", stack["slug"]),
            "Invalid stack slug",
        )
        https_url(stack["url"], origin=True, grafana=True)
        https_url(stack["faro_api_url"], grafana=True)
        require(
            urlsplit(stack["faro_api_url"]).path == "/faro",
            "Faro management endpoint must end in /faro",
        )
        https_url(stack["otlp_endpoint"], grafana=True)
        require(
            stack["otlp_instance_id"] == str(stack["id"]),
            "OTLP instance identity must match the actual stack ID",
        )
        require(
            isinstance(stack["region"], str)
            and re.fullmatch(r"[a-z0-9-]+", stack["region"]),
            "Invalid region",
        )
        https_url(spec["frontend_origin"], origin=True)
        exact_keys(spec["datasources"], ("metrics", "logs", "traces"), "datasources")
        for binding in spec["datasources"].values():
            exact_keys(binding, ("uid", "name"), "datasource binding")
            require(
                isinstance(binding["uid"], str)
                and re.fullmatch(r"[A-Za-z0-9_-]{1,40}", binding["uid"]),
                "Invalid datasource UID",
            )
            require(
                isinstance(binding["name"], str) and 0 < len(binding["name"]) < 200,
                "Invalid datasource name",
            )
        exact_keys(
            spec["approval"],
            (
                "reference",
                "residency",
                "free_plan_verified",
                "quota_review",
                "isolation_review",
            ),
            "approval",
        )
        for key in ("reference", "residency", "quota_review", "isolation_review"):
            require(
                isinstance(spec["approval"][key], str)
                and spec["approval"][key].strip(),
                f"Missing approval {key}",
            )
        require(
            spec["approval"]["free_plan_verified"] is True,
            "Actual Free-plan verification required",
        )
    configured = [spec for spec in document["environments"].values() if spec["enabled"]]
    require(
        len({spec["frontend_origin"].rstrip("/") for spec in configured})
        == len(configured),
        "Development and production require distinct exact frontend origins",
    )
    return document


def load_manifest(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, "Duplicate JSON key")
            result[key] = value
        return result

    try:
        return validate_manifest(
            json.loads(Path(path).read_text(encoding="utf-8"), object_pairs_hook=unique)
        )
    except (OSError, ValueError) as error:
        raise ProvisionError("Cannot load valid provisioning manifest") from error


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise TransportError(
            "API redirect rejected; verify endpoint before retry", "redirect"
        )


class Transport:
    def __init__(self):
        self.opener = build_opener(NoRedirect())

    def request(
        self,
        method,
        url,
        token,
        payload=None,
        stack_id=None,
        missing=False,
        extra_headers=None,
    ):
        # The only additional header currently needed is public Grafana policy
        # provenance. Never let an extra header override credential/scope headers.
        require(
            extra_headers is None or extra_headers == {"X-Disable-Provenance": "true"},
            "Unsupported per-request headers",
        )
        data = None if payload is None else json.dumps(payload).encode()
        authorization = token if stack_id is None else f"{stack_id}:{token}"
        headers = {
            "Authorization": f"Bearer {authorization}",
            "Content-Type": "application/json",
            "User-Agent": "pawlocal-grafana-provisioner/1",
        }
        if stack_id is not None:
            headers["X-Scope-OrgID"] = str(stack_id)
        headers.update(extra_headers or {})
        request = Request(url, data=data, headers=headers, method=method)
        try:
            with self.opener.open(request, timeout=30) as response:
                raw = response.read(MAX_BODY + 1)
                if len(raw) > MAX_BODY:
                    raise TransportError("API response too large", "response-too-large")
                return json.loads(raw) if raw else None
        except HTTPError as error:
            if error.code == 404 and missing:
                return None
            # Never print server response bodies which can echo credentials or data.
            raise TransportError(
                f"{method} API failed with HTTP {error.code}; inspect provider audit logs",
                "http-error",
                error.code,
            ) from None
        except (URLError, TimeoutError, OSError):
            raise TransportError(f"{method} API transport failure", "network") from None
        except ValueError:
            raise TransportError(f"{method} API JSON failure", "invalid-json") from None


class Provisioner:
    def __init__(self, transport, credentials):
        self.transport = transport
        self.credentials = credentials

    def call(self, method, url, credential, **kwargs):
        token = self.credentials.get(credential)
        if credential == "GRAFANA_FARO_ACCESS_POLICY_TOKEN" and not token:
            token = self.credentials.get("GRAFANA_CLOUD_ACCESS_POLICY_TOKEN")
        require(
            isinstance(token, str) and token.strip(),
            f"Missing operator credential {credential}",
        )
        return self.transport.request(method, url, token, **kwargs)

    def discover(self, stack_url, region, datasource_uids_json=""):
        selected = datasource_selection(datasource_uids_json)
        stack_url = https_url(stack_url, origin=True, grafana=True)
        host = urlsplit(stack_url).hostname
        require(host.count(".") == 2, "Expected a standard stack.grafana.net URL")
        slug = host.split(".")[0]
        remote = self.call(
            "GET",
            f"https://grafana.com/api/instances/{slug}",
            "GRAFANA_CLOUD_ACCESS_POLICY_TOKEN",
        )
        require(
            isinstance(remote, dict)
            and remote.get("slug") == slug
            and remote.get("url", "").rstrip("/") == stack_url,
            "Discovered stack identity/URL mismatch",
        )
        require(
            remote.get("regionSlug") == region,
            "Actual stack region differs from supplied region",
        )
        require(
            type(remote.get("id")) is int and remote["id"] > 0,
            "Invalid discovered stack ID",
        )
        connection = self.call(
            "GET",
            f"https://grafana.com/api/instances/{slug}/connections",
            "GRAFANA_CLOUD_ACCESS_POLICY_TOKEN",
        )
        require(isinstance(connection, dict), "Missing stack connection metadata")
        connection_endpoint = otlp_http_endpoint(connection.get("otlpHttpUrl"))
        sources = self.call(
            "GET", stack_url + "/api/datasources", "GRAFANA_SERVICE_ACCOUNT_TOKEN"
        )
        require(
            isinstance(sources, list)
            and len(sources) <= 100
            and all(isinstance(source, dict) for source in sources),
            "Invalid or oversized datasource discovery response",
        )
        bindings = {}
        public_candidates = {}
        unresolved = []
        for signal, kind in SIGNAL_TYPES.items():
            candidates = []
            for source in sources:
                if source.get("type") != kind:
                    continue
                uid, name = source.get("uid"), source.get("name")
                require(
                    isinstance(uid, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,40}", uid),
                    "Invalid discovered datasource UID",
                )
                require(
                    isinstance(name, str)
                    and 0 < len(name) < 200
                    and all(ord(char) >= 32 and ord(char) != 127 for char in name),
                    "Invalid discovered datasource name",
                )
                candidates.append({"uid": uid, "name": name, "type": kind})
            public_candidates[signal] = candidates
            if signal in selected:
                matches = [
                    source
                    for source in sources
                    if source.get("uid") == selected[signal]
                ]
                require(
                    len(matches) == 1 and matches[0].get("type") == kind,
                    "Selected datasource UID missing, duplicated or wrong type",
                )
                candidates = [
                    candidate
                    for candidate in candidates
                    if candidate["uid"] == selected[signal]
                ]
            if len(candidates) != 1:
                unresolved.append(signal)
                continue
            bindings[signal] = {key: candidates[0][key] for key in ("uid", "name")}
        faro_api = faro_management_url(region, remote.get("createdAt"))
        return {
            "status": "needs-selection-not-approved"
            if unresolved
            else "discovered-not-approved",
            "stack": {
                "id": remote["id"],
                "slug": slug,
                "url": stack_url,
                "region": region,
                "faro_api_url": faro_api,
                "otlp_endpoint": connection_endpoint,
                "otlp_instance_id": str(remote["id"]),
            },
            "datasources": bindings,
            "datasource_candidates": public_candidates,
            "unresolved_signals": unresolved,
            "pending": [
                "exact frontend origin from release evidence",
                "account Free/quota/residency and per-signal isolation review",
                "owner approval reference; reviewed enabled binding before mutation",
            ],
        }

    def reconcile(self, environment, spec, apply=False):
        if not spec["enabled"]:
            return {"environment": environment, "status": "disabled", "operations": []}
        stack = spec["stack"]
        # Read actual account metadata before permitting any mutation.
        remote = self.call(
            "GET",
            f"https://grafana.com/api/instances/{stack['id']}",
            "GRAFANA_CLOUD_ACCESS_POLICY_TOKEN",
        )
        require(
            isinstance(remote, dict)
            and remote.get("id") == stack["id"]
            and remote.get("slug") == stack["slug"],
            "Stack identity mismatch",
        )
        require(
            remote.get("url", "").rstrip("/") == stack["url"].rstrip("/")
            and remote.get("regionSlug") == stack["region"],
            "Stack URL/region differs from approved binding",
        )
        connection = self.call(
            "GET",
            f"https://grafana.com/api/instances/{stack['slug']}/connections",
            "GRAFANA_CLOUD_ACCESS_POLICY_TOKEN",
        )
        require(isinstance(connection, dict), "Missing stack connection metadata")
        connection_endpoint = otlp_http_endpoint(connection.get("otlpHttpUrl"))
        require(
            stack["otlp_endpoint"].rstrip("/") == connection_endpoint,
            "OTLP endpoint differs from actual stack connection metadata",
        )
        for signal, expected_type in (
            ("metrics", "prometheus"),
            ("logs", "loki"),
            ("traces", "tempo"),
        ):
            binding = spec["datasources"][signal]
            datasource = self.call(
                "GET",
                stack["url"].rstrip("/")
                + "/api/datasources/uid/"
                + quote(binding["uid"], safe=""),
                "GRAFANA_SERVICE_ACCOUNT_TOKEN",
            )
            require(
                isinstance(datasource, dict)
                and datasource.get("uid") == binding["uid"]
                and datasource.get("name") == binding["name"]
                and datasource.get("type") == expected_type,
                f"{signal} datasource identity/type mismatch",
            )
        folder_uid = f"pawlocal-{environment}"
        folder_title = f"PawLocal {environment}"
        folder_url = stack["url"].rstrip("/") + "/api/folders"
        folder = self.call(
            "GET",
            folder_url + "/" + folder_uid,
            "GRAFANA_SERVICE_ACCOUNT_TOKEN",
            missing=True,
        )
        require(
            folder is None
            or (
                folder.get("uid") == folder_uid and folder.get("title") == folder_title
            ),
            "Folder UID collision; no adoption/update allowed",
        )
        faro_url = stack["faro_api_url"].rstrip("/") + "/api/v1/app"
        apps = self.call(
            "GET", faro_url, "GRAFANA_FARO_ACCESS_POLICY_TOKEN", stack_id=stack["id"]
        )
        require(isinstance(apps, list), "Invalid Faro app list")
        name = f"pawlocal-{environment}"
        matches = [app for app in apps if app.get("name") == name]
        require(len(matches) <= 1, "Duplicate Faro names; reconcile ownership manually")
        app = matches[0] if matches else None
        labels = [
            {"label": "managed_by", "value": MARKER},
            {"label": "environment", "value": environment},
        ]
        desired = {
            "name": name,
            "corsOrigins": [{"url": spec["frontend_origin"].rstrip("/")}],
            "extraLogLabels": labels,
            "settings": {"geolocation.enabled": "0", "combineLabData": "0"},
        }
        if app:
            require(
                {"label": "managed_by", "value": MARKER}
                in [
                    {"label": item.get("label"), "value": item.get("value")}
                    for item in app.get("extraLogLabels", [])
                ],
                "Faro name collision; refusing adoption",
            )
            require(
                type(app.get("id")) is int and app["id"] > 0,
                "Invalid existing Faro app ID",
            )

        def canonical(value):
            return {
                "name": value.get("name"),
                "corsOrigins": sorted(
                    item.get("url") for item in value.get("corsOrigins", [])
                ),
                "extraLogLabels": sorted(
                    (item.get("label"), item.get("value"))
                    for item in value.get("extraLogLabels", [])
                ),
                "settings": value.get("settings"),
            }

        changed = app is None or canonical(app) != canonical(desired)
        operations = ([] if folder else ["create-folder"]) + (
            [] if not changed else ["create-faro" if app is None else "update-faro"]
        )
        # All preflight/collision checks above finish before any write.
        if apply:
            if folder is None:
                created = self.call(
                    "POST",
                    folder_url,
                    "GRAFANA_SERVICE_ACCOUNT_TOKEN",
                    payload={"uid": folder_uid, "title": folder_title},
                )
                require(
                    created and created.get("uid") == folder_uid,
                    "Created folder identity mismatch",
                )
            if changed:
                app = self.call(
                    "POST" if app is None else "PUT",
                    faro_url if app is None else faro_url + "/" + str(app["id"]),
                    "GRAFANA_FARO_ACCESS_POLICY_TOKEN",
                    payload=desired,
                    stack_id=stack["id"],
                )
            # Read back every owned public object after mutation; no deletion/recreation.
            verified_folder = self.call(
                "GET", folder_url + "/" + folder_uid, "GRAFANA_SERVICE_ACCOUNT_TOKEN"
            )
            require(
                verified_folder and verified_folder.get("title") == folder_title,
                "Folder verification failed",
            )
            require(app and type(app.get("id")) is int, "Missing Faro app after apply")
            expected_app_id = app["id"]
            app = self.call(
                "GET",
                faro_url + "/" + str(expected_app_id),
                "GRAFANA_FARO_ACCESS_POLICY_TOKEN",
                stack_id=stack["id"],
            )
            require(
                app.get("id") == expected_app_id, "Faro read-back app identity mismatch"
            )
            require(
                canonical(app) == canonical(desired),
                "Faro read-back differs from desired configuration",
            )
        result = {
            "environment": environment,
            "status": "applied" if apply else "plan",
            "operations": operations,
            "stack_id": stack["id"],
            "region": stack["region"],
            "folder_uid": folder_uid,
            "datasources": spec["datasources"],
        }
        if app:
            endpoint = https_url(app.get("collectEndpointURL"), grafana=True)
            key = app.get("appKey")
            require(
                isinstance(key, str) and re.fullmatch(r"[A-Za-z0-9_-]+", key),
                "Missing/invalid public Faro application key",
            )
            result["public_handoff"] = {
                f"/pawlocal/{environment}/config/grafana/stack-url": stack["url"],
                f"/pawlocal/{environment}/config/grafana/otlp-endpoint": stack[
                    "otlp_endpoint"
                ],
                f"/pawlocal/{environment}/config/grafana/otlp-instance-id": stack[
                    "otlp_instance_id"
                ],
                f"/pawlocal/{environment}/config/grafana/faro-collector-url": endpoint
                + "/"
                + key,
            }
        return result


def faro_management_url(region, created_at):
    # Exact region exceptions from the pinned official v4.50.0 client, not caller-selected hosts.
    exceptions = {
        "au": "prod-au-southeast-0",
        "eu": "prod-eu-west-0",
        "us": "prod-us-central-0",
        "azure-uaenorth-0": "prod-me-central-2.azure-uaenorth-0",
        "us-azure": "prod-us-central-7",
    }
    if region == "prod-us-east-0":
        require(
            isinstance(created_at, str),
            "Stack creation timestamp needed for US East Faro endpoint",
        )
        try:
            created = datetime.fromisoformat(created_at)
            require(
                created.tzinfo is not None, "Stack creation timestamp needs timezone"
            )
        except ValueError as error:
            raise ProvisionError("Invalid stack creation timestamp") from error
        if created > datetime(2024, 12, 18, tzinfo=UTC):
            return "https://faro-api-prod-us-east-2.grafana.net/faro"
    require(
        isinstance(region, str) and re.fullmatch(r"[a-z0-9-]+", region),
        "Invalid stack region",
    )
    prefix = exceptions.get(region, region)
    return f"https://faro-api-{prefix}.grafana.net/faro"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest", type=Path, default=Path(__file__).with_name("bindings.json")
    )
    parser.add_argument("--environment", choices=ENVIRONMENTS, required=True)
    parser.add_argument(
        "--mode", choices=("check", "discover", "plan", "apply"), default="check"
    )
    parser.add_argument(
        "--stack-url", help="Existing Grafana stack URL for read-only discovery"
    )
    parser.add_argument("--region", help="Approved expected region slug for discovery")
    parser.add_argument(
        "--datasource-uids-json",
        default="",
        help="Discovery-only reviewed signal-to-UID JSON selectors",
    )
    args = parser.parse_args()
    if args.mode == "discover":
        require(
            args.stack_url and args.region,
            "Discovery requires --stack-url and --region",
        )
        result = Provisioner(Transport(), os.environ).discover(
            args.stack_url, args.region, args.datasource_uids_json
        )
        result["environment"] = args.environment
        print(json.dumps(result, indent=2))
        return
    require(
        not args.stack_url and not args.region and not args.datasource_uids_json,
        "--stack-url/--region/--datasource-uids-json are discovery-only",
    )
    document = load_manifest(args.manifest)
    if args.mode == "check":
        print(
            json.dumps(
                {
                    "environment": args.environment,
                    "status": "validated",
                    "enabled": document["environments"][args.environment]["enabled"],
                }
            )
        )
        return
    result = Provisioner(Transport(), os.environ).reconcile(
        args.environment,
        document["environments"][args.environment],
        apply=args.mode == "apply",
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    try:
        main()
    except ProvisionError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1)
