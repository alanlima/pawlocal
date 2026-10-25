"""Shared, strict read-only verification of deployed application release evidence.

This module has no incident admission, quota, runtime-control or policy-switch
responsibility. Callers choose telemetry policy explicitly; all other evidence
checks always apply. Local manifest validation remains in validate-release-metadata.py.
"""

import datetime as dt
import json
import re
import time
import urllib.request

REPOSITORY = "alanlima/pawlocal"
GITHUB = "https://api.github.com/repos/" + REPOSITORY


class ReleaseEvidenceError(ValueError):
    """Release identity or verification evidence could not be established."""


def strict_json(raw):
    def pairs(values):
        result = {}
        for key, value in values:
            if key in result:
                raise ReleaseEvidenceError("duplicate JSON key")
            result[key] = value
        return result

    try:
        return json.loads(
            raw, object_pairs_hook=pairs,
            parse_constant=lambda _: (_ for _ in ()).throw(ReleaseEvidenceError("nonfinite JSON")),
        )
    except (TypeError, json.JSONDecodeError) as error:
        raise ReleaseEvidenceError("invalid JSON") from error


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        raise ReleaseEvidenceError("GitHub redirect rejected")


class GitHub:
    """Bounded release-history GET client; never accepts writes or arbitrary URLs."""

    def __init__(self, token, deadline, opener=None):
        if not token:
            raise ReleaseEvidenceError("GitHub credential missing")
        self.token = token
        self.deadline = deadline
        self.opener = opener or urllib.request.build_opener(NoRedirect)

    def request(self, method, path, data=None):
        allowed = method == "GET" and data is None and re.fullmatch(
            r"/(?:deployments(?:/[1-9][0-9]*/statuses)?|actions/runs/[1-9][0-9]*(?:/attempts/[1-9][0-9]*)?)(?:\?[A-Za-z0-9_=&-]+)?", path,
        )
        if not allowed or time.time() >= self.deadline:
            raise ReleaseEvidenceError("unapproved GitHub operation/deadline")
        request = urllib.request.Request(
            GITHUB + path, method="GET", headers={
                "Authorization": "Bearer " + self.token,
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        with self.opener.open(request, timeout=min(15, self.deadline - time.time())) as response:
            if response.status != 200:
                raise ReleaseEvidenceError("GitHub acknowledgement failed")
            body = response.read(2 * 1024 * 1024 + 1)
            if len(body) > 2 * 1024 * 1024:
                raise ReleaseEvidenceError("GitHub response bound")
            return strict_json(body)

    def pages(self, path, maximum=10):
        if type(maximum) is not int or not 1 <= maximum <= 10:
            raise ReleaseEvidenceError("pagination bound must be between 1 and 10")
        results = []
        for page in range(1, maximum + 1):
            values = self.request("GET", path + ("&" if "?" in path else "?") + f"per_page=100&page={page}")
            if not isinstance(values, list):
                raise ReleaseEvidenceError("GitHub list expected")
            results.extend(values)
            if len(values) < 100:
                return results
        raise ReleaseEvidenceError("pagination bound; owner reconciliation required")


def verified_record(github, deployment, environment, *, historical=False, require_telemetry=True):
    """Verify current runtime, or exact historical success, under caller telemetry policy."""
    if (
        deployment.get("environment") != environment
        or deployment.get("repository_url") != GITHUB
        or deployment.get("creator", {}).get("login") != "github-actions[bot]"
    ):
        raise ReleaseEvidenceError("untrusted deployment record owner")
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
        raise ReleaseEvidenceError("explicit deployed commit missing")
    digest = payload.get("backend_image_digest", "")
    if (
        not isinstance(digest, str)
        or not re.fullmatch(r"sha256:[0-9a-f]{64}", digest)
        or payload.get("running_image_digest") != digest
        or payload.get("backend_image") != "ghcr.io/alanlima/pawlocal-api@" + digest
    ):
        raise ReleaseEvidenceError("deployed immutable image differs")
    record_schema = payload.get("record_schema_version")
    manifest_schema = payload.get("manifest_schema_version")
    evidence_schema = payload.get("evidence_schema_version")
    if (
        any(
            type(version) is not int
            for version in (record_schema, manifest_schema, evidence_schema)
        )
        or record_schema != 1
        or (manifest_schema, evidence_schema) not in {(2, 1), (3, 2)}
    ):
        raise ReleaseEvidenceError("validated release/telemetry evidence missing")
    if (
        manifest_schema == 2
        and "frontend_telemetry_enabled" in payload
        or manifest_schema == 3
        and not isinstance(payload.get("frontend_telemetry_enabled"), bool)
    ):
        raise ReleaseEvidenceError("validated release/telemetry evidence missing")
    required = {
        "evidence_validated": True,
        "database_provider": "aurora_dsql",
        "migration_runner": "dsql_baseline",
        "migration_id": "dsql_0001_initial",
    }
    if (
        type(payload.get("telemetry_enabled")) is not bool
        or (require_telemetry and payload["telemetry_enabled"] is not True)
        or any(
            type(payload.get(key)) is not type(value) or payload.get(key) != value
            for key, value in required.items()
        )
    ):
        raise ReleaseEvidenceError("validated release/telemetry evidence missing")
    if (
        any(
            not isinstance(payload.get(key), str)
            or not re.fullmatch(r"sha256:[0-9a-f]{64}", payload[key])
            for key in (
                "release_manifest_digest",
                "verification_evidence_digest",
                "frontend_artifact_digest",
            )
        )
    ):
        raise ReleaseEvidenceError("release evidence digests missing")
    if (
        payload.get("public_endpoint_health")
        != {
            "frontend": True,
            "api": True,
        }
        or payload.get("database_query_smoke")
        != {
            "route": "/api/v1/places",
            "result": "valid_place_page",
        }
    ):
        raise ReleaseEvidenceError("release health evidence missing")
    run_id = payload.get("workflow_run_id")
    attempt = payload.get("workflow_run_attempt")
    if (
        type(run_id) is not int
        or not 1 <= run_id <= 9007199254740991
        or type(attempt) is not int
        or not 1 <= attempt <= 9007199254740991
    ):
        raise ReleaseEvidenceError("deployment producer run missing")
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
        or run.get("path") not in (
            {expected, ".github/workflows/release-rollback-production.yml"}
            if environment == "production" else {expected}
        )
        or run.get("head_branch") != "main"
        or run.get("run_attempt") != attempt
    ):
        raise ReleaseEvidenceError("untrusted deployment producer")
    if (environment == "development" and run.get("head_sha") != sha):
        raise ReleaseEvidenceError("development producer commit differs")
    statuses = github.request(
        "GET", f"/deployments/{deployment['id']}/statuses?per_page=100"
    )
    if not isinstance(statuses, list) or not statuses or len(statuses) >= 100:
        raise ReleaseEvidenceError("deployment status uncertainty")
    if any(
        not isinstance(value, dict)
        or not isinstance(value.get("created_at"), str)
        or not value["created_at"]
        for value in statuses
    ):
        raise ReleaseEvidenceError("deployment status uncertainty")
    # GitHub returns newest first; stable sorting preserves API order on tied
    # timestamps. Inactive only retires a deployment; it does not revoke its
    # verified history. No failure/error/unknown state may be crossed to find it.
    try:
        dated = [
            (
                dt.datetime.fromisoformat(value["created_at"].replace("Z", "+00:00")),
                value,
            )
            for value in statuses
        ]
        if any(date.tzinfo is None for date, _value in dated):
            raise ValueError("timezone missing")
    except ValueError as error:
        raise ReleaseEvidenceError("deployment status timestamp uncertainty") from error
    ordered = [
        value for _date, value in sorted(dated, key=lambda pair: pair[0], reverse=True)
    ]
    for status in ordered:
        if (
            status.get("creator", {}).get("login") != "github-actions[bot]"
        ):
            raise ReleaseEvidenceError("untrusted deployment status")
        if status.get("state") == "success":
            break
        if (not historical or status.get("state") != "inactive"):
            raise ReleaseEvidenceError("latest deployment is not a trusted successful release")
    else:
        raise ReleaseEvidenceError("deployment has no trusted successful verification")
    return {
        "affected_sha": sha,
        "image_digest": digest,
        "deployment_id": deployment["id"],
        "deployment_run": run_id,
    }


def deployed_release(github, environment, *, require_telemetry=True):
    deployments = github.pages("/deployments?environment=" + environment, maximum=2)
    if not deployments:
        raise ReleaseEvidenceError("deployed release not found")
    # A failed/unknown newer deployment can have changed runtime identity. Do
    # not silently fall back to an older successful record.
    selected = max(deployments, key=lambda value: value.get("created_at", ""))
    release = verified_record(github, selected, environment, require_telemetry=require_telemetry)
    if environment == "production":
        matching_development(github, release, require_telemetry=require_telemetry)
    return release


def matching_development(github, release, *, require_telemetry=True):
    """Require the exact pair's durable development proof, including retired success."""
    development = github.pages(
        "/deployments?environment=development&ref=" + release["affected_sha"],
        maximum=2,
    )
    matched = False
    for candidate in development:
        try:
            verified = verified_record(
                github, candidate, "development", historical=True, require_telemetry=require_telemetry
            )
        except ReleaseEvidenceError:
            continue
        if (
            verified["affected_sha"] == release["affected_sha"]
            and verified["image_digest"] == release["image_digest"]
        ):
            matched = True
            break
    if not matched:
        raise ReleaseEvidenceError("production lacks matching development-verified pair")


