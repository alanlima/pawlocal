"""Trusted change authorization for protected main.

Never executes, imports or checks out candidate/PR content.
Validates incident provenance and allowlisted application paths for machine PRs,
or enforces protected human review for ordinary PRs.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import re
import sys
import time
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath

# Candidate path boundary enforcement
from candidate import MAX_FILES, is_allowed_path

DEFAULT_CONTEXT = "PawLocal change authorization"
CONTEXT = DEFAULT_CONTEXT
ALLOWED_STATUSES = {"success", "failure", "pending"}


class Denied(Exception):
    """Raised when change authorization fails closed."""


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class GitHubClient:
    """Bounded, authenticated GitHub REST client for change authorization."""

    def __init__(
        self,
        token: str,
        repository: str,
        context: str = DEFAULT_CONTEXT,
        deadline: float | None = None,
        opener=None,
    ):
        if not token:
            raise Denied("GitHub token required")
        if not repository or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
            raise Denied(f"Valid GitHub repository (owner/repo) required, got: {repository!r}")
        self.token = token
        self.repository = repository
        self.context = context
        self.api_base = f"https://api.github.com/repos/{repository}"
        self.deadline = deadline or (time.time() + 600)
        self.opener = opener or urllib.request.build_opener(NoRedirect)

    def request(self, method: str, path: str, data: dict | None = None) -> dict | list:
        if time.time() >= self.deadline:
            raise Denied("Operation deadline exceeded")

        url = self.api_base + path if path.startswith("/") else path
        raw_body = json.dumps(data, separators=(",", ":")).encode() if data is not None else None

        req = urllib.request.Request(
            url,
            data=raw_body,
            method=method,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "Content-Type": "application/json",
            },
        )

        with self.opener.open(req, timeout=min(15, max(1, self.deadline - time.time()))) as resp:
            if resp.status not in (200, 201):
                raise Denied(f"GitHub API returned unexpected status: {resp.status}")
            body = resp.read(2 * 1024 * 1024 + 1)
            if len(body) > 2 * 1024 * 1024:
                raise Denied("Response exceeded size bound")
            return json.loads(body.decode("utf-8"))

    def download_raw(self, path: str) -> bytes:
        if time.time() >= self.deadline:
            raise Denied("Operation deadline exceeded")

        url = self.api_base + path if path.startswith("/") else path
        req = urllib.request.Request(
            url,
            method="GET",
            headers={
                "Authorization": f"Bearer {self.token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )

        with self.opener.open(req, timeout=min(15, max(1, self.deadline - time.time()))) as resp:
            if resp.status != 200:
                raise Denied(f"Artifact download failed with status {resp.status}")
            body = resp.read(5 * 1024 * 1024 + 1)
            if len(body) > 5 * 1024 * 1024:
                raise Denied("Artifact download exceeded size bound")
            return body

    def get_pr(self, number: int) -> dict:
        return self.request("GET", f"/pulls/{number}")

    def get_pr_files(self, number: int) -> list[str]:
        raw_files = self.request("GET", f"/pulls/{number}/files?per_page=100")
        if not isinstance(raw_files, list):
            raise Denied("Invalid PR files response")
        return [f["filename"] for f in raw_files if isinstance(f, dict) and "filename" in f]

    def post_status(self, sha: str, state: str, description: str) -> dict:
        if not re.fullmatch(r"[0-9a-f]{40}", sha):
            raise Denied("Invalid commit SHA for status post")
        if state not in ALLOWED_STATUSES:
            raise Denied(f"Invalid status state: {state}")
        payload = {
            "state": state,
            "context": self.context,
            "description": description[:140],
        }
        return self.request("POST", f"/statuses/{sha}", payload)


def classify_pr(pr_data: dict, publisher_bot_logins: set[str] | list[str] | None = None) -> str:
    """Classifies a PR as 'incident' or 'ordinary'. Fails closed on invalid inputs."""
    if not isinstance(pr_data, dict):
        raise Denied("Invalid PR payload")

    if pr_data.get("draft") is True:
        raise Denied("Draft PRs are not eligible for change authorization")

    base = pr_data.get("base", {})
    if base.get("ref") != "main":
        raise Denied(f"Target branch must be main, got: {base.get('ref')}")

    user = pr_data.get("user", {})
    login = user.get("login", "")
    user_type = user.get("type", "")

    # Check if author matches the verified publisher bot login or naming pattern
    is_bot = user_type == "Bot" and (
        (publisher_bot_logins and login in publisher_bot_logins)
        or bool(re.fullmatch(r"[A-Za-z0-9_.-]+-publisher\[bot\]", login))
    )

    if is_bot:
        head_ref = pr_data.get("head", {}).get("ref", "")
        if head_ref.startswith("incident/"):
            return "incident"

    return "ordinary"


def extract_run_id(pr_body: str) -> int:
    if not isinstance(pr_body, str):
        raise Denied("PR body missing")
    match = re.search(r"actions/runs/([1-9][0-9]*)", pr_body)
    if not match:
        raise Denied("No workflow run evidence found in PR body")
    return int(match.group(1))


def download_publication_receipt(client: GitHubClient, run_id: int) -> dict:
    """Downloads and verifies the immutable publication artifact from the controller run."""
    run = client.request("GET", f"/actions/runs/{run_id}")
    run_repo = run.get("repository", {}) if isinstance(run, dict) else {}
    run_repo_name = run_repo.get("full_name") or run_repo.get("name")
    
    # Must match repository of the client
    if (
        not isinstance(run, dict)
        or run.get("path") != ".github/workflows/incident-responder.yml"
        or run.get("head_branch") != "main"
        or (run_repo_name and client.repository and run_repo_name != client.repository and not client.repository.endswith(f"/{run_repo_name}"))
        or run.get("event") != "workflow_dispatch"
    ):
        raise Denied("Untrusted incident controller workflow run")

    artifacts_resp = client.request("GET", f"/actions/runs/{run_id}/artifacts?per_page=100")
    if not isinstance(artifacts_resp, dict) or not isinstance(artifacts_resp.get("artifacts"), list):
        raise Denied("Unable to retrieve controller artifacts")

    target_name = f"oncall-publication-{run_id}"
    matched = [a for a in artifacts_resp["artifacts"] if a.get("name") == target_name]
    if not matched:
        raise Denied(f"Publication artifact {target_name} not found")

    artifact_id = matched[0].get("id")
    zip_bytes = client.download_raw(f"/actions/artifacts/{artifact_id}/zip")
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
        if "publication.json" not in z.namelist():
            raise Denied("publication.json missing in publication artifact")
        raw = z.read("publication.json")

    receipt = json.loads(raw.decode("utf-8"))
    return receipt


def verify_incident_candidate(
    client: GitHubClient,
    pr_number: int,
    publication_receipt: dict | None = None,
) -> dict:
    """Verifies that an incident candidate meets all safety constraints and allowlists."""
    pr = client.get_pr(pr_number)
    if pr.get("state") != "open" or pr.get("draft") is True:
        raise Denied("PR is not open or is draft")

    head_sha = pr.get("head", {}).get("sha", "")
    base_sha = pr.get("base", {}).get("sha", "")
    head_ref = pr.get("head", {}).get("ref", "")

    # Retrieve authentic publication artifact if not passed directly
    if publication_receipt is None:
        run_id = extract_run_id(pr.get("body", ""))
        publication_receipt = download_publication_receipt(client, run_id)

    # 1. Validate publication receipt provenance
    if (
        publication_receipt.get("schema") != 1
        or publication_receipt.get("pr") != pr_number
        or publication_receipt.get("candidate_sha") != head_sha
        or publication_receipt.get("base_sha") != base_sha
        or publication_receipt.get("branch") != head_ref
    ):
        raise Denied("Publication receipt does not match current PR head/base/branch")

    deadline = publication_receipt.get("promotion_deadline", 0)
    if time.time() >= deadline:
        raise Denied("Incident candidate promotion deadline expired")

    # 2. Check candidate changed paths against application allowlist
    changed_files = client.get_pr_files(pr_number)
    if not changed_files:
        raise Denied("Candidate PR contains no changed files")
    if len(changed_files) > MAX_FILES:
        raise Denied(f"Candidate PR touches {len(changed_files)} files, exceeds maximum {MAX_FILES}")

    for file_path in changed_files:
        if not is_allowed_path(file_path):
            raise Denied(f"Candidate file outside allowed application scope: {file_path}")

    return {
        "pr_number": pr_number,
        "head_sha": head_sha,
        "base_sha": base_sha,
        "authorized": True,
        "route": "incident",
    }


def verify_ordinary_approval(
    client: GitHubClient,
    pr_number: int,
    expected_head_sha: str,
    expected_base_sha: str,
) -> dict:
    """Verifies that an ordinary PR has not mutated after human approval."""
    pr = client.get_pr(pr_number)
    if pr.get("state") != "open" or pr.get("draft") is True:
        raise Denied("Ordinary PR is not open or is draft")

    current_head = pr.get("head", {}).get("sha", "")
    current_base = pr.get("base", {}).get("sha", "")

    if current_head != expected_head_sha:
        raise Denied(f"PR head changed after approval: expected {expected_head_sha}, got {current_head}")
    if current_base != expected_base_sha:
        raise Denied(f"PR base changed after approval: expected {expected_base_sha}, got {current_base}")

    return {
        "pr_number": pr_number,
        "head_sha": current_head,
        "base_sha": current_base,
        "authorized": True,
        "route": "ordinary",
    }


def main():
    parser = argparse.ArgumentParser(description="Change authorization")
    parser.add_argument("--mode", choices=["classify", "incident", "ordinary"], required=True)
    parser.add_argument("--repository", default=os.environ.get("GITHUB_REPOSITORY", ""), help="Target GitHub repository (owner/repo)")
    parser.add_argument("--context", default=os.environ.get("CHANGE_AUTHORIZATION_CONTEXT", DEFAULT_CONTEXT), help="Status check context name")
    parser.add_argument("--publisher-bot", default=os.environ.get("PUBLISHER_BOT_LOGIN", ""), help="Expected publisher bot login")
    args = parser.parse_args()

    repo = args.repository or os.environ.get("GITHUB_REPOSITORY", "")
    if not repo:
        raise Denied("Repository parameter or GITHUB_REPOSITORY environment variable required")

    publisher_bots = {args.publisher_bot} if args.publisher_bot else None

    if args.mode == "classify":
        event_path = os.environ.get("GITHUB_EVENT_PATH") or os.environ.get("EVENT_PATH")
        if not event_path:
            raise Denied("Missing GITHUB_EVENT_PATH")
        with open(event_path, "r", encoding="utf-8") as f:
            event = json.load(f)
        pr = event.get("pull_request", {})
        route = classify_pr(pr, publisher_bot_logins=publisher_bots)
        pr_number = pr.get("number")
        head_sha = pr.get("head", {}).get("sha", "")
        base_sha = pr.get("base", {}).get("sha", "")
        output_file = os.environ.get("GITHUB_OUTPUT")
        if output_file:
            with open(output_file, "a", encoding="utf-8") as f:
                f.write(f"route={route}\n")
                f.write(f"pr_number={pr_number}\n")
                f.write(f"head_sha={head_sha}\n")
                f.write(f"base_sha={base_sha}\n")
        print(f"Classified PR #{pr_number} as route: {route}")
        return

    runner_temp = os.environ.get("RUNNER_TEMP", "/tmp")
    token_file = Path(runner_temp) / "oncall-status-token.json"
    if not token_file.exists():
        raise Denied(f"Status token missing at {token_file}")
    token_data = json.loads(token_file.read_text(encoding="utf-8"))
    client = GitHubClient(
        token=token_data["token"],
        repository=repo,
        context=args.context,
    )

    pr_number = int(os.environ["PR_NUMBER"])
    head_sha = os.environ["HEAD_SHA"]
    base_sha = os.environ["BASE_SHA"]

    if args.mode == "incident":
        try:
            verify_incident_candidate(client, pr_number)
            client.post_status(head_sha, "success", "Authenticated incident candidate authorized")
            print("Incident change authorization status posted successfully.")
        except Denied as e:
            client.post_status(head_sha, "failure", f"Incident authorization denied: {e}")
            print(f"Incident authorization denied: {e}", file=sys.stderr)
            sys.exit(1)

    elif args.mode == "ordinary":
        try:
            verify_ordinary_approval(client, pr_number, head_sha, base_sha)
            client.post_status(head_sha, "success", "Protected human approval verified")
            print("Ordinary change authorization status posted successfully.")
        except Denied as e:
            client.post_status(head_sha, "failure", f"Ordinary approval denied: {e}")
            print(f"Ordinary approval denied: {e}", file=sys.stderr)
            sys.exit(1)


if __name__ == "__main__":
    main()
