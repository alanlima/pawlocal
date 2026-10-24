"""Trusted main-only preflight. Never executed from a candidate checkout."""

import datetime as dt
import fnmatch
import hashlib
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

from control import check_ledger
from deadline import arm
from diagnostics import gather
from protection import classic_absent
from quota import Denied, Profile, integer, reserve, strict_json
from quota_gateway import NoRedirect
from settings import bindings_ready, runtime_ready

REPOSITORY = "alanlima/pawlocal"
GITHUB = "https://api.github.com/repos/" + REPOSITORY
LEDGER_MARKER = "<!-- pawlocal-oncall-quota:v1 -->"
ENTRY_MARKER = "<!-- pawlocal-oncall-reservation:v1 -->"
INCIDENT_PREFIX = "<!-- pawlocal-incident:v1:"


class GitHub:
    def __init__(self, token, deadline, opener=None):
        if not token:
            raise Denied("GitHub credential missing")
        self.token = token
        self.deadline = deadline
        self.opener = opener or urllib.request.build_opener(NoRedirect)

    def request(self, method, path, data=None):
        # Only issue writes, repository/deployment/run reads in this client.
        allowed = method == "GET" and re.fullmatch(
            r"/(?:issues(?:/\d+(?:/comments)?)?|deployments(?:/\d+/statuses)?|actions/runs/\d+(?:/jobs|/attempts/[1-9][0-9]*)?|rulesets(?:/\d+)?|commits/[0-9a-f]{40}|git/ref/heads/main|environments/(?:development|production)(?:-plan|-apply)?(?:/deployment-branch-policies)?|environments/oncall-(?:development|production)(?:/deployment-branch-policies)?)(?:\?[A-Za-z0-9_=&-]+)?",
            path,
        )
        allowed = (
            allowed
            or method == "POST"
            and re.fullmatch(r"/issues(?:/\d+/comments)?", path)
        )
        allowed = allowed or (
            method == "PATCH"
            and re.fullmatch(r"/issues/[1-9][0-9]*", path)
            and data == {"state": "closed", "state_reason": "completed"}
        )
        if not allowed or time.time() >= self.deadline:
            raise Denied("unapproved GitHub operation/deadline")
        raw = None if data is None else json.dumps(data, separators=(",", ":")).encode()
        request = urllib.request.Request(
            GITHUB + path,
            data=raw,
            method=method,
            headers={
                "Authorization": "Bearer " + self.token,
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "Content-Type": "application/json",
            },
        )
        with self.opener.open(
            request, timeout=min(15, self.deadline - time.time())
        ) as response:
            if response.status not in (200, 201):
                raise Denied("GitHub acknowledgement failed")
            body = response.read(2 * 1024 * 1024 + 1)
            if len(body) > 2 * 1024 * 1024:
                raise Denied("GitHub response bound")
            return strict_json(body)

    def pages(self, path, maximum=10):
        results = []
        for page in range(1, maximum + 1):
            values = self.request(
                "GET",
                path + ("&" if "?" in path else "?") + f"per_page=100&page={page}",
            )
            if not isinstance(values, list):
                raise Denied("GitHub list expected")
            results.extend(values)
            if len(values) < 100:
                return results
        raise Denied("pagination bound; owner reconciliation required")


def alerts(raw, environment):
    if environment not in {"development", "production"} or len(raw.encode()) > 32768:
        raise Denied("invalid environment/payload bound")
    values = strict_json(raw)
    if not isinstance(values, list) or not 1 <= len(values) <= 20:
        raise Denied("invalid alert group")
    seen = set()
    for value in values:
        required = {
            "incident_key",
            "fingerprint",
            "status",
            "starts_at",
            "ends_at",
            "environment",
            "service",
            "alert_name",
        }
        if not isinstance(value, dict) or not required <= set(value):
            raise Denied("normalized alert fields missing")
        if not isinstance(value, dict) or set(value) - {
            "incident_key",
            "fingerprint",
            "status",
            "starts_at",
            "ends_at",
            "environment",
            "service",
            "alert_name",
            "release",
            "route",
        }:
            raise Denied("invalid normalized alert schema")
        if value.get("environment") != environment or not all(
            isinstance(value.get(key), str)
            and re.fullmatch(r"[a-z][a-z0-9-]{0,99}", value[key])
            for key in ("service", "alert_name")
        ):
            raise Denied("unsupported alert")
        if (
            value.get("status") not in {"firing", "resolved"}
            or not isinstance(value.get("fingerprint"), str)
            or not re.fullmatch(r"[0-9a-f]{16,64}", value["fingerprint"])
        ):
            raise Denied("invalid generation")
        try:
            started = dt.datetime.fromisoformat(value["starts_at"])
        except (ValueError, TypeError, KeyError) as error:
            raise Denied("invalid start time") from error
        if (
            started.tzinfo != dt.UTC
            or started.timestamp() < 0
            or started.timestamp() > time.time() + 30
            or started.isoformat(timespec="milliseconds").replace("+00:00", "Z")
            != value["starts_at"]
        ):
            raise Denied("invalid generation time")
        try:
            ended = dt.datetime.fromisoformat(value["ends_at"])
        except (ValueError, TypeError) as error:
            raise Denied("invalid normalized resolution") from error
        if (
            ended.tzinfo != dt.UTC
            or ended.isoformat(timespec="milliseconds").replace("+00:00", "Z")
            != value["ends_at"]
            or value["status"] == "resolved"
            and ended < started
        ):
            raise Denied("invalid normalized resolution")
        key = hashlib.sha256(
            json.dumps(
                [environment, value["fingerprint"], value["starts_at"]],
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        if value.get("incident_key") != key or key in seen:
            raise Denied("incorrect or duplicate incident identity")
        seen.add(key)
        if "release" in value and (
            not isinstance(value["release"], str)
            or not re.fullmatch(
                r"(?:[0-9a-f]{40}|sha256:[0-9a-f]{64})", value["release"]
            )
        ):
            raise Denied("invalid release")
        # The receiver intentionally omits route labels. Do not reintroduce a
        # route allowlist or forward arbitrary customer paths into model context.
        if "route" in value:
            raise Denied("route labels must be removed by the receiver")
    return values


def current_alert(stack_url, token, alert, deadline, opener=None):
    parsed = urllib.parse.urlsplit(stack_url)
    if (
        parsed.scheme != "https"
        or not re.fullmatch(r"[a-z0-9-]+\.grafana\.net", parsed.netloc)
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise Denied("approved Grafana stack URL required")
    if not token or time.time() >= deadline:
        raise Denied("alert read unavailable")
    request = urllib.request.Request(
        stack_url.rstrip("/") + "/api/alertmanager/grafana/api/v2/alerts",
        headers={"Authorization": "Bearer " + token, "Accept": "application/json"},
    )
    with (opener or urllib.request.build_opener(NoRedirect)).open(
        request, timeout=min(15, deadline - time.time())
    ) as response:
        body = response.read(2 * 1024 * 1024 + 1)
        if response.status != 200 or len(body) > 2 * 1024 * 1024:
            raise Denied("alert read failed")
        values = strict_json(body)
    if not isinstance(values, list):
        raise Denied("unknown alert response")
    for value in values:
        if not isinstance(value, dict):
            raise Denied("unknown alert entry")
        labels = value.get("labels", {})
        if value.get("fingerprint") != alert["fingerprint"]:
            continue
        try:
            started = (
                dt.datetime.fromisoformat(value.get("startsAt", ""))
                .isoformat(timespec="milliseconds")
                .replace("+00:00", "Z")
            )
        except (ValueError, AttributeError) as error:
            raise Denied("invalid current alert generation") from error
        if (
            started != alert["starts_at"]
            or labels.get("environment") != alert["environment"]
            or labels.get("service") != alert["service"]
            or labels.get("alertname") != alert["alert_name"]
        ):
            raise Denied("current generation differs")
        status = value.get("status", {}).get("state")
        if status != "active":
            raise Denied("current alert state is suppressed or unknown")
        return True
    return False


def verified_record(github, deployment, environment, *, historical=False):
    """Verify current runtime, or durable success of an exact past producer attempt."""
    if (
        deployment.get("environment") != environment
        or deployment.get("repository_url") != GITHUB
        or deployment.get("creator", {}).get("login") != "github-actions[bot]"
    ):
        raise Denied("untrusted deployment record owner")
    payload = deployment.get("payload", {})
    if isinstance(payload, str):
        payload = strict_json(payload)
    sha = deployment.get("sha", "")
    if (
        not isinstance(payload, dict)
        or not isinstance(sha, str)
        or not re.fullmatch(r"[0-9a-f]{40}", sha)
        or payload.get("release_commit") != sha
    ):
        raise Denied("explicit deployed commit missing")
    digest = payload.get("backend_image_digest", "")
    if (
        not isinstance(digest, str)
        or not re.fullmatch(r"sha256:[0-9a-f]{64}", digest)
        or payload.get("running_image_digest") != digest
        or payload.get("backend_image") != "ghcr.io/alanlima/pawlocal-api@" + digest
    ):
        raise Denied("deployed immutable image differs")
    record_schema = payload.get("record_schema_version")
    manifest_schema = payload.get("manifest_schema_version")
    evidence_schema = payload.get("evidence_schema_version")
    if (
        any(type(version) is not int for version in (record_schema, manifest_schema, evidence_schema))
        or record_schema != 1
        or (manifest_schema, evidence_schema) not in {(2, 1), (3, 2)}
    ):
        raise Denied("validated release/telemetry evidence missing")
    if (
        manifest_schema == 2 and "frontend_telemetry_enabled" in payload
        or manifest_schema == 3 and not isinstance(payload.get("frontend_telemetry_enabled"), bool)
    ):
        raise Denied("validated release/telemetry evidence missing")
    required = {
        "evidence_validated": True,
        "database_provider": "aurora_dsql",
        "migration_runner": "dsql_baseline",
        "migration_id": "dsql_0001_initial",
        "telemetry_enabled": True,
    }
    if any(
        type(payload.get(key)) is not type(value) or payload.get(key) != value
        for key, value in required.items()
    ):
        raise Denied("validated release/telemetry evidence missing")
    if any(
        not isinstance(payload.get(key), str)
        or not re.fullmatch(r"sha256:[0-9a-f]{64}", payload[key])
        for key in (
            "release_manifest_digest",
            "verification_evidence_digest",
            "frontend_artifact_digest",
        )
    ):
        raise Denied("release evidence digests missing")
    if payload.get("public_endpoint_health") != {
        "frontend": True,
        "api": True,
    } or payload.get("database_query_smoke") != {
        "route": "/api/v1/places",
        "result": "valid_place_page",
    }:
        raise Denied("release health evidence missing")
    run_id = payload.get("workflow_run_id")
    attempt = payload.get("workflow_run_attempt")
    if (
        type(run_id) is not int
        or not 1 <= run_id <= 9007199254740991
        or type(attempt) is not int
        or not 1 <= attempt <= 9007199254740991
    ):
        raise Denied("deployment producer run missing")
    run_path = f"/actions/runs/{run_id}"
    if historical:
        run_path += f"/attempts/{attempt}"
    run = github.request("GET", run_path)
    expected = (
        ".github/workflows/fullstack-release.yml"
        if environment == "development"
        else ".github/workflows/deploy-production.yml"
    )
    events = (
        {"push", "workflow_dispatch"}
        if environment == "development"
        else {"workflow_dispatch"}
    )
    if (
        run.get("id") != run_id
        or run.get("status") != "completed"
        or run.get("repository", {}).get("id") != 1423024931
        or run.get("head_repository", {}).get("id") != 1423024931
        or run.get("conclusion") != "success"
        or run.get("event") not in events
        or run.get("path") != expected
        or run.get("head_branch") != "main"
        or run.get("run_attempt") != attempt
    ):
        raise Denied("untrusted deployment producer")
    if environment == "development" and run.get("head_sha") != sha:
        raise Denied("development producer commit differs")
    statuses = github.request(
        "GET", f"/deployments/{deployment['id']}/statuses?per_page=100"
    )
    if not isinstance(statuses, list) or not statuses or len(statuses) >= 100:
        raise Denied("deployment status uncertainty")
    if any(
        not isinstance(value, dict)
        or not isinstance(value.get("created_at"), str)
        or not value["created_at"]
        for value in statuses
    ):
        raise Denied("deployment status uncertainty")
    # GitHub returns newest first; stable sorting preserves API order on tied
    # timestamps. Inactive only retires a deployment; it does not revoke its
    # verified history. No failure/error/unknown state may be crossed to find it.
    try:
        dated = [
            (dt.datetime.fromisoformat(value["created_at"].replace("Z", "+00:00")), value)
            for value in statuses
        ]
        if any(date.tzinfo is None for date, _value in dated):
            raise ValueError("timezone missing")
    except ValueError as error:
        raise Denied("deployment status timestamp uncertainty") from error
    ordered = [
        value for _date, value in sorted(dated, key=lambda pair: pair[0], reverse=True)
    ]
    for status in ordered:
        if status.get("creator", {}).get("login") != "github-actions[bot]":
            raise Denied("untrusted deployment status")
        if status.get("state") == "success":
            break
        if not historical or status.get("state") != "inactive":
            raise Denied("latest deployment is not a trusted successful release")
    else:
        raise Denied("deployment has no trusted successful verification")
    return {
        "affected_sha": sha,
        "image_digest": digest,
        "deployment_id": deployment["id"],
        "deployment_run": run_id,
    }


def deployed_release(github, environment):
    deployments = github.pages("/deployments?environment=" + environment, maximum=2)
    if not deployments:
        raise Denied("deployed release not found")
    # A failed/unknown newer deployment can have changed runtime identity. Do
    # not silently fall back to an older successful record.
    selected = max(deployments, key=lambda value: value.get("created_at", ""))
    release = verified_record(github, selected, environment)
    if environment == "production":
        development = github.pages(
            "/deployments?environment=development&ref=" + release["affected_sha"],
            maximum=2,
        )
        matched = False
        for candidate in development:
            try:
                verified = verified_record(github, candidate, "development", historical=True)
            except Denied:
                continue
            if (
                verified["affected_sha"] == release["affected_sha"]
                and verified["image_digest"] == release["image_digest"]
            ):
                matched = True
                break
        if not matched:
            raise Denied("production lacks matching development-verified pair")
    return release


def reserve_month(github, profile, issue_number, run_id, attempt):
    if not re.fullmatch(r"[1-9]\d{0,9}", issue_number):
        raise Denied("protected ledger issue missing")
    issue = github.request("GET", "/issues/" + issue_number)
    if (
        issue.get("state") != "open"
        or not issue.get("body", "").startswith(LEDGER_MARKER)
        or issue.get("user", {}).get("login") != "alanlima"
    ):
        raise Denied("trusted ledger issue missing")
    comments = github.pages(f"/issues/{issue_number}/comments", maximum=100)
    ledger = []
    for comment in comments:
        if not comment.get("body", "").startswith(ENTRY_MARKER):
            continue
        if comment.get("user", {}).get("login") != "github-actions[bot]":
            raise Denied("untrusted ledger reservation")
        ledger.append(strict_json(comment["body"][len(ENTRY_MARKER) :].strip()))
    month = dt.datetime.now(dt.UTC).strftime("%Y-%m")
    entry = reserve(profile, ledger, month, run_id, attempt)
    body = (
        ENTRY_MARKER + "\n" + json.dumps(entry, sort_keys=True, separators=(",", ":"))
    )
    check_ledger(
        lambda path: github.request("GET", path), int(issue_number), github.deadline
    )
    created = github.request("POST", f"/issues/{issue_number}/comments", {"body": body})
    if (
        created.get("body") != body
        or created.get("user", {}).get("login") != "github-actions[bot]"
        or not isinstance(created.get("id"), int)
    ):
        raise Denied("reservation acknowledgement uncertain")
    # Write acknowledgement binds exact reservation; a timeout leaves admission
    # denied. Existing reservation blocks an owner rerun rather than refunding.
    return entry


def readiness(github):
    authorizer = integer(int(os.environ.get("PAWLOCAL_AUTHORIZER_APP_ID", "0")))
    path = Path(os.environ.get("RUNNER_TEMP", "")) / "oncall-readiness-token.json"
    if path.is_file():
        try:
            capability = strict_json(path.read_bytes())
            token = capability.get("token")
            if token and isinstance(token, str):
                github = GitHub(token, github.deadline, github.opener)
                print(f"[readiness] Loaded elevated readiness token from {path}", file=sys.stderr)
            else:
                print(f"[readiness] Warning: {path} found but missing valid 'token' string", file=sys.stderr)
        except Exception as exc:
            print(f"[readiness] Warning: Failed to parse readiness token from {path}: {exc}", file=sys.stderr)
    else:
        print(f"[readiness] No oncall-readiness-token.json found at {path}; using default GitHub token", file=sys.stderr)
    summaries = github.request("GET", "/rulesets?per_page=100")
    if not isinstance(summaries, list) or len(summaries) >= 100:
        msg = f"ruleset inventory unknown (type={type(summaries).__name__}, count={len(summaries) if isinstance(summaries, list) else 'N/A'})"
        print(f"[readiness] DENIED: {msg}", file=sys.stderr)
        raise Denied(msg)
    required = {
        "PawLocal change authorization",
        "Backend checks / Backend checks",
        "Frontend checks and HTTP-mode build / frontend",
    }
    protections, checks = set(), set()
    active_rulesets = []

    def matches(pattern):
        if not isinstance(pattern, str):
            msg = f"unknown ruleset branch pattern: {pattern!r}"
            print(f"[readiness] DENIED: {msg}", file=sys.stderr)
            raise Denied(msg)
        if pattern in {"~ALL", "~DEFAULT_BRANCH"}:
            return True
        if not pattern.startswith("refs/heads/"):
            msg = f"unsupported branch ruleset selector: {pattern!r}"
            print(f"[readiness] DENIED: {msg}", file=sys.stderr)
            raise Denied(msg)
        # A conservative over-match denies uncertain protection configurations;
        # it can never ignore a potentially applicable approval requirement.
        return fnmatch.fnmatchcase("refs/heads/main", pattern)

    for summary in summaries:
        if type(summary.get("id")) is not int:
            msg = f"invalid ruleset summary id: {summary.get('id')!r}"
            print(f"[readiness] DENIED: {msg}", file=sys.stderr)
            raise Denied(msg)
        rule_id = summary["id"]
        rule = github.request("GET", f"/rulesets/{rule_id}")
        rule_name = rule.get("name", summary.get("name", f"ruleset-{rule_id}"))
        print(f"[readiness] Inspecting ruleset id={rule_id} name={rule_name!r}", file=sys.stderr)
        if (
            rule.get("enforcement") in {"disabled", "evaluate"}
            or rule.get("target") == "tag"
        ):
            print(
                f"[readiness] Skipping inactive/non-branch ruleset id={rule_id} ({rule_name!r}): "
                f"enforcement={rule.get('enforcement')!r}, target={rule.get('target')!r}",
                file=sys.stderr,
            )
            continue
        if rule.get("enforcement") != "active" or rule.get("target") != "branch":
            msg = (
                f"ruleset id={rule_id} ({rule_name!r}): unknown active ruleset target/enforcement "
                f"(enforcement={rule.get('enforcement')!r}, target={rule.get('target')!r})"
            )
            print(f"[readiness] DENIED: {msg}", file=sys.stderr)
            raise Denied(msg)
        conditions = rule.get("conditions", {})
        names = conditions.get("ref_name", {})
        if (
            set(conditions) != {"ref_name"}
            or not isinstance(names.get("include"), list)
            or not isinstance(names.get("exclude"), list)
        ):
            msg = (
                f"ruleset id={rule_id} ({rule_name!r}): effective ruleset conditions unknown "
                f"(conditions={conditions!r})"
            )
            print(f"[readiness] DENIED: {msg}", file=sys.stderr)
            raise Denied(msg)
        included = [matches(pattern) for pattern in names["include"]]
        excluded = [matches(pattern) for pattern in names["exclude"]]
        if not any(included) or any(excluded):
            print(
                f"[readiness] Skipping ruleset id={rule_id} ({rule_name!r}): does not target main "
                f"(include={names.get('include')}, exclude={names.get('exclude')})",
                file=sys.stderr,
            )
            continue
        bypass = rule.get("bypass_actors")
        current_bypass = rule.get("current_user_can_bypass", "never")
        rules_list = rule.get("rules")
        if (
            (bypass is not None and bypass != [])
            or current_bypass != "never"
            or not isinstance(rules_list, list)
        ):
            reasons = []
            if bypass is not None and bypass != []:
                reasons.append(f"bypass_actors is non-empty: {bypass!r}")
            if current_bypass != "never":
                reasons.append(f"current_user_can_bypass is {current_bypass!r} (must be 'never')")
            if not isinstance(rules_list, list):
                reasons.append(f"rules is not a list: {type(rules_list).__name__}")
            msg = f"ruleset id={rule_id} ({rule_name!r}): applicable bypass or policy inventory unsupported: {'; '.join(reasons)}"
            print(f"[readiness] DENIED: {msg}", file=sys.stderr)
            raise Denied(msg)
        for item in rule["rules"]:
            kind = item.get("type")
            if kind not in {
                "deletion",
                "non_fast_forward",
                "pull_request",
                "required_status_checks",
            }:
                msg = f"ruleset id={rule_id} ({rule_name!r}): unreviewed effective main policy type: {kind!r}"
                print(f"[readiness] DENIED: {msg}", file=sys.stderr)
                raise Denied(msg)
            parameters = item.get("parameters", {})
            if kind == "pull_request" and not (
                parameters.get("required_approving_review_count") == 0
                and parameters.get("require_code_owner_review") is False
                and parameters.get("required_review_thread_resolution") is True
                and parameters.get("allowed_merge_methods") == ["squash"]
                and parameters.get("require_last_push_approval", False) is False
            ):
                actual_pr_params = {
                    "required_approving_review_count": parameters.get("required_approving_review_count"),
                    "require_code_owner_review": parameters.get("require_code_owner_review"),
                    "required_review_thread_resolution": parameters.get("required_review_thread_resolution"),
                    "allowed_merge_methods": parameters.get("allowed_merge_methods"),
                    "require_last_push_approval": parameters.get("require_last_push_approval", False),
                }
                msg = (
                    f"ruleset id={rule_id} ({rule_name!r}): effective PR policy requires unsupported/human gates "
                    f"(actual parameters: {actual_pr_params})"
                )
                print(f"[readiness] DENIED: {msg}", file=sys.stderr)
                raise Denied(msg)
            if kind == "required_status_checks":
                if parameters.get("strict_required_status_checks_policy") is not True:
                    msg = (
                        f"ruleset id={rule_id} ({rule_name!r}): strict candidate checks required "
                        f"(strict_required_status_checks_policy={parameters.get('strict_required_status_checks_policy')!r})"
                    )
                    print(f"[readiness] DENIED: {msg}", file=sys.stderr)
                    raise Denied(msg)
                entries = parameters.get("required_status_checks")
                if not isinstance(entries, list) or any(
                    not isinstance(entry.get("context"), str) for entry in entries
                ):
                    msg = f"ruleset id={rule_id} ({rule_name!r}): status policy inventory unknown (entries={entries!r})"
                    print(f"[readiness] DENIED: {msg}", file=sys.stderr)
                    raise Denied(msg)
                for entry in entries:
                    if entry["context"] == "PawLocal change authorization" and (
                        type(entry.get("integration_id")) is not int
                        or entry["integration_id"] != authorizer
                    ):
                        msg = (
                            f"ruleset id={rule_id} ({rule_name!r}): ordinary change authorization must pin the trusted App source "
                            f"(expected integration_id={authorizer}, got {entry.get('integration_id')!r})"
                        )
                        print(f"[readiness] DENIED: {msg}", file=sys.stderr)
                        raise Denied(msg)
                checks.update(entry["context"] for entry in entries)
            protections.add(kind)
        active_rulesets.append(f"id={rule_id} ({rule_name!r})")
    missing_protections = {"deletion", "non_fast_forward", "pull_request", "required_status_checks"} - protections
    missing_checks = required - checks
    if missing_protections or missing_checks:
        reasons = []
        if missing_protections:
            reasons.append(f"missing protections: {sorted(missing_protections)}")
        if missing_checks:
            reasons.append(f"missing required checks: {sorted(missing_checks)}")
        msg = f"complete autonomous machine protections must be configured before admission: {'; '.join(reasons)}"
        print(f"[readiness] DENIED: {msg}", file=sys.stderr)
        raise Denied(msg)
    print(
        f"[readiness] Ruleset validation succeeded for {active_rulesets}: "
        f"protections={sorted(protections)}, confirmed checks={sorted(checks)}",
        file=sys.stderr,
    )
    classic_absent(github.deadline)
    runtime_ready(github)
    print("[readiness] Preflight readiness checks completed successfully", file=sys.stderr)


def _main():
    deadline = int(os.environ["INCIDENT_DEADLINE"])
    arm(deadline)
    if (
        os.environ.get("GITHUB_REPOSITORY") != REPOSITORY
        or os.environ.get("GITHUB_REF") != "refs/heads/main"
        or os.environ.get("GITHUB_EVENT_NAME") != "workflow_dispatch"
        or os.environ.get("GITHUB_RUN_ATTEMPT") != "1"
    ):
        raise Denied("trusted main first-attempt dispatch required")
    actor = os.environ.get("PAWLOCAL_DISPATCH_ACTOR", "")
    if (
        not re.fullmatch(r"[a-z0-9-]+\[bot\]", actor)
        or os.environ.get("GITHUB_ACTOR") != actor
    ):
        raise Denied("exact installed dispatch App actor required")
    if (
        os.environ.get("PAWLOCAL_ONCALL_ENABLED") != "true"
        or os.environ.get("SCHEMA_VERSION") != "1"
    ):
        raise Denied("admission disabled or unsupported schema")
    profile = Profile.load(os.environ.get("PAWLOCAL_MODEL_PROFILE", ""))
    bindings_ready(os.environ["GITHUB_WORKSPACE"])
    environment = os.environ.get("INCIDENT_ENVIRONMENT", "")
    if (
        environment == "production"
        and os.environ.get("PAWLOCAL_PRODUCTION_TELEMETRY_READ_APPROVED") != "true"
    ):
        raise Denied("production telemetry-read/privacy approval missing")
    received = alerts(os.environ.get("ALERTS_JSON", ""), environment)
    github = GitHub(os.environ.get("GH_TOKEN", ""), deadline)
    readiness(github)
    quota_issue = integer(int(os.environ.get("PAWLOCAL_QUOTA_ISSUE", "0")))
    check_ledger(lambda path: github.request("GET", path), quota_issue, deadline)
    existing = github.pages("/issues?state=all", maximum=100)
    selected = None
    for alert in received:
        marker = INCIDENT_PREFIX + alert["incident_key"] + " -->"
        matches = [
            issue
            for issue in existing
            if marker in issue.get("body", "")
            and issue.get("user", {}).get("login") == "github-actions[bot]"
        ]
        if matches:
            # Closed/failed/resolved claims consume the single generation too.
            continue
        active = alert["status"] == "firing" and current_alert(
            os.environ.get("GRAFANA_STACK_URL", ""),
            os.environ.get("PAWLOCAL_GRAFANA_QUERY_TOKEN", ""),
            alert,
            deadline,
        )
        state = (
            "ADMISSION_PENDING"
            if active and selected is None
            else ("ESCALATED_GROUP_LIMIT" if active else "RESOLVED")
        )
        check_ledger(lambda path: github.request("GET", path), quota_issue, deadline)
        issue = github.request(
            "POST",
            "/issues",
            {
                "title": f"Incident {environment}: search/detail {alert['incident_key'][:12]}",
                "body": marker
                + f"\n\nState: {state}.\n\nGeneration: `{alert['starts_at']}`.\n\nRun: https://github.com/{REPOSITORY}/actions/runs/{os.environ['GITHUB_RUN_ID']}\n\nOne attempt only; trusted automation enforces fresh review, candidate CI, squash merge and verified release promotion.",
                "labels": ["stage-5", "bug"],
            },
        )
        if (
            type(issue.get("number")) is not int
            or issue["number"] <= 0
            or issue.get("user", {}).get("login") != "github-actions[bot]"
        ):
            raise Denied("incident claim acknowledgement uncertain")
        if state == "RESOLVED":
            check_ledger(
                lambda path: github.request("GET", path), quota_issue, deadline
            )
            github.request(
                "PATCH",
                f"/issues/{issue['number']}",
                {"state": "closed", "state_reason": "completed"},
            )
        if active and selected is None:
            selected = {"alert": alert, "issue": issue["number"]}
            with Path(os.environ["GITHUB_OUTPUT"]).open("a") as output:
                output.write(
                    f"issue={issue['number']}\nincident_key={alert['incident_key']}\n"
                )
    if selected is None:
        with Path(os.environ["GITHUB_OUTPUT"]).open("a") as output:
            output.write("admitted=false\n")
        print("[admission] Preflight completed: no firing alerts selected for admission", file=sys.stderr)
        return
    try:
        release = deployed_release(github, environment)
        supplied_release = selected["alert"].get("release")
        if supplied_release and supplied_release not in {
            release["affected_sha"],
            release["image_digest"],
        }:
            raise Denied("alert release differs from current deployment")
        diagnostics = gather(
            os.environ["GITHUB_WORKSPACE"],
            os.environ.get("GRAFANA_STACK_URL", ""),
            os.environ.get("PAWLOCAL_GRAFANA_QUERY_TOKEN", ""),
            selected["alert"],
            release,
            deadline,
        )
        base = github.request("GET", "/git/ref/heads/main")["object"]["sha"]
        if not re.fullmatch(r"[0-9a-f]{40}", base):
            raise Denied("trusted base missing")
        entry = reserve_month(
            github,
            profile,
            os.environ.get("PAWLOCAL_QUOTA_ISSUE", ""),
            os.environ["GITHUB_RUN_ID"],
            1,
        )
        metadata = (
            selected
            | release
            | {
                "diagnostics": diagnostics,
                "base_sha": base,
                "deadline": deadline,
                "run_id": os.environ["GITHUB_RUN_ID"],
                "profile": profile.digest,
                "reservation": entry,
                "quota_issue": int(os.environ["PAWLOCAL_QUOTA_ISSUE"]),
            }
        )
        output = Path(os.environ["RUNNER_TEMP"]) / "oncall-admission"
        output.mkdir(mode=0o700)
        payload = json.dumps(metadata, sort_keys=True, separators=(",", ":")).encode()
        (output / "admission.json").write_bytes(payload)
        (output / "profile.json").write_text(
            json.dumps(profile.__dict__, sort_keys=True)
        )
        with Path(os.environ["GITHUB_OUTPUT"]).open("a") as stream:
            stream.write(
                f"admitted=true\nmetadata_sha256={hashlib.sha256(payload).hexdigest()}\nprofile_sha256={profile.digest}\ndeadline={deadline}\n"
            )
        print(f"[admission] Preflight completed: admitted incident for issue #{selected['issue']}", file=sys.stderr)
    except Exception:
        if time.time() < deadline:
            check_ledger(
                lambda path: github.request("GET", path), quota_issue, deadline
            )
            github.request(
                "POST",
                f"/issues/{selected['issue']}/comments",
                {
                    "body": "ESCALATED: trusted preflight did not complete. Any monthly reservation remains consumed. Inspect this incident's linked failed run; no automatic retry or refund is permitted."
                },
            )
        raise


def main():
    try:
        _main()
    except Exception as exc:
        print(f"[admission] Preflight admission failed: {exc}", file=sys.stderr)
        raise


if __name__ == "__main__":
    main()
