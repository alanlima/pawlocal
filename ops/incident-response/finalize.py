"""Bounded always-finalizer. Retain uncertain leases; never retry remediation."""

import os
import re
import time
from pathlib import Path

import receipts
from control import INCIDENT, LiveControl
from deadline import arm
from job import context
from promotion import ReleaseClient, deployed_release, publication, verified_merge
from quota import Denied
from enforcement import enabled, skipped, operational_deadline


def summary(state, reason):
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        Path(path).write_text(
            f"## Incident outcome: {state}\n\n{reason}\n\n"
            + (
                "The generation remains consumed. "
                if enabled()
                else "Incident enforcement is disabled; prior attempt and reservation records remain audit history. Generation/deduplication policy is not enforced. "
            )
            + "Any recorded or uncertain monthly reservation remains consumed. No automatic retry, refund, rollback or cancellation of an in-flight Terraform apply is authorized.\n"
        )


def complete(client, metadata, profile, published):
    payload = receipts.read(
        "production", os.environ.get("PRODUCTION_SHA256"), metadata, published
    )
    if not enabled():
        skipped("receipts")
        release = payload.get("release", {})
        if (
            not isinstance(release, dict)
            or type(release.get("deployment_run")) is not int
            or not re.fullmatch(r"[0-9a-f]{40}", str(payload.get("merged_sha", "")))
        ):
            raise Denied("usable completed release identifiers missing")
        return payload.get("merged_sha"), release.get("deployment_run")
    sha = verified_merge(client, metadata, published)
    proof = payload.get("recovery", {})
    release = payload.get("release")
    development = receipts.read(
        "development", os.environ.get("DEVELOPMENT_SHA256"), metadata, published
    )
    if (
        payload.get("merged_sha") != sha
        or payload.get("merge_sha256") != os.environ.get("MERGE_SHA256")
        or payload.get("development_sha256") != os.environ.get("DEVELOPMENT_SHA256")
        or not isinstance(release, dict)
        or release.get("affected_sha") != sha
        or development.get("merged_sha") != sha
        or development.get("merge_sha256") != os.environ.get("MERGE_SHA256")
        or development.get("release", {}).get("affected_sha") != sha
        or development.get("release", {}).get("image_digest")
        != release.get("image_digest")
        or deployed_release(client, "production") != release
    ):
        raise Denied("complete production recovery provenance missing")
    receipts.validate_recovery(proof, release, profile, "production", published)
    receipts.validate_recovery(
        development.get("recovery"),
        development.get("release"),
        profile,
        "development",
        published,
    )
    if proof["started_at"] < development["recovery"]["completed_at"]:
        raise Denied("recovery receipt phase order differs")
    return sha, release["deployment_run"]


def main():
    # A locally retained summary survives a deadline/alarm or API uncertainty.
    # After deadline/stop, do not issue a compensating cloud mutation.
    summary(
        "LEASE_UNCERTAIN",
        "Trusted finalization has not yet established a completed outcome. Inspect this run and linked deployment evidence.",
    )
    raw_deadline = os.environ.get("PROMOTION_DEADLINE") or os.environ.get(
        "INCIDENT_DEADLINE", "0"
    )
    try:
        deadline = int(raw_deadline)
        if not enabled():
            deadline = operational_deadline()
        if enabled() and not 0 < deadline - time.time() <= 3600:
            return
        arm(deadline, maximum=3600)
        issue, key, quota = (
            os.environ.get(name, "")
            for name in ("INCIDENT_ISSUE", "INCIDENT_KEY", "PAWLOCAL_QUOTA_ISSUE")
        )
        if (
            not re.fullmatch(r"[1-9][0-9]{0,19}", issue)
            or not re.fullmatch(r"[0-9a-f]{64}", key)
            or not re.fullmatch(r"[1-9][0-9]{0,19}", quota)
        ):
            raise Denied("trusted claim outputs unavailable")
        client = ReleaseClient(os.environ["GH_TOKEN"], deadline)
        fallback = {
            "issue": int(issue),
            "quota_issue": int(quota),
            "alert": {"incident_key": key},
        }
        control = LiveControl(
            lambda path: client.request("GET", path), fallback, deadline
        ).check
        control()
        actual = client.request("GET", "/issues/" + issue)
        run_id = os.environ["GITHUB_RUN_ID"]
        run_url = "https://github.com/alanlima/pawlocal/actions/runs/" + run_id
        if enabled() and (
            run_url not in actual.get("body", "")
            or INCIDENT + key + " -->" not in actual.get("body", "")
        ):
            raise Denied("claim does not bind current workflow")
        state = (
            "LEASE_UNCERTAIN" if os.environ.get("PUBLICATION_SHA256") else "ESCALATED"
        )
        evidence = run_url
        if os.environ.get("ADMITTED") == "true":
            metadata, profile = context(followup=True)
            if enabled() and (
                metadata["issue"] != int(issue)
                or metadata["alert"]["incident_key"] != key
                or metadata["quota_issue"] != int(quota)
            ):
                raise Denied("claim/admission provenance differs")
            if os.environ.get("PROMOTER_RESULT") == "success":
                _, _, published = publication()
                sha, deployment_run = complete(client, metadata, profile, published)
                state = "RECOVERED" if enabled() else "RELEASE_COMPLETED_UNVERIFIED"
                evidence += f"; merged `{sha}`; production https://github.com/alanlima/pawlocal/actions/runs/{deployment_run}"
        control()
        body = (
            f"{state}: {evidence}. "
            + (
                "Trusted candidate checks, fresh review, development and production release identity, and both stable recovery windows were verified."
                if state == "RECOVERED"
                else "Release operations completed with incident enforcement disabled. Check/review policy and stable recovery were not verified. The incident remains open."
                if state == "RELEASE_COMPLETED_UNVERIFIED"
                else "This attempt did not establish complete recovery. Partial publication/deployment may exist; reconcile actual run and deployment state before any new owner-authorized attempt."
            )
            + (
                " The incident generation remains consumed."
                if enabled()
                else " Prior incident records remain audit history; generation/deduplication policy is disabled."
            )
            + " Any recorded or uncertain monthly reservation remains consumed; no automatic retry or refund."
        )
        acknowledged = client.request(
            "POST", "/issues/" + issue + "/comments", {"body": body}
        )
        if (
            acknowledged.get("body") != body
            or acknowledged.get("user", {}).get("login") != "github-actions[bot]"
        ):
            raise Denied("outcome write acknowledgement uncertain")
        if state == "RECOVERED":
            control()
            closed = client.request(
                "PATCH",
                "/issues/" + issue,
                {"state": "closed", "state_reason": "completed"},
            )
            if closed.get("number") != int(issue) or closed.get("state") != "closed":
                raise Denied("outcome closure acknowledgement uncertain")
        summary(
            state,
            evidence
            + (
                "\n\nEnforcement disabled; recovery unverified."
                if not enabled()
                else ""
            ),
        )
    except Exception:
        # No second API write after uncertainty: the first may have succeeded.
        summary(
            "LEASE_UNCERTAIN",
            "Finalizer could not establish or acknowledge the outcome, or live owner control stopped the attempt. Inspect the linked run; no recovery is claimed here.",
        )
        raise


if __name__ == "__main__":
    main()
