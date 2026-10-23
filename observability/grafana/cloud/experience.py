"""Own #226 dashboards, a native synthetic journey and its narrowly scoped alert route."""

import argparse
import base64
import copy
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

from build_dashboards import OWNER, build
from provision import (
    Provisioner,
    ProvisionError,
    Transport,
    exact_keys,
    https_url,
    load_manifest,
    require,
)

ROOT = Path(__file__).resolve().parent
JOB = "pawlocal-development-search-detail"
ALERT = "pawlocal-development-search-detail-failure"
RULE_UID = "pawlocal-development-search-detail"
FOLDER = "pawlocal-development"
GROUP = "pawlocal-development-journey"
CONTACT = "pawlocal-development-oncall"
MATCHERS = [
    ["alertname", "=", ALERT],
    ["environment", "=", "development"],
    ["service", "=", "pawlocal-api"],
    ["pawlocal_owner", "=", "monitoring-226"],
]


def configuration(path):
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    exact_keys(
        value,
        (
            "version",
            "enabled",
            "active",
            "usage_datasource_uid",
            "synthetic_api_url",
            "probe_id",
            "api_base_url",
            "webhook_url",
            "operator_receiver",
            "approval",
            "responder_routing",
            "responder_approval",
        ),
        "experience",
    )
    require(
        type(value["version"]) is int and value["version"] == 1,
        "Unsupported experience version",
    )
    require(
        type(value["enabled"]) is bool and type(value["active"]) is bool,
        "enabled/active must be boolean",
    )
    if not value["enabled"]:
        require(
            not value["active"], "Disabled configuration cannot activate monitoring"
        )
        return value
    require(
        type(value["responder_routing"]) is bool, "responder_routing must be boolean"
    )
    https_url(value["synthetic_api_url"], origin=True, grafana=True)
    https_url(value["api_base_url"])
    require(
        value["api_base_url"].endswith("/api/v1"), "Use the approved /api/v1 base URL"
    )
    if value["responder_routing"]:
        url = urlsplit(https_url(value["webhook_url"], origin=True))
        require(
            re.fullmatch(
                r"[a-z0-9]+[.]lambda-url[.][a-z0-9-]+[.]on[.]aws", url.hostname
            ),
            "Expected matching approved Lambda Function URL",
        )
        require(
            isinstance(value["responder_approval"], str)
            and value["responder_approval"].strip(),
            "Record G1/receiver approval before routing alerts to the responder",
        )
    require(
        type(value["probe_id"]) is int and value["probe_id"] > 0,
        "Select exactly one actual public probe ID",
    )
    for field in ("usage_datasource_uid", "operator_receiver", "approval"):
        require(
            isinstance(value[field], str) and value[field].strip(),
            f"Missing reviewed {field}",
        )
    return value


def dashboards(bindings, usage_uid):
    replacements = {
        f"__{kind.upper()}_UID__": binding["uid"]
        for kind, binding in bindings["datasources"].items()
    }
    replacements["__USAGE_UID__"] = usage_uid
    results = []
    for dashboard in build().values():
        serialized = json.dumps(dashboard)
        for marker, uid in replacements.items():
            serialized = serialized.replace(marker, uid)
        results.append(json.loads(serialized))
    return results


def synthetic(config):
    script = (
        (ROOT / "search-detail.js")
        .read_text(encoding="utf-8")
        .replace("__API_BASE_JSON__", json.dumps(config["api_base_url"]))
    )
    return {
        "job": JOB,
        "target": config["api_base_url"],
        "frequency": 300000,
        "timeout": 10000,
        "enabled": config["active"],
        "alertSensitivity": "none",
        "basicMetricsOnly": True,
        "probes": [config["probe_id"]],
        "folderUid": FOLDER,
        "labels": [
            {"name": "environment", "value": "development"},
            {"name": "service", "value": "pawlocal-api"},
            {"name": "pawlocal_owner", "value": "monitoring-226"},
        ],
        "settings": {
            "scripted": {"script": base64.b64encode(script.encode()).decode()}
        },
    }


def alert_rule(metrics_uid, active=False):
    expr = f'avg_over_time(probe_success{{job="{JOB}"}}[10m])'
    return {
        "uid": RULE_UID,
        "title": ALERT,
        "folderUID": FOLDER,
        "ruleGroup": GROUP,
        "condition": "C",
        "for": "5m",
        "keep_firing_for": "2m",
        "isPaused": not active,
        "noDataState": "NoData",
        "execErrState": "Error",
        "labels": {
            "environment": "development",
            "service": "pawlocal-api",
            "route": "/api/v1/places",
            "severity": "warning",
            "pawlocal_owner": "monitoring-226",
        },
        "annotations": {
            "summary": "Public search to details journey failed",
            "__dashboardUid__": "pawlocal-journey",
            "__panelId__": "3",
            "runbook_url": "https://github.com/alanlima/pawlocal/blob/main/observability/grafana/cloud/ACCEPTANCE.md",
        },
        "data": [
            {
                "refId": "A",
                "datasourceUid": metrics_uid,
                "relativeTimeRange": {"from": 900, "to": 0},
                "model": {
                    "refId": "A",
                    "expr": expr,
                    "instant": True,
                    "range": False,
                    "intervalMs": 1000,
                    "maxDataPoints": 43200,
                },
            },
            {
                "refId": "B",
                "datasourceUid": "__expr__",
                "relativeTimeRange": {"from": 0, "to": 0},
                "model": {
                    "refId": "B",
                    "type": "reduce",
                    "expression": "A",
                    "reducer": "last",
                    "conditions": [
                        {
                            "type": "query",
                            "query": {"params": ["B"]},
                            "reducer": {"type": "last", "params": []},
                            "evaluator": {"type": "gt", "params": []},
                            "operator": {"type": "and"},
                        }
                    ],
                },
            },
            {
                "refId": "C",
                "datasourceUid": "__expr__",
                "relativeTimeRange": {"from": 0, "to": 0},
                "model": {
                    "refId": "C",
                    "type": "threshold",
                    "expression": "B",
                    "conditions": [
                        {
                            "type": "query",
                            "query": {"params": ["C"]},
                            "reducer": {"type": "last", "params": []},
                            "evaluator": {"type": "lt", "params": [1]},
                            "operator": {"type": "and"},
                        }
                    ],
                },
            },
        ],
    }


def contact_point(webhook_url, secret):
    return {
        "uid": CONTACT,
        "name": CONTACT,
        "type": "webhook",
        "disableResolveMessage": False,
        "settings": {
            "url": webhook_url,
            "httpMethod": "POST",
            "maxAlerts": 20,
            "hmacConfig": {
                "secret": secret,
                "header": "X-Grafana-Alerting-Signature",
                "timestampHeader": "X-Grafana-Alerting-Timestamp",
            },
        },
    }


def merge_policy(existing, operator_receiver, enable=True):
    require(
        isinstance(existing, dict) and existing.get("receiver") == operator_receiver,
        "Existing root must retain reviewed operator receiver",
    )
    result = copy.deepcopy(existing)
    route = {
        "receiver": CONTACT,
        "object_matchers": MATCHERS,
        "continue": False,
        "group_by": ["alertname", "grafana_folder", "environment"],
        "group_wait": "30s",
        "group_interval": "5m",
        "repeat_interval": "4h",
    }
    routes = result.setdefault("routes", [])
    # Append only after rejecting any conflicting ownership predicate.
    owned = [
        item
        for item in routes
        if any(
            matcher[:2] == ["pawlocal_owner", "="] and matcher[2] == "monitoring-226"
            for matcher in item.get("object_matchers", [])
        )
    ]
    require(
        len(owned) <= 1 and (not owned or owned[0] == route),
        "Notification route collision; no wholesale policy overwrite permitted",
    )
    if enable and not owned:
        routes.insert(0, route)
    elif not enable and owned:
        routes.remove(owned[0])
    return result


def subset_equal(remote, desired):
    if isinstance(desired, dict):
        return isinstance(remote, dict) and all(
            key in remote and subset_equal(remote[key], value)
            for key, value in desired.items()
        )
    if isinstance(desired, list):
        return (
            isinstance(remote, list)
            and len(remote) == len(desired)
            and all(subset_equal(a, b) for a, b in zip(remote, desired))
        )
    return remote == desired


class Experience(Provisioner):
    def reconcile_experience(self, config, binding, apply=False):
        if not config["enabled"]:
            return {"status": "disabled", "operations": []}
        require(binding["enabled"], "Grafana binding must be configured first")
        # Bind this development-only probe to the existing hosted domain contract,
        # derived from the reviewed Faro frontend origin rather than another URL.
        frontend = urlsplit(https_url(binding["frontend_origin"], origin=True))
        require(
            frontend.hostname.startswith("pawlocal-dev.") and frontend.port is None,
            "Expected the reviewed development Faro frontend origin",
        )
        expected_api = (
            "https://api-dev."
            + frontend.hostname.removeprefix("pawlocal-dev.")
            + "/api/v1"
        )
        require(
            config["api_base_url"] == expected_api,
            "Development check API must match the approved development frontend domain",
        )
        # Existing #224 preflight validates real stack/region/endpoints/datasources, read-only.
        super().reconcile("development", binding, apply=False)
        base = binding["stack"]["url"].rstrip("/")

        def grafana(method, path, **kwargs):
            return self.call(
                method, base + path, "GRAFANA_SERVICE_ACCOUNT_TOKEN", **kwargs
            )

        sm_base = config["synthetic_api_url"].rstrip("/") + "/api/v1"

        def sm(method, path, **kwargs):
            return self.call(
                method, sm_base + path, "GRAFANA_SYNTHETIC_MONITORING_TOKEN", **kwargs
            )

        tenant = sm("GET", "/tenant")
        require(
            type(tenant.get("id")) is int
            and tenant["id"] > 0
            and tenant.get("stackId") == binding["stack"]["id"],
            "Synthetic token belongs to a different stack",
        )
        require(
            tenant.get("status", 0) in (0, "ACTIVE"), "Synthetic tenant is not active"
        )
        usage = grafana("GET", "/api/datasources/uid/" + config["usage_datasource_uid"])
        require(
            usage.get("uid") == config["usage_datasource_uid"]
            and usage.get("type") == "prometheus"
            and usage.get("name") == "grafanacloud-usage",
            "Verify the actual account usage datasource binding",
        )
        folder = grafana("GET", "/api/folders/" + FOLDER)
        require(
            folder and folder.get("uid") == FOLDER,
            "Create/verify the #224 folder first",
        )
        desired_dashboards = dashboards(binding, config["usage_datasource_uid"])
        dashboard_ops = []
        for desired in desired_dashboards:
            old = grafana("GET", "/api/dashboards/uid/" + desired["uid"], missing=True)
            if old:
                require(
                    OWNER in old["dashboard"].get("tags", [])
                    and old.get("meta", {}).get("folderUid") == FOLDER,
                    "Foreign dashboard UID collision",
                )
            comparison = {
                key: value
                for key, value in desired.items()
                if key not in ("id", "version")
            }
            if not old or not subset_equal(old["dashboard"], comparison):
                payload = copy.deepcopy(desired)
                if old:
                    payload["id"] = old["dashboard"]["id"]
                    payload["version"] = old["dashboard"]["version"]
                dashboard_ops.append(payload)
        probes = sm("GET", "/probe/list")
        selected = [probe for probe in probes if probe.get("id") == config["probe_id"]]
        require(
            len(selected) == 1
            and selected[0].get("public") is True
            and selected[0].get("online") is True,
            "Select one online public probe",
        )
        check = synthetic(config)
        existing_checks = sm("GET", "/check/list")
        owned_checks = [
            item
            for item in existing_checks
            if item.get("job") == JOB
            or item.get("target") == check["target"]
            and any(
                label.get("name") == "pawlocal_owner"
                and label.get("value") == "monitoring-226"
                for label in item.get("labels", [])
            )
        ]
        require(len(owned_checks) <= 1, "Ambiguous synthetic check ownership")
        old_check = owned_checks[0] if owned_checks else None
        if old_check:
            require(
                any(
                    label.get("name") == "pawlocal_owner"
                    and label.get("value") == "monitoring-226"
                    for label in old_check.get("labels", [])
                ),
                "Foreign synthetic job collision",
            )
            require(
                old_check.get("tenantId") == tenant["id"],
                "Synthetic check tenant identity mismatch",
            )
            check.update({"id": old_check["id"], "tenantId": old_check["tenantId"]})
        check_changed = not old_check or not subset_equal(old_check, check)
        group_path = f"/api/v1/provisioning/folder/{FOLDER}/rule-groups/{GROUP}"
        old_group = grafana("GET", group_path, missing=True)
        organization = grafana("GET", "/api/org")
        require(
            type(organization.get("id")) is int and organization["id"] > 0,
            "Missing actual Grafana organization ID",
        )
        rule = alert_rule(binding["datasources"]["metrics"]["uid"], config["active"])
        rule["orgID"] = organization["id"]
        if old_group:
            require(
                all(
                    item.get("uid") == RULE_UID
                    and item.get("labels", {}).get("pawlocal_owner") == "monitoring-226"
                    for item in old_group.get("rules", [])
                ),
                "Foreign rules in owned rule group",
            )
        group = {"title": GROUP, "folderUid": FOLDER, "interval": 60, "rules": [rule]}
        group_changed = not old_group or not subset_equal(old_group, group)
        contacts = (
            grafana("GET", "/api/v1/provisioning/contact-points")
            if config["responder_routing"]
            else []
        )
        matching = [
            item
            for item in contacts
            if item.get("uid") == CONTACT or item.get("name") == CONTACT
        ]
        require(
            len(matching) <= 1
            and (
                not matching
                or matching[0].get("uid") == CONTACT
                and matching[0].get("type") == "webhook"
                and matching[0].get("settings", {}).get("url") == config["webhook_url"]
            ),
            "Contact-point identity/URL collision",
        )
        policy = grafana("GET", "/api/v1/provisioning/policies")
        updated_policy = merge_policy(
            policy, config["operator_receiver"], config["responder_routing"]
        )
        operations = ["dashboard:" + item["uid"] for item in dashboard_ops]
        operations += (
            ["synthetic:update" if old_check else "synthetic:create"]
            if check_changed
            else []
        )
        operations += (
            ["contact-point:runtime-secret-write"]
            if config["responder_routing"]
            else []
        )
        operations += ["rule-group:update"] if group_changed else []
        operations += (
            [
                "notification-route:add"
                if config["responder_routing"]
                else "notification-route:remove-owned"
            ]
            if policy != updated_policy
            else []
        )
        if apply:
            # No writes before complete resource preflight and presence of runtime-only HMAC.
            secret = self.credentials.get("PAWLOCAL_GRAFANA_WEBHOOK_HMAC")
            if config["responder_routing"]:
                require(
                    isinstance(secret, str) and len(secret) >= 32,
                    "Provide approved runtime-only HMAC through the trusted setup process",
                )
            for payload in dashboard_ops:
                grafana(
                    "POST",
                    "/api/dashboards/db",
                    payload={
                        "dashboard": payload,
                        "folderUid": FOLDER,
                        "overwrite": False,
                    },
                )
                current = grafana("GET", "/api/dashboards/uid/" + payload["uid"])
                require(
                    subset_equal(
                        current["dashboard"],
                        {
                            key: value
                            for key, value in payload.items()
                            if key not in ("id", "version")
                        },
                    ),
                    "Dashboard read-back mismatch",
                )
            if check_changed:
                result = sm(
                    "POST",
                    "/check/update" if old_check else "/check/add",
                    payload=check,
                )
                require(
                    result and type(result.get("id")) is int,
                    "Missing synthetic check identity",
                )
                readback = sm("GET", "/check/" + str(result["id"]))
                require(subset_equal(readback, check), "Synthetic read-back mismatch")
            if config["responder_routing"]:
                grafana(
                    "PUT" if matching else "POST",
                    "/api/v1/provisioning/contact-points"
                    + ("/" + CONTACT if matching else ""),
                    payload=contact_point(config["webhook_url"], secret),
                )
                public_contact = contact_point(config["webhook_url"], secret)
                del public_contact["settings"]["hmacConfig"]["secret"]
                verified_contacts = grafana(
                    "GET", "/api/v1/provisioning/contact-points"
                )
                require(
                    any(
                        subset_equal(item, public_contact) for item in verified_contacts
                    ),
                    "Contact-point public read-back mismatch; private write acceptance is not plaintext verification",
                )
            # The root policy is shared: re-read before the reviewed narrow insertion; never replace concurrent changes.
            if policy != updated_policy:
                require(
                    grafana("GET", "/api/v1/provisioning/policies") == policy,
                    "Notification policy changed during preflight; rerun plan",
                )
                grafana(
                    "PUT",
                    "/api/v1/provisioning/policies",
                    payload=updated_policy,
                    # This API writes the entire shared tree. Preserve operator UI
                    # editing instead of marking unrelated routes API-provisioned.
                    extra_headers={"X-Disable-Provenance": "true"},
                )
                require(
                    subset_equal(
                        grafana("GET", "/api/v1/provisioning/policies"), updated_policy
                    ),
                    "Notification route read-back mismatch",
                )
            if group_changed:
                grafana("PUT", group_path, payload=group)
                require(
                    subset_equal(grafana("GET", group_path), group),
                    "Rule-group read-back mismatch",
                )
        return {
            "status": "applied" if apply else "plan",
            "operations": operations,
            "active": config["active"],
            "raw_executions_per_30_days": 8640,
            "maximum_billing_units_at_10_second_timeout": 8640,
            "g1": "pending live journey/privacy/quota/firing/recovery evidence and owner review",
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / "experience.json")
    parser.add_argument("--bindings", type=Path, default=ROOT / "bindings.json")
    parser.add_argument("--mode", choices=("check", "plan", "apply"), default="check")
    args = parser.parse_args()
    config = configuration(args.config)
    # Regeneration is a developer command, not a live provisioning side effect.
    for name, desired in build().items():
        require(
            json.loads(
                (ROOT / "dashboards" / f"{name}.json").read_text(encoding="utf-8")
            )
            == desired,
            "Dashboard JSON drift: regenerate build_dashboards.py",
        )
    if args.mode == "check":
        print(
            json.dumps(
                {"status": "validated", "enabled": config["enabled"], "dashboards": 6}
            )
        )
        return
    binding = load_manifest(args.bindings)["environments"]["development"]
    print(
        json.dumps(
            Experience(Transport(), os.environ).reconcile_experience(
                config, binding, apply=args.mode == "apply"
            ),
            indent=2,
        )
    )


if __name__ == "__main__":
    try:
        main()
    except (ProvisionError, OSError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1)
