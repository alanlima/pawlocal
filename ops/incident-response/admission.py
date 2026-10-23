"""Trusted main-only preflight. Never executed from a candidate checkout."""

import datetime as dt
import fnmatch
import hashlib
import json
import os
import re
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
            r"/(?:issues(?:/\d+(?:/comments)?)?|deployments(?:/\d+/statuses)?|actions/runs/\d+(?:/jobs)?|rulesets(?:/\d+)?|commits/[0-9a-f]{40}|git/ref/heads/main|environments/(?:development|production)(?:-plan|-apply)?(?:/deployment-branch-policies)?|environments/oncall-(?:development|production)(?:/deployment-branch-policies)?)(?:\?[A-Za-z0-9_=&-]+)?",
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


def verified_record(github, deployment, environment):
    if (
        deployment.get("repository_url") != GITHUB
        or deployment.get("creator", {}).get("login") != "github-actions[bot]"
    ):
        raise Denied("untrusted deployment record owner")
    payload = deployment.get("payload", {})
    if isinstance(payload, str):
        payload = strict_json(payload)
    sha = deployment.get("sha", "")
    if (
        not isinstance(payload, dict)
        or not re.fullmatch(r"[0-9a-f]{40}", sha)
        or payload.get("release_commit") != sha
    ):
        raise Denied("explicit deployed commit missing")
    digest = payload.get("backend_image_digest", "")
    if (
        not re.fullmatch(r"sha256:[0-9a-f]{64}", digest)
        or payload.get("running_image_digest") != digest
        or payload.get("backend_image") != "ghcr.io/alanlima/pawlocal-api@" + digest
    ):
        raise Denied("deployed immutable image differs")
    record_schema = payload.get("record_schema_version")
    manifest_schema = payload.get("manifest_schema_version")
    evidence_schema = payload.get("evidence_schema_version")
    if record_schema != 1 or (manifest_schema, evidence_schema) not in {(2, 1), (3, 2)}:
        raise Denied("validated release/telemetry evidence missing")
    if manifest_schema == 3 and not isinstance(payload.get("frontend_telemetry_enabled"), bool):
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
    if type(run_id) is not int or type(attempt) is not int or attempt < 1:
        raise Denied("deployment producer run missing")
    run = github.request("GET", f"/actions/runs/{run_id}")
    expected = (
        ".github/workflows/fullstack-release.yml"
        if environment == "development"
        else ".github/workflows/deploy-production.yml"
    )
    event = "push" if environment == "development" else "workflow_dispatch"
    if (
        run.get("repository", {}).get("id") != 1423024931
        or run.get("head_repository", {}).get("id") != 1423024931
        or run.get("conclusion") != "success"
        or run.get("event") != event
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
    if not statuses or len(statuses) >= 100:
        raise Denied("deployment status uncertainty")
    latest = max(statuses, key=lambda value: value.get("created_at", ""))
    if (
        latest.get("state") != "success"
        or latest.get("creator", {}).get("login") != "github-actions[bot]"
    ):
        raise Denied("latest deployment is not a trusted successful release")
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
                verified = verified_record(github, candidate, "development")
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
    summaries = github.request("GET", "/rulesets?per_page=100")
    if not isinstance(summaries, list) or len(summaries) >= 100:
        raise Denied("ruleset inventory unknown")
    required = {
        "PawLocal change authorization",
        "Backend checks / Backend checks",
        "Frontend checks and HTTP-mode build / frontend",
    }
    protections, checks = set(), set()

    def matches(pattern):
        if not isinstance(pattern, str):
            raise Denied("unknown ruleset branch pattern")
        if pattern in {"~ALL", "~DEFAULT_BRANCH"}:
            return True
        if not pattern.startswith("refs/heads/"):
            raise Denied("unsupported branch ruleset selector")
        # A conservative over-match denies uncertain protection configurations;
        # it can never ignore a potentially applicable approval requirement.
        return fnmatch.fnmatchcase("refs/heads/main", pattern)

    for summary in summaries:
        if type(summary.get("id")) is not int:
            raise Denied("invalid ruleset")
        rule = github.request("GET", f"/rulesets/{summary['id']}")
        if (
            rule.get("enforcement") in {"disabled", "evaluate"}
            or rule.get("target") == "tag"
        ):
            continue
        if rule.get("enforcement") != "active" or rule.get("target") != "branch":
            raise Denied("unknown active ruleset target/enforcement")
        conditions = rule.get("conditions", {})
        names = conditions.get("ref_name", {})
        if (
            set(conditions) != {"ref_name"}
            or not isinstance(names.get("include"), list)
            or not isinstance(names.get("exclude"), list)
        ):
            raise Denied("effective ruleset conditions unknown")
        included = [matches(pattern) for pattern in names["include"]]
        excluded = [matches(pattern) for pattern in names["exclude"]]
        if not any(included) or any(excluded):
            continue
        if rule.get("bypass_actors") != [] or not isinstance(rule.get("rules"), list):
            raise Denied("applicable bypass or policy inventory unsupported")
        for item in rule["rules"]:
            kind = item.get("type")
            if kind not in {
                "deletion",
                "non_fast_forward",
                "pull_request",
                "required_status_checks",
            }:
                raise Denied("unreviewed effective main policy")
            parameters = item.get("parameters", {})
            if kind == "pull_request" and not (
                parameters.get("required_approving_review_count") == 0
                and parameters.get("require_code_owner_review") is False
                and parameters.get("required_review_thread_resolution") is True
                and parameters.get("allowed_merge_methods") == ["squash"]
                and parameters.get("require_last_push_approval", False) is False
            ):
                raise Denied("effective PR policy requires unsupported/human gates")
            if kind == "required_status_checks":
                if parameters.get("strict_required_status_checks_policy") is not True:
                    raise Denied("strict candidate checks required")
                entries = parameters.get("required_status_checks")
                if not isinstance(entries, list) or any(
                    not isinstance(entry.get("context"), str) for entry in entries
                ):
                    raise Denied("status policy inventory unknown")
                for entry in entries:
                    if entry["context"] == "PawLocal change authorization" and (
                        type(entry.get("integration_id")) is not int
                        or entry["integration_id"] != authorizer
                    ):
                        raise Denied(
                            "ordinary change authorization must pin the trusted App source"
                        )
                checks.update(entry["context"] for entry in entries)
            protections.add(kind)
    if (
        not {"deletion", "non_fast_forward", "pull_request", "required_status_checks"}
        <= protections
        or not required <= checks
    ):
        raise Denied(
            "complete autonomous machine protections must be configured before admission"
        )
    classic_absent(github.deadline)
    runtime_ready(github)


def main():
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


if __name__ == "__main__":
    main()
