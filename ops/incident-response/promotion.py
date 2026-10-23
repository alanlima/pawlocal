"""Trusted machine merge/promotion. Never imports or executes candidate source."""

import argparse
import json
import os
import re
import time
import urllib.request
from pathlib import Path

from admission import (
    GITHUB,
    INCIDENT_PREFIX,
    GitHub,
    current_alert,
    deployed_release,
    readiness,
)
from candidate import digest
from deadline import arm
from job import context, download
from quota import Denied, integer, strict_json
from quota_gateway import NoRedirect
from settings import runtime_ready

CHECKS = {
    "Backend checks / Backend checks",
    "Frontend checks and HTTP-mode build / frontend",
}


class ReleaseClient(GitHub):
    """Additional reads only; writes remain separate exact-purpose brokers."""

    def request(self, method, path, data=None):
        allowed = method == "GET" and re.fullmatch(
            r"/(?:pulls/\d+|actions/runs(?:/\d+(?:/jobs)?)?|git/commits/[0-9a-f]{40}|environments/production(?:/deployment-branch-policies)?)(?:\?[A-Za-z0-9_=&%.-]+)?",
            path,
        )
        if not allowed:
            return super().request(method, path, data)
        return request(self.token, self.deadline, method, path, data)


def request(token, deadline, method, path, body=None, opener=None):
    if method != "GET":
        merge_allowed = (
            method == "PUT"
            and re.fullmatch(r"/pulls/[1-9][0-9]*/merge", path)
            and isinstance(body, dict)
            and set(body) == {"sha", "merge_method"}
            and body.get("merge_method") == "squash"
            and re.fullmatch(r"[0-9a-f]{40}", str(body.get("sha")))
        )
        dispatch_allowed = (
            method == "POST"
            and path == "/actions/workflows/deploy-production.yml/dispatches"
            and isinstance(body, dict)
            and set(body) == {"ref", "inputs", "return_run_details"}
            and body.get("ref") == "main"
            and body.get("return_run_details") is True
            and isinstance(body.get("inputs"), dict)
            and set(body["inputs"]) == {"release_commit", "backend_image"}
            and re.fullmatch(r"[0-9a-f]{40}", str(body["inputs"].get("release_commit")))
            and re.fullmatch(
                r"ghcr\.io/alanlima/pawlocal-api@sha256:[0-9a-f]{64}",
                str(body["inputs"].get("backend_image")),
            )
        )
        if not (merge_allowed or dispatch_allowed):
            raise Denied("non-allowlisted release mutation")
    if not token or time.time() >= deadline:
        raise Denied("promotion credential/deadline unavailable")
    value = urllib.request.Request(
        GITHUB + path,
        method=method,
        data=None if body is None else json.dumps(body, separators=(",", ":")).encode(),
        headers={
            "Authorization": "Bearer " + token,
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    with (opener or urllib.request.build_opener(NoRedirect)).open(
        value, timeout=min(15, deadline - time.time())
    ) as response:
        raw = response.read(2 * 1024 * 1024 + 1)
        if response.status not in {200, 201} or len(raw) > 2 * 1024 * 1024:
            raise Denied("promotion acknowledgement uncertain; no automatic redispatch")
        return strict_json(raw)


def publication():
    metadata, profile = context(followup=True)
    raw = download("oncall-publication-" + metadata["run_id"], {"publication.json"})[
        "publication.json"
    ]
    if digest(raw) != os.environ.get("PUBLICATION_SHA256"):
        raise Denied("publication artifact differs")
    value = strict_json(raw)
    if not isinstance(value, dict) or set(value) != {
        "schema",
        "run_id",
        "issue",
        "pr",
        "candidate_sha",
        "tree_sha",
        "base_sha",
        "branch",
        "admission_sha256",
        "profile_sha256",
        "published_at",
        "promotion_deadline",
    }:
        raise Denied("publication schema invalid")
    integer(value["pr"])
    integer(value["published_at"])
    integer(value["promotion_deadline"])
    if (
        value["schema"] != 1
        or value["run_id"] != metadata["run_id"]
        or value["issue"] != metadata["issue"]
        or value["base_sha"] != metadata["base_sha"]
        or value["admission_sha256"] != os.environ["ADMISSION_SHA256"]
        or value["profile_sha256"] != profile.digest
        or value["published_at"] > metadata["deadline"]
        or value["promotion_deadline"]
        != value["published_at"] + profile.promotion_seconds
        or value["promotion_deadline"] != int(os.environ["PROMOTION_DEADLINE"])
        or not value["published_at"] <= time.time() < value["promotion_deadline"]
        or not all(
            isinstance(value[key], str) and re.fullmatch(r"[0-9a-f]{40}", value[key])
            for key in ("candidate_sha", "tree_sha")
        )
        or value["branch"]
        != f"incident/{metadata['alert']['environment']}/{metadata['alert']['incident_key'][:16]}"
    ):
        raise Denied("publication provenance/deadline invalid")
    return metadata, profile, value


def valid_run(run, workflow, event, sha=None):
    return (
        isinstance(run, dict)
        and type(run.get("id")) is int
        and run.get("repository", {}).get("id") == 1423024931
        and run.get("head_repository", {}).get("id") == 1423024931
        and run.get("path") == ".github/workflows/" + workflow
        and run.get("event") == event
        and run.get("run_attempt") == 1
        and (sha is None or run.get("head_sha") == sha)
    )


def candidate_ci(client, value):
    listing = client.request(
        "GET",
        "/actions/runs?event=pull_request&head_sha="
        + value["candidate_sha"]
        + "&per_page=100",
    )
    if type(listing.get("total_count")) is not int or listing["total_count"] >= 100:
        raise Denied("candidate run inventory unknown")
    runs = [
        run
        for run in listing.get("workflow_runs", [])
        if valid_run(
            run, "fullstack-release.yml", "pull_request", value["candidate_sha"]
        )
        and any(pr.get("number") == value["pr"] for pr in run.get("pull_requests", []))
    ]
    if len(runs) > 1:
        raise Denied("multiple candidate attempts require escalation")
    if not runs or runs[0].get("status") != "completed":
        return False
    run = runs[0]
    if run.get("conclusion") != "success":
        raise Denied("candidate PR CI failed")
    jobs = client.request("GET", f"/actions/runs/{run['id']}/jobs?per_page=100")
    if type(jobs.get("total_count")) is not int or jobs["total_count"] >= 100:
        raise Denied("candidate job inventory unknown")
    for name in CHECKS:
        matches = [job for job in jobs.get("jobs", []) if job.get("name") == name]
        if (
            len(matches) != 1
            or any(
                matches[0].get(key) != expected
                for key, expected in {
                    "conclusion": "success",
                    "run_id": run["id"],
                    "run_attempt": 1,
                    "head_sha": value["candidate_sha"],
                }.items()
            )
            or not re.fullmatch(
                re.escape(GITHUB) + r"/check-runs/[1-9][0-9]*",
                matches[0].get("check_run_url", ""),
            )
        ):
            raise Denied("authentic candidate checks missing")
    return True


def check_pr(client, value):
    pr = client.request("GET", f"/pulls/{value['pr']}")
    if (
        pr.get("state") != "open"
        or pr.get("draft") is not False
        or pr.get("head", {}).get("sha") != value["candidate_sha"]
        or pr.get("head", {}).get("ref") != value["branch"]
        or pr.get("head", {}).get("repo", {}).get("id") != 1423024931
        or pr.get("base", {}).get("ref") != "main"
        or pr.get("base", {}).get("sha") != value["base_sha"]
        or pr.get("base", {}).get("repo", {}).get("id") != 1423024931
        or pr.get("merged") is not False
    ):
        raise Denied("exact published PR changed")
    if (
        client.request("GET", "/git/ref/heads/main").get("object", {}).get("sha")
        != value["base_sha"]
    ):
        raise Denied("main moved; no automatic rebase or second candidate")
    readiness(client)


def pause(deadline):
    remaining = deadline - time.time()
    if remaining <= 0:
        raise Denied(
            "release phase deadline; cease new mutations and reconcile in-flight deployment"
        )
    time.sleep(min(15, remaining))


def merge(client, token, value, metadata):
    while not candidate_ci(client, value):
        check_pr(client, value)
        pause(client.deadline)
    check_pr(client, value)
    check_incident(client, metadata)
    # No generic App request path: only this PR, candidate SHA, squash method.
    result = request(
        token,
        client.deadline,
        "PUT",
        f"/pulls/{value['pr']}/merge",
        {"sha": value["candidate_sha"], "merge_method": "squash"},
    )
    sha = result.get("sha")
    if (
        result.get("merged") is not True
        or not isinstance(sha, str)
        or not re.fullmatch(r"[0-9a-f]{40}", sha)
    ):
        raise Denied("merge result uncertain; no retry")
    commit = client.request("GET", "/git/commits/" + sha)
    parents = commit.get("parents", [])
    if (
        commit.get("tree", {}).get("sha") != value["tree_sha"]
        or not isinstance(parents, list)
        or len(parents) != 1
        or parents[0].get("sha") != value["base_sha"]
    ):
        raise Denied("merged release differs from reviewed candidate tree/base")
    return sha


def check_incident(client, metadata):
    issue = client.request("GET", f"/issues/{metadata['issue']}")
    if (
        issue.get("state") != "open"
        or issue.get("user", {}).get("login") != "github-actions[bot]"
        or INCIDENT_PREFIX + metadata["alert"]["incident_key"] + " -->"
        not in issue.get("body", "")
    ):
        raise Denied("incident claim closed or changed")
    if not current_alert(
        os.environ.get("GRAFANA_STACK_URL", ""),
        os.environ.get("PAWLOCAL_GRAFANA_QUERY_TOKEN", ""),
        metadata["alert"],
        client.deadline,
    ):
        raise Denied("original incident resolved before merge")
    actual = deployed_release(client, metadata["alert"]["environment"])
    if any(
        actual[key] != metadata[key]
        for key in ("affected_sha", "image_digest", "deployment_id", "deployment_run")
    ):
        raise Denied("affected deployment changed before merge")


def development_run(client, sha):
    listing = client.request(
        "GET", "/actions/runs?event=push&head_sha=" + sha + "&per_page=100"
    )
    if type(listing.get("total_count")) is not int or listing["total_count"] >= 100:
        raise Denied("development release inventory unknown")
    runs = [
        run
        for run in listing.get("workflow_runs", [])
        if valid_run(run, "fullstack-release.yml", "push", sha)
        and run.get("head_branch") == "main"
    ]
    if len(runs) > 1:
        raise Denied("multiple development release attempts require escalation")
    if not runs or runs[0].get("status") != "completed":
        return None
    if runs[0].get("conclusion") != "success":
        raise Denied("development release failed")
    return runs[0]["id"]


def promote(client, sha):
    runtime_ready(client)
    while True:
        run_id = development_run(client, sha)
        if run_id is not None:
            development = deployed_release(client, "development")
            if (
                development["affected_sha"] != sha
                or development["deployment_run"] != run_id
            ):
                raise Denied(
                    "development release readback differs from the actual push run"
                )
            break
        pause(client.deadline)
    runtime_ready(client)
    if client.request("GET", "/git/ref/heads/main").get("object", {}).get("sha") != sha:
        raise Denied("main moved before exact verified production dispatch")
    image = "ghcr.io/alanlima/pawlocal-api@" + development["image_digest"]
    dispatched = request(
        client.token,
        client.deadline,
        "POST",
        "/actions/workflows/deploy-production.yml/dispatches",
        {
            "ref": "main",
            "inputs": {"release_commit": sha, "backend_image": image},
            "return_run_details": True,
        },
    )
    run_id = dispatched.get("workflow_run_id")
    if (
        type(run_id) is not int
        or dispatched.get("run_url") != GITHUB + f"/actions/runs/{run_id}"
        or dispatched.get("html_url")
        != f"https://github.com/alanlima/pawlocal/actions/runs/{run_id}"
    ):
        raise Denied("production dispatch uncertain; never automatically redeliver")
    while True:
        run = client.request("GET", f"/actions/runs/{run_id}")
        if not valid_run(run, "deploy-production.yml", "workflow_dispatch", sha):
            raise Denied("production run provenance differs")
        if run.get("status") == "completed":
            if run.get("conclusion") != "success":
                raise Denied(
                    "production release failed; no automatic infrastructure rollback"
                )
            production = deployed_release(client, "production")
            if (
                production["affected_sha"] != sha
                or production["image_digest"] != development["image_digest"]
                or production["deployment_run"] != run_id
            ):
                raise Denied(
                    "production readback differs from exact development-verified pair"
                )
            return production
        pause(client.deadline)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=["merge", "promote"])
    phase = parser.parse_args().phase
    arm(os.environ["PROMOTION_DEADLINE"], maximum=3600)
    metadata, _, value = publication()
    client = ReleaseClient(os.environ["GH_TOKEN"], value["promotion_deadline"])
    if os.environ.get("PAWLOCAL_ONCALL_ENABLED") != "true":
        raise Denied("incident automation disabled")
    if (
        metadata["alert"]["environment"] == "production"
        and os.environ.get("PAWLOCAL_PRODUCTION_TELEMETRY_READ_APPROVED") != "true"
    ):
        raise Denied("production telemetry-read authority revoked")
    root = Path(os.environ["RUNNER_TEMP"])
    if phase == "merge":
        token = root / "oncall-publisher-token.json"
        if (
            token.is_symlink()
            or token.stat().st_mode & 0o077
            or token.stat().st_uid != os.getuid()
        ):
            raise Denied("trusted merge credential handoff invalid")
        sha = merge(client, strict_json(token.read_bytes())["token"], value, metadata)
        with open(os.environ["GITHUB_OUTPUT"], "a") as stream:
            stream.write("merged_sha=" + sha + "\n")
    else:
        sha = os.environ.get("MERGED_SHA", "")
        if not re.fullmatch(r"[0-9a-f]{40}", sha):
            raise Denied("trusted merge output required")
        production = promote(client, sha)
        if current_alert(
            os.environ.get("GRAFANA_STACK_URL", ""),
            os.environ.get("PAWLOCAL_GRAFANA_QUERY_TOKEN", ""),
            metadata["alert"],
            client.deadline,
        ):
            raise Denied("release succeeded but original incident remains active")
        print(
            "Production identity and original alert recovery verified: "
            + production["affected_sha"]
        )


if __name__ == "__main__":
    main()
