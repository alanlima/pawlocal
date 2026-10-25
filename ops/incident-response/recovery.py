"""Trusted bounded recovery observer; no model input, writes or customer output.

Known post-deploy firing/pending/no-data and metric warmup may settle only
inside the caller's unchanged absolute deadline. The full approved stable
window starts at the first healthy sample; later regression escalates rather
than resetting the window. Public release identity and journey must stay valid
during settling. Schema, permission and network uncertainty fail immediately.
The optional trusted live-control callback runs before every HTTP request and
before a receipt; process environment flags are only a job snapshot.

Runtime rules schema: Grafana ngalert api/tooling/api.json AlertingRule.
Prometheus datasource proxy uses the standard instant-query vector response.
These offline contracts still require live stack permission/shape acceptance.
"""

import datetime as dt
import math
import os
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

from quota import Denied, strict_json
from enforcement import enabled, skipped, evidence
from quota_gateway import NoRedirect

MAX_BODY = 2 * 1024 * 1024
INTERVAL = 30
FRESH_SECONDS = 120


def _require(condition, reason):
    if not condition:
        raise Denied(reason)


class _Settling(Denied):
    """Known post-deploy signal warmup, never an authorization/schema error."""


def _ready(condition, reason):
    if not condition:
        raise _Settling(reason)


def _origin(value):
    _require(isinstance(value, str), "recovery origin unavailable")
    url = urllib.parse.urlsplit(value)
    _require(
        url.scheme == "https"
        and re.fullmatch(r"[a-z0-9][a-z0-9.-]{1,250}", url.netloc or "")
        and url.path in {"", "/"}
        and not url.query
        and not url.fragment,
        "recovery origin invalid",
    )
    return value.rstrip("/")


def _timestamp(value):
    try:
        result = dt.datetime.fromisoformat(value)
        _require(result.tzinfo is not None, "recovery timestamp invalid")
        return result.timestamp()
    except (ValueError, TypeError, AttributeError, OverflowError) as error:
        raise Denied("recovery timestamp invalid") from error


def _enabled(environment, profile, now, deadline):
    _require(now < deadline, "recovery deadline exhausted")
    _require(os.environ.get("PAWLOCAL_ONCALL_ENABLED") == "true", "recovery disabled")
    _require(
        environment != "production"
        or os.environ.get("PAWLOCAL_PRODUCTION_TELEMETRY_READ_APPROVED") == "true",
        "production recovery read revoked",
    )
    profile.valid_at(now)


def _binding(trusted, environment, frontend, stack):
    binding_path = Path(trusted) / "observability/grafana/cloud/bindings.json"
    try:
        raw = binding_path.read_bytes()
        _require(len(raw) <= MAX_BODY, "recovery binding bound")
        value = strict_json(raw)
        selected = value.get("environments", {}).get(environment, {})
        _require(
            value.get("version") == 1
            and selected.get("enabled") is True
            and selected.get("approval")
            and selected.get("frontend_origin", "").rstrip("/") == frontend
            and (selected.get("stack") or {}).get("url", "").rstrip("/") == stack,
            "recovery approved binding unavailable",
        )
        source = (selected.get("datasources") or {}).get("metrics") or {}
        _require(
            re.fullmatch(r"[A-Za-z0-9_-]{1,40}", str(source.get("uid", ""))),
            "recovery metrics binding invalid",
        )
        return source["uid"]
    except (OSError, AttributeError, TypeError) as error:
        raise Denied("recovery binding unavailable") from error


def _scope(
    environment, profile, service, api_base_url, frontend_origin, stack_url, query_token
):
    _require(
        environment in {"development", "production"}, "recovery environment invalid"
    )
    _require(
        isinstance(service, str) and re.fullmatch(r"[a-z][a-z0-9-]{0,99}", service),
        "recovery service invalid",
    )
    rule_uid = (
        profile.rule_uids.get(environment, "")
        if hasattr(profile, "rule_uids") and isinstance(profile.rule_uids, dict)
        else ""
    )
    if rule_uid:
        _require(
            re.fullmatch(r"[A-Za-z0-9_-]{1,40}", rule_uid),
            "recovery rule unavailable",
        )
    stack = _origin(stack_url)
    _require(
        re.fullmatch(r"https://[a-z0-9-]+\.grafana\.net", stack) and query_token,
        "recovery stack credential unavailable",
    )
    frontend = _origin(frontend_origin)
    host = urllib.parse.urlsplit(frontend).hostname
    prefix = "pawlocal-dev." if environment == "development" else "pawlocal."
    _require(host.startswith(prefix), "recovery frontend environment mismatch")
    domain = host[len(prefix) :]
    api_origin = (
        "https://" + ("api-dev." if environment == "development" else "api.") + domain
    )
    _require(api_base_url == api_origin + "/api/v1", "recovery API binding mismatch")
    return rule_uid, stack, frontend, api_origin


def _rule(rules, environment, service, rule_uid, metrics_uid, alert_name=None):
    _require(
        isinstance(rules, dict) and isinstance(rules.get("data"), dict),
        "recovery rule schema invalid",
    )
    _require(rules.get("status") == "success", "recovery rule response invalid")
    groups = rules.get("data", {}).get("groups")
    _require(
        isinstance(groups, list) and len(groups) <= 200,
        "recovery rule groups invalid",
    )
    _require(
        all(
            isinstance(group, dict)
            and isinstance(group.get("rules"), list)
            and len(group["rules"]) <= 500
            and all(isinstance(rule, dict) for rule in group["rules"])
            for group in groups
        ),
        "recovery rule group schema invalid",
    )
    if rule_uid:
        matches = [
            rule
            for group in groups
            for rule in group.get("rules", [])
            if rule.get("uid") == rule_uid
        ]
    elif alert_name:
        matches = [
            rule
            for group in groups
            for rule in group.get("rules", [])
            if rule.get("name") == alert_name
            or (rule.get("labels") or {}).get("alertname") == alert_name
        ]
    else:
        matches = [
            rule
            for group in groups
            for rule in group.get("rules", [])
            if (rule.get("labels") or {}).get("environment") == environment
            and (rule.get("labels") or {}).get("service") == service
        ]
    _require(len(matches) >= 1, "recovery exact rule unavailable")
    rule = matches[0]
    sources = rule.get("queriedDatasourceUIDs")
    _require(
        isinstance(sources, list)
        and len(sources) == 1
        and isinstance(sources[0], str)
        and sources[0] == metrics_uid,
        "recovery rule datasource differs from approved binding",
    )
    labels = rule.get("labels", {})
    _require(isinstance(labels, dict), "recovery rule labels invalid")
    _require(
        rule.get("type") == "alerting"
        and rule.get("isPaused") is False
        and rule.get("health") in {"ok", "nodata"}
        and rule.get("state") in {"inactive", "pending", "firing"}
        and not rule.get("lastError")
        and isinstance(rule.get("alerts"), list)
        and labels.get("environment") == environment
        and labels.get("service") == service,
        "recovery rule unhealthy",
    )
    instances = rule["alerts"]
    allowed_instance_states = {"Normal", "Pending", "Alerting", "Recovering"}
    if environment == "development":
        allowed_instance_states.add("NoData")
    _require(
        len(instances) <= 1000
        and all(
            isinstance(instance, dict)
            and instance.get("state") in allowed_instance_states
            for instance in instances
        ),
        "recovery rule instance health unknown",
    )
    return rule


def observe(
    trusted,
    environment,
    release,
    profile,
    *,
    service,
    alert_name=None,
    api_base_url,
    frontend_origin,
    stack_url,
    query_token,
    deadline,
    opener=None,
    clock=time.time,
    sleep=time.sleep,
    control=None,
):
    """Raise a fixed redacted Denied on any uncertainty; never reset the window."""
    _require(
        environment in {"development", "production"}, "recovery environment invalid"
    )
    if not enabled():
        skipped("recovery")
        return {
            "schema": 1,
            "environment": environment,
            "recovery_verified": False,
            "enforcement": evidence(),
            "observations": [],
            "window_seconds": 0,
            "started_at": clock(),
            "completed_at": clock(),
            "profile_sha256": profile.digest,
        }
    _enabled(environment, profile, clock(), deadline)
    _require(
        isinstance(service, str) and re.fullmatch(r"[a-z][a-z0-9-]{0,99}", service),
        "recovery service invalid",
    )
    _require(
        isinstance(release, dict)
        and re.fullmatch(r"sha256:[0-9a-f]{64}", str(release.get("image_digest", "")))
        and re.fullmatch(r"[0-9a-f]{40}", str(release.get("affected_sha", ""))),
        "recovery release invalid",
    )
    _require(
        all(
            type(release.get(key)) is int and release[key] > 0
            for key in ("deployment_id", "deployment_run")
        ),
        "recovery deployment invalid",
    )
    _require(
        type(profile.recovery_seconds) is int
        and 600 <= profile.recovery_seconds <= 900,
        "recovery window invalid",
    )
    rule_uid, stack, frontend, api_origin = _scope(
        environment,
        profile,
        service,
        api_base_url,
        frontend_origin,
        stack_url,
        query_token,
    )

    def binding():
        return _binding(trusted, environment, frontend, stack)

    uid = binding()
    client = opener or urllib.request.build_opener(NoRedirect)

    def request(url, *, secret=False, json_body=True):
        _enabled(environment, profile, clock(), deadline)
        if control is not None:
            control()
        _require(
            not secret or url.startswith(stack + "/api/"),
            "recovery credential destination invalid",
        )
        headers = {"Accept": "application/json" if json_body else "text/html"}
        if secret:
            headers["Authorization"] = "Bearer " + query_token
        try:
            with client.open(
                urllib.request.Request(url, headers=headers),
                timeout=min(10, deadline - clock()),
            ) as response:
                _require(
                    response.status == 200 and response.geturl() == url,
                    "recovery HTTP response invalid",
                )
                raw = response.read(MAX_BODY + 1)
                _require(len(raw) <= MAX_BODY, "recovery response bound")
            _enabled(environment, profile, clock(), deadline)
            return strict_json(raw) if json_body else raw
        except Denied:
            raise
        except Exception as error:
            raise Denied("recovery network unavailable") from error

    entered = clock()
    _require(
        entered + profile.recovery_seconds < deadline,
        "recovery window exceeds deadline",
    )
    started = None
    samples = 0
    settling_samples = 0
    previous_evaluation = None

    def sample():
        nonlocal previous_evaluation
        now = clock()
        _enabled(environment, profile, now, deadline)
        if control is not None:
            control()
        _require(binding() == uid, "recovery binding changed")
        _require(request(frontend + "/", json_body=False), "recovery frontend empty")
        health = request(api_origin + "/health")
        _require(isinstance(health, dict), "recovery health schema invalid")
        _require(
            health.get("status") == "ok"
            and health.get("environment") == environment
            and health.get("image_digest") == release["image_digest"],
            "recovery runtime identity mismatch",
        )
        page = request(api_base_url + "/places?page=1&page_size=1")
        _require(isinstance(page, dict), "recovery search schema invalid")
        items = page.get("items")
        _require(
            isinstance(items, list) and len(items) == 1 and isinstance(items[0], dict),
            "recovery search unavailable",
        )
        place_id = items[0].get("id")
        _require(
            isinstance(place_id, str)
            and re.fullmatch(
                r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
                place_id,
            ),
            "recovery public place identity invalid",
        )
        detail = request(api_base_url + "/places/" + place_id)
        _require(
            isinstance(detail, dict) and detail.get("id") == place_id,
            "recovery detail mismatch",
        )
        rules = request(stack + "/api/prometheus/grafana/api/v1/rules", secret=True)
        rule = _rule(rules, environment, service, rule_uid, uid, alert_name=alert_name)
        instances = rule["alerts"]
        # Grafana retains Normal instances on inactive healthy rules; an empty
        # list is not the only healthy API shape (official api_prometheus_test).
        allowed_settled_states = (
            {"Normal", "NoData"} if environment == "development" else {"Normal"}
        )
        _ready(
            rule["health"] == "ok"
            and rule["state"] == "inactive"
            and all(
                instance["state"] in allowed_settled_states for instance in instances
            ),
            "recovery rule settling",
        )
        evaluated = _timestamp(rule.get("lastEvaluation"))
        _ready(
            0 <= clock() - evaluated <= FRESH_SECONDS
            and (previous_evaluation is None or evaluated >= previous_evaluation),
            "recovery rule evaluation stale",
        )
        previous_evaluation = evaluated
        alerts = request(stack + "/api/alertmanager/grafana/api/v2/alerts", secret=True)
        _require(
            isinstance(alerts, list) and len(alerts) <= 1000, "recovery alerts invalid"
        )
        for alert in alerts:
            _require(
                isinstance(alert, dict) and isinstance(alert.get("labels"), dict),
                "recovery alert schema invalid",
            )
            labels = alert["labels"]
            # Every generation is checked, including silenced/inhibited alerts.
            if environment == "development":
                # In development, synthetic monitoring is not continuous, so the synthetic probe check produces NoData in Alertmanager.
                # Permit development recovery without artificial dependency on synthetic monitors.
                continue
            _ready(
                not (
                    labels.get("environment") == environment
                    and labels.get("service") == service
                ),
                "recovery alert generation returned",
            )
        selector = f'environment="{environment}",service="{service}",release="{release["image_digest"]}"'
        predicates = []
        for metric in (
            "pawlocal_api_requests_total",
            "pawlocal_dependency_requests_total",
        ):
            total = f"{metric}{{{selector}}}"
            success = f'{metric}{{{selector},outcome="success"}}'
            predicates.extend(
                (
                    f"(sum(increase({success}[2m])) > 0)",
                    f"(sum(increase({total}[2m])) - sum(increase({success}[2m])) == 0)",
                    f"(min(timestamp({total})) > {clock() - FRESH_SECONDS})",
                )
            )
        query = " and ".join(predicates)
        result = request(
            stack
            + "/api/datasources/proxy/uid/"
            + uid
            + "/api/v1/query?"
            + urllib.parse.urlencode({"query": query}),
            secret=True,
        )
        _require(
            isinstance(result, dict) and isinstance(result.get("data"), dict),
            "recovery metric response invalid",
        )
        data = result.get("data", {})
        rows = data.get("result")
        _require(
            result.get("status") == "success"
            and not result.get("warnings")
            and data.get("resultType") == "vector"
            and isinstance(rows, list)
            and len(rows) <= 1,
            "recovery metric health unknown",
        )
        _ready(len(rows) == 1, "recovery metrics settling")
        try:
            timestamp, count = rows[0]["value"]
            timestamp, count = float(timestamp), float(count)
            _require(
                math.isfinite(timestamp) and math.isfinite(count),
                "recovery metric nonfinite",
            )
            _ready(
                math.isfinite(timestamp)
                and math.isfinite(count)
                and count > 0
                and 0 <= clock() - timestamp <= FRESH_SECONDS,
                "recovery metrics stale or unhealthy",
            )
        except Denied:
            raise
        except (KeyError, ValueError, TypeError) as error:
            raise Denied("recovery metric schema invalid") from error

    while True:
        try:
            sample()
        except _Settling as error:
            if started is not None:
                raise Denied("recovery regressed during stable window") from error
            settling_samples += 1
            _require(
                clock() + INTERVAL + profile.recovery_seconds < deadline,
                "recovery settling exhausted phase deadline",
            )
            sleep(INTERVAL)
            continue
        completed = clock()
        if started is None:
            started = completed
            _require(
                started + profile.recovery_seconds < deadline,
                "recovery stable window exceeds phase deadline",
            )
        samples += 1
        _enabled(environment, profile, completed, deadline)
        if control is not None:
            control()
        if completed - started >= profile.recovery_seconds:
            return {
                "schema": 1,
                "environment": environment,
                "commit": release["affected_sha"],
                "digest": release["image_digest"],
                "deployment_id": release["deployment_id"],
                "deployment_run": release["deployment_run"],
                "window_seconds": profile.recovery_seconds,
                "started_at": started,
                "completed_at": completed,
                "samples": samples,
                "settling_seconds": started - entered,
                "settling_samples": settling_samples,
                "profile_sha256": profile.digest,
            }
        sleep(min(INTERVAL, started + profile.recovery_seconds - completed))


def configured_rule(
    trusted,
    environment,
    profile,
    *,
    service,
    api_base_url,
    frontend_origin,
    stack_url,
    query_token,
    deadline,
    opener=None,
    clock=time.time,
    control=None,
):
    """Verify monitored production prerequisites before dispatch, never recovery.

    Known firing/pending instances are allowed because the repair is not yet
    promoted. Missing/paused/stale/error/unknown rule state fails closed.
    """
    if not enabled():
        skipped("recovery")
        return
    _enabled(environment, profile, clock(), deadline)
    rule_uid, stack, frontend, _ = _scope(
        environment,
        profile,
        service,
        api_base_url,
        frontend_origin,
        stack_url,
        query_token,
    )
    uid = _binding(trusted, environment, frontend, stack)
    if control is not None:
        control()
    _enabled(environment, profile, clock(), deadline)
    url = stack + "/api/prometheus/grafana/api/v1/rules"
    request = urllib.request.Request(
        url,
        headers={
            "Authorization": "Bearer " + query_token,
            "Accept": "application/json",
        },
    )
    try:
        with (opener or urllib.request.build_opener(NoRedirect)).open(
            request, timeout=min(10, deadline - clock())
        ) as response:
            _require(
                response.status == 200 and response.geturl() == url,
                "recovery prerequisite HTTP response invalid",
            )
            raw = response.read(MAX_BODY + 1)
            _require(len(raw) <= MAX_BODY, "recovery prerequisite response bound")
        rule = _rule(strict_json(raw), environment, service, rule_uid, uid)
        _require(
            rule["health"] == "ok"
            and 0 <= clock() - _timestamp(rule.get("lastEvaluation")) <= FRESH_SECONDS,
            "recovery prerequisite rule unhealthy or stale",
        )
        _require(
            _binding(trusted, environment, frontend, stack) == uid,
            "recovery prerequisite binding changed",
        )
        if control is not None:
            control()
        _enabled(environment, profile, clock(), deadline)
    except Denied:
        raise
    except Exception as error:
        raise Denied("recovery prerequisite unavailable") from error
