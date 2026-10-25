"""Resolve and bind a manual application rollback using canonical release evidence."""

import argparse
import datetime as dt
import html
import json
import os
from pathlib import Path
import re
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
from release_evidence import GitHub, ReleaseEvidenceError as Denied, deployed_release, matching_development, verified_record

PREVIOUS = "Previous verified production release"
SPECIFIC = "Specific production deployment"


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"[1-9][0-9]{0,15}", value) or int(value) > 9007199254740991:
        raise Denied("A valid numeric production deployment ID is required")
    return int(value)


def reason_text(value):
    if not isinstance(value, str) or not 1 <= len(value.strip()) <= 500 or any(ord(c) < 32 for c in value):
        raise Denied("Reason must be a single line of 1 to 500 characters")
    return value.strip()


def date(record):
    try:
        value = dt.datetime.fromisoformat(record["created_at"].replace("Z", "+00:00"))
        if value.tzinfo is None:
            raise ValueError()
        return value
    except (KeyError, ValueError, TypeError, AttributeError) as error:
        raise Denied("Deployment history has an uncertain timestamp") from error


def resolve(github, target, deployment_id, reason):
    reason = reason_text(reason)
    if target not in {PREVIOUS, SPECIFIC}:
        raise Denied("Unknown rollback selection")
    if target == PREVIOUS and deployment_id:
        raise Denied("Deployment ID must be empty for previous-release selection")
    requested = identifier(deployment_id) if target == SPECIFIC else None
    # The current release must be trusted; never skip an uncertain latest record.
    current = deployed_release(github, "production", require_telemetry=False)
    history = github.pages("/deployments?environment=production", maximum=10)
    if not history or len({record.get("id") for record in history}) != len(history):
        raise Denied("Missing or ambiguous production history")
    history.sort(key=lambda record: (date(record), identifier(str(record.get("id")))), reverse=True)
    if history[0]["id"] != current["deployment_id"]:
        raise Denied("Production changed during selection; run again")
    pair = current["affected_sha"], current["image_digest"]
    for record in history[1:]:
        if requested is not None and record["id"] != requested:
            continue
        try:
            selected = verified_record(github, record, "production", historical=True, require_telemetry=False)
            matching_development(github, selected, require_telemetry=False)
        except Denied:
            if requested is not None:
                raise
            continue
        if (selected["affected_sha"], selected["image_digest"]) == pair:
            if requested is not None:
                raise Denied("Selected deployment is the current release")
            continue
        return {
            "release_commit": selected["affected_sha"],
            "backend_image": "ghcr.io/alanlima/pawlocal-api@" + selected["image_digest"],
            "rollback_from_deployment_id": str(current["deployment_id"]),
            "rollback_to_deployment_id": str(selected["deployment_id"]),
            "reason": reason,
            "current_commit": current["affected_sha"],
            "current_image_digest": current["image_digest"],
            "current_created_at": history[0]["created_at"],
            "current_run_id": str(current["deployment_run"]),
            "target_created_at": record["created_at"],
            "target_run_id": str(selected["deployment_run"]),
        }
    raise Denied("No eligible distinct historical production deployment found within bounded history")


def validate(github, source, target, reason, commit, image):
    """Called while the canonical production lifecycle lock is held, before mutation."""
    source, target = identifier(source), identifier(target)
    reason_text(reason)
    current = deployed_release(github, "production", require_telemetry=False)
    if current["deployment_id"] != source:
        raise Denied("Production changed since selection; start a new rollback")
    records = github.pages("/deployments?environment=production", maximum=10)
    selected = [record for record in records if record.get("id") == target]
    sources = [record for record in records if record.get("id") == source]
    if len(selected) != 1 or len(sources) != 1 or (date(selected[0]), target) >= (date(sources[0]), source):
        raise Denied("Rollback target must be an unambiguous historical production deployment")
    release = verified_record(github, selected[0], "production", historical=True, require_telemetry=False)
    matching_development(github, release, require_telemetry=False)
    if release["affected_sha"] != commit or "ghcr.io/alanlima/pawlocal-api@" + release["image_digest"] != image:
        raise Denied("Resolved rollback release pair changed")
    if (release["affected_sha"], release["image_digest"]) == (current["affected_sha"], current["image_digest"]):
        raise Denied("Rollback target must differ from current release")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["resolve", "validate"])
    args = parser.parse_args()
    if os.environ.get("GITHUB_REF") != "refs/heads/main" or os.environ.get("GITHUB_REPOSITORY") != "alanlima/pawlocal":
        raise Denied("Rollback requires the trusted repository main branch")
    github = GitHub(os.environ.get("GH_TOKEN"), time.time() + 180)
    reason = os.environ.get("ROLLBACK_REASON", "")
    if args.mode == "validate":
        validate(github, os.environ.get("ROLLBACK_FROM", ""), os.environ.get("ROLLBACK_TO", ""), reason,
                 os.environ.get("RELEASE_COMMIT", ""), os.environ.get("BACKEND_IMAGE", ""))
        return
    result = resolve(github, os.environ.get("ROLLBACK_TARGET", ""), os.environ.get("ROLLBACK_DEPLOYMENT_ID", ""), reason)
    with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as stream:
        for key, value in result.items():
            stream.write(f"{key}={value}\n")
    with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as stream:
        stream.write(summary(result))
        stream.write(f"[Original target verification](https://github.com/alanlima/pawlocal/actions/runs/{result['target_run_id']})\n\n")
        stream.write("Verified means the recorded checks passed; it does not prove every journey healthy. "
                     "Frontend is rebuilt from the selected source using current tools/configuration. "
                     "Database/schema changes are not reversed.\n")


def summary(result):
    """Lead with operational identities; escape user text for safe Markdown/HTML."""
    value = "## Production rollback selection\n\n| | Deployment | Date | Verification run |\n|---|---|---|---|\n"
    for label, identity, prefix in (("From", "rollback_from_deployment_id", "current"), ("To", "rollback_to_deployment_id", "target")):
        run = result[prefix + "_run_id"]
        value += f"| {label} | {result[identity]} | {result[prefix + '_created_at']} | [Run {run}](https://github.com/alanlima/pawlocal/actions/runs/{run}) |\n"
    value += "\nReason: <code>" + html.escape(result["reason"]).replace("`", "&#96;") + "</code>\n\n"
    # Escape backticks in audit JSON so operator input cannot close the code fence.
    value += "<details><summary>Resolved release identifiers</summary>\n\n```json\n"
    value += json.dumps(result, indent=2).replace("`", "\\u0060").replace("<", "\\u003c").replace(">", "\\u003e") + "\n```\n\n</details>\n\n"
    return value


if __name__ == "__main__":
    main()
