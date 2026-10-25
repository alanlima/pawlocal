"""Trusted deterministic GitHub broker. Never executes candidate code."""

import base64
import datetime as dt
import hashlib
import json
import os
import re
import time
import urllib.parse
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
from candidate import ALLOWED, digest, load
from control import LiveControl
from deadline import arm
from job import context, download, remaining
from quota import Denied, strict_json
from enforcement import enabled, skipped, evidence
from quota_gateway import NoRedirect


class Broker:
    def __init__(self, token, metadata, candidate_sha, opener=None, control=None):
        self.token = token
        self.metadata = metadata
        self.candidate_sha = candidate_sha
        source_environment = metadata.get(
            "source_environment", metadata["alert"]["environment"]
        )
        self.branch = (
            f"incident/{source_environment}/{metadata['alert']['incident_key'][:16]}"
        )
        self.opener = opener or urllib.request.build_opener(NoRedirect)
        self.control = control

    def approved(self, method, path, body):
        if method == "GET":
            return bool(re.fullmatch(r"/git/commits/[0-9a-f]{40}", path))
        if method != "POST" or not isinstance(body, dict):
            return False
        if path == "/git/blobs":
            return (
                set(body) == {"content", "encoding"}
                and body["encoding"] == "base64"
                and isinstance(body["content"], str)
                and len(body["content"]) <= 1024 * 1024
            )
        if path == "/git/trees":
            return (
                set(body) == {"base_tree", "tree"}
                and re.fullmatch(r"[0-9a-f]{40}", str(body["base_tree"]))
                and isinstance(body["tree"], list)
                and (not enabled() or 1 <= len(body["tree"]) <= 20)
                and all(
                    set(item) == {"path", "mode", "type", "sha"}
                    and item["path"] in ALLOWED
                    and item["mode"] == "100644"
                    and item["type"] == "blob"
                    and (
                        not enabled()
                        and item["sha"] is None
                        or re.fullmatch(r"[0-9a-f]{40}", str(item["sha"]))
                    )
                    for item in body["tree"]
                )
            )
        if path == "/git/commits":
            return (
                set(body) == {"message", "tree", "parents", "author", "committer"}
                and body["parents"] == [self.metadata["base_sha"]]
                and re.fullmatch(r"[0-9a-f]{40}", str(body["tree"]))
                and body["author"] == body["committer"]
            )
        if path == "/git/refs":
            return body == {
                "ref": "refs/heads/" + self.branch,
                "sha": self.candidate_sha,
            }
        if path == "/pulls":
            return (
                set(body) == {"head", "base", "title", "body", "draft"}
                and body["head"] == self.branch
                and body["base"] == "main"
                and body["draft"] is False
                and isinstance(body["title"], str)
                and len(body["title"]) < 160
                and isinstance(body["body"], str)
                and len(body["body"]) < 16384
            )
        return False

    def request(self, method, path, body=None):
        if enabled() and not self.approved(method, path, body):
            raise Denied("publisher operation denied")
        if method != "GET":
            if self.control is None:
                raise Denied("live publication control required")
            self.control()
        timeout = min(15, remaining(self.metadata))
        request = urllib.request.Request(
            GITHUB + path,
            method=method,
            data=None if body is None else json.dumps(body).encode(),
            headers={
                "Authorization": "Bearer " + self.token,
                "Accept": "application/vnd.github+json",
                "Content-Type": "application/json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        with self.opener.open(request, timeout=timeout) as response:
            raw = response.read(1024 * 1024 + 1)
            if response.status not in {200, 201} or len(raw) > 1024 * 1024:
                raise Denied("publisher acknowledgement uncertain")
            return strict_json(raw)


def authentic_jobs(github, run_id):
    if not enabled():
        skipped("checks")
        return
    run = github.request("GET", f"/actions/runs/{run_id}")
    if (
        run.get("id") != int(run_id)
        or run.get("repository", {}).get("id") != 1423024931
        or run.get("head_repository", {}).get("id") != 1423024931
        or run.get("path") != ".github/workflows/incident-responder.yml"
        or run.get("head_sha") != os.environ.get("GITHUB_SHA")
        or run.get("head_branch") != "main"
        or run.get("event") != "workflow_dispatch"
        or run.get("run_attempt") != 1
    ):
        raise Denied("incident workflow run provenance differs")
    value = github.request("GET", f"/actions/runs/{run_id}/jobs?per_page=100")
    jobs = value.get("jobs", [])
    if value.get("total_count", 100) >= 100 or not isinstance(jobs, list):
        raise Denied("job provenance unknown")
    for name in (
        "Trusted preflight",
        "Fix search/detail",
        "Validate candidate",
        "Fresh review",
    ):
        selected = [job for job in jobs if job.get("name") == name]
        if enabled() and (
            len(selected) != 1
            or selected[0].get("conclusion") != "success"
            or selected[0].get("run_attempt") != 1
            or selected[0].get("run_id") != int(run_id)
            or selected[0].get("head_sha") != run["head_sha"]
        ):
            raise Denied("authentic fresh checks/review did not succeed")


def can_publish(github, metadata):
    if not enabled():
        skipped("publication")
        return
    if os.environ.get("PAWLOCAL_ONCALL_ENABLED") != "true":
        raise Denied("emergency admission disabled")
    environment = metadata["alert"]["environment"]
    LiveControl(
        lambda path: github.request("GET", path), metadata, metadata["deadline"]
    ).check()
    if (
        environment == "production"
        and os.environ.get("PAWLOCAL_PRODUCTION_TELEMETRY_READ_APPROVED") != "true"
    ):
        raise Denied("production read approval revoked")
    issue = github.request("GET", f"/issues/{metadata['issue']}")
    marker = INCIDENT_PREFIX + metadata["alert"]["incident_key"] + " -->"
    if (
        issue.get("state") != "open"
        or issue.get("user", {}).get("login") != "github-actions[bot]"
        or marker not in issue.get("body", "")
    ):
        raise Denied("incident closed, changed or unsupported")
    if (
        github.request("GET", "/git/ref/heads/main").get("object", {}).get("sha")
        != metadata["base_sha"]
    ):
        raise Denied("main moved since authentic candidate checks")
    readiness(github)
    if not current_alert(
        os.environ.get("GRAFANA_STACK_URL", ""),
        os.environ.get("PAWLOCAL_GRAFANA_QUERY_TOKEN", ""),
        metadata["alert"],
        metadata["deadline"],
    ):
        raise Denied("incident resolved before publication")
    release = deployed_release(github, environment)
    if any(
        release[key] != metadata[key]
        for key in ("affected_sha", "image_digest", "deployment_id", "deployment_run")
    ):
        raise Denied("actual deployed release changed")


def main():
    arm(os.environ["INCIDENT_DEADLINE"])
    metadata, profile = context()
    github = GitHub(os.environ["GH_TOKEN"], metadata["deadline"])
    outcome = [
        os.environ.get(key)
        for key in ("FIXER_RESULT", "CHECKS_RESULT", "REVIEWER_RESULT")
    ]
    if enabled() and (
        outcome != ["success"] * 3 or os.environ.get("CANDIDATE_ELIGIBLE") != "true"
    ):
        state = (
            "RELEASE_LAG"
            if os.environ.get("CHECKS_RESULT") == "success"
            and os.environ.get("CANDIDATE_ELIGIBLE") == "false"
            else "ESCALATED"
        )
        github.request(
            "POST",
            f"/issues/{metadata['issue']}/comments",
            {
                "body": state
                + ": this single attempt did not qualify for publication. Inspect linked workflow/check evidence. Its full monthly reservation remains consumed; no automatic retries or refunds."
            },
        )
        return
    authentic_jobs(github, metadata["run_id"])
    candidate = download("oncall-candidate-" + metadata["run_id"], {"candidate.json"})[
        "candidate.json"
    ]
    checks = download("oncall-checks-" + metadata["run_id"], {"checks.json"})[
        "checks.json"
    ]
    review = download("oncall-review-" + metadata["run_id"], {"review.json"})[
        "review.json"
    ]
    if enabled() and (
        any(
            digest(raw) != os.environ.get(key)
            for raw, key in (
                (candidate, "CANDIDATE_SHA256"),
                (checks, "CHECKS_SHA256"),
                (review, "REVIEW_SHA256"),
            )
        )
    ):
        raise Denied("artifact provenance differs")
    files = load(candidate, metadata)
    checked, reviewed = strict_json(checks), strict_json(review)
    pinned = os.environ["PINNED_CANDIDATE_SHA"]
    if enabled() and (
        checked.get("candidate_sha") != pinned
        or checked.get("base_sha") != metadata["base_sha"]
        or checked.get("patch_sha256") != digest(candidate)
        or checked.get("run_id") != metadata["run_id"]
        or checked.get("profile") != profile.digest
        or checked.get("admission_sha256") != os.environ["ADMISSION_SHA256"]
        or not all(
            checked.get(key) is True
            for key in ("affected_reproduced", "main_reproduced", "candidate_passed")
        )
    ):
        raise Denied("checks do not bind identical candidate")
    expected_review = {
        "run_id": metadata["run_id"],
        "candidate_sha": pinned,
        "candidate_sha256": digest(candidate),
        "checks_sha256": digest(checks),
        "verdict": "pass",
        "findings": [],
    }
    if enabled() and (reviewed != expected_review):
        raise Denied("fresh review provenance differs")
    can_publish(github, metadata)
    token_path = Path(os.environ["RUNNER_TEMP"]) / "oncall-publisher-token.json"
    if (
        token_path.is_symlink()
        or token_path.stat().st_mode & 0o077
        or token_path.stat().st_uid != os.getuid()
    ):
        raise Denied("private publisher token handoff invalid")
    control = LiveControl(
        lambda path: github.request("GET", path), metadata, metadata["deadline"]
    ).check
    broker = Broker(
        strict_json(token_path.read_bytes())["token"], metadata, pinned, control=control
    )
    base = broker.request("GET", "/git/commits/" + metadata["base_sha"])
    tree = []
    for name, raw in sorted(files.items()):
        if raw is None and not enabled():
            tree.append({"path": name, "mode": "100644", "type": "blob", "sha": None})
            continue
        sha = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
        blob = broker.request(
            "POST",
            "/git/blobs",
            {"content": base64.b64encode(raw).decode(), "encoding": "base64"},
        )
        if enabled() and (blob.get("sha") != sha):
            raise Denied("published blob differs")
        tree.append({"path": name, "mode": "100644", "type": "blob", "sha": sha})
    created_tree = broker.request(
        "POST", "/git/trees", {"base_tree": base["tree"]["sha"], "tree": tree}
    )
    if enabled() and (created_tree.get("sha") != checked["tree_sha"]):
        raise Denied("published tree differs")
    identity = {
        "name": "PawLocal Incident Responder",
        "email": "oncall@users.noreply.github.com",
        "date": dt.datetime.fromtimestamp(checked["timestamp"], dt.UTC).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        ),
    }
    commit = broker.request(
        "POST",
        "/git/commits",
        {
            "message": checked["message"],
            "tree": checked["tree_sha"],
            "parents": [metadata["base_sha"]],
            "author": identity,
            "committer": identity,
        },
    )
    if enabled() and (commit.get("sha") != pinned):
        raise Denied("published commit differs from reviewed candidate")
    can_publish(github, metadata)
    broker.request(
        "POST", "/git/refs", {"ref": "refs/heads/" + broker.branch, "sha": pinned}
    )
    body = f"Addresses incident #{metadata['issue']} in the search/detail journey. The identical regression reproduced on affected `{metadata['affected_sha']}` and current main `{metadata['base_sha']}`; candidate `{pinned}` passed trusted checks and fresh machine review.\n\nTrusted automation requires authentic candidate PR CI before squash merge, verifies the resulting development release, then promotes that exact verified release to production and checks recovery.\n\nWorkflow evidence: https://github.com/alanlima/pawlocal/actions/runs/{metadata['run_id']}\n\nCandidate artifact SHA256: `{digest(candidate)}`.\n\nRelated: #{metadata['issue']}, #42."
    if not enabled():
        body = (
            f"Addresses incident #{metadata['issue']}. Candidate `{pinned}` was constructed from actual source bytes. "
            "Incident enforcement is disabled: regression, review/CI, publication provenance and recovery policy are not required. "
            "Skipped checks are not passes; external GitHub required checks still apply. "
            f"\n\nWorkflow evidence: https://github.com/alanlima/pawlocal/actions/runs/{metadata['run_id']}"
            f"\n\nCandidate artifact SHA256: `{digest(candidate)}`. Related: #{metadata['issue']}, #42."
        )
    can_publish(github, metadata)
    published_at = int(time.time())
    result = broker.request(
        "POST",
        "/pulls",
        {
            "head": broker.branch,
            "base": "main",
            "title": f"fix: search/detail incident {metadata['alert']['incident_key'][:12]}",
            "body": body,
            "draft": False,
        },
    )
    number = result.get("number")
    if (
        type(number) is not int
        or result.get("head", {}).get("sha") != pinned
        or result.get("base", {}).get("ref") != "main"
        or result.get("state") != "open"
    ):
        raise Denied("PR acknowledgement uncertain; inspect owner-visible branch/run")
    control()
    github.request(
        "POST",
        f"/issues/{metadata['issue']}/comments",
        {
            "body": f"PR_OPEN: https://github.com/alanlima/pawlocal/pull/{number}. Candidate `{pinned}` awaits authentic candidate PR CI, followed by trusted automated squash merge and verified release promotion. Full monthly reservation remains consumed."
        },
    )
    publication = {
        **({"enforcement": evidence()} if not enabled() else {}),
        "schema": 1,
        "run_id": metadata["run_id"],
        "issue": metadata["issue"],
        "pr": number,
        "candidate_sha": pinned,
        "tree_sha": checked["tree_sha"],
        "base_sha": metadata["base_sha"],
        "branch": broker.branch,
        "admission_sha256": os.environ["ADMISSION_SHA256"],
        "profile_sha256": profile.digest,
        "published_at": published_at,
        "promotion_deadline": published_at + profile.promotion_seconds,
    }
    raw = json.dumps(publication, sort_keys=True, separators=(",", ":")).encode()
    output = Path(os.environ["RUNNER_TEMP"]) / "oncall-publication"
    output.mkdir(mode=0o700)
    (output / "publication.json").write_bytes(raw)
    with open(os.environ["GITHUB_OUTPUT"], "a") as stream:
        stream.write(
            f"publication_sha256={digest(raw)}\npromotion_deadline={publication['promotion_deadline']}\n"
        )


if __name__ == "__main__":
    main()
