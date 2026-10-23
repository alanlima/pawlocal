"""Bound, redacted follow-up receipts from trusted jobs only."""

import json
import math
import os
import re
import time
from pathlib import Path

from candidate import digest
from job import download
from quota import Denied, strict_json


def write(phase, metadata, publication, payload):
    if phase not in {"merge", "development", "production", "progress"}:
        raise Denied("unsupported receipt phase")
    now = int(time.time())
    if not publication["published_at"] <= now < publication["promotion_deadline"]:
        raise Denied("receipt cannot extend release deadline")
    value = {
        "schema": 1,
        "phase": phase,
        "run_id": metadata["run_id"],
        "admission_sha256": publication["admission_sha256"],
        "publication_sha256": os.environ["PUBLICATION_SHA256"],
        "profile_sha256": publication["profile_sha256"],
        "deadline": publication["promotion_deadline"],
        "recorded_at": now,
        "payload": payload,
    }
    raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    root = Path(os.environ["RUNNER_TEMP"]) / ("oncall-" + phase)
    root.mkdir(mode=0o700, exist_ok=True)
    (root / "receipt.json").write_bytes(raw)
    with open(os.environ["GITHUB_OUTPUT"], "a") as stream:
        stream.write(phase + "_sha256=" + digest(raw) + "\n")
    return value


def read(phase, expected, metadata, publication):
    if (
        phase not in {"merge", "development", "production"}
        or not isinstance(expected, str)
        or not re.fullmatch(r"[0-9a-f]{64}", expected)
    ):
        raise Denied("trusted receipt digest required")
    raw = download("oncall-" + phase + "-" + metadata["run_id"], {"receipt.json"})[
        "receipt.json"
    ]
    value = strict_json(raw)
    if (
        digest(raw) != expected
        or not isinstance(value, dict)
        or set(value)
        != {
            "schema",
            "phase",
            "run_id",
            "admission_sha256",
            "publication_sha256",
            "profile_sha256",
            "deadline",
            "recorded_at",
            "payload",
        }
    ):
        raise Denied("receipt schema/digest differs")
    expected_fields = {
        "schema": 1,
        "phase": phase,
        "run_id": metadata["run_id"],
        "admission_sha256": publication["admission_sha256"],
        "publication_sha256": os.environ["PUBLICATION_SHA256"],
        "profile_sha256": publication["profile_sha256"],
        "deadline": publication["promotion_deadline"],
    }
    if (
        any(
            type(value[key]) is not type(item) or value[key] != item
            for key, item in expected_fields.items()
        )
        or type(value["recorded_at"]) is not int
        or not publication["published_at"] <= value["recorded_at"] < value["deadline"]
        or not isinstance(value["payload"], dict)
    ):
        raise Denied("receipt provenance/deadline differs")
    return value["payload"]


def validate_recovery(proof, release, profile, environment, publication):
    fields = {
        "schema",
        "environment",
        "commit",
        "digest",
        "deployment_id",
        "deployment_run",
        "window_seconds",
        "started_at",
        "completed_at",
        "samples",
        "settling_seconds",
        "settling_samples",
        "profile_sha256",
    }
    if (
        not isinstance(proof, dict)
        or set(proof) != fields
        or not isinstance(release, dict)
    ):
        raise Denied("complete bounded recovery receipt required")
    expected = {
        "schema": 1,
        "environment": environment,
        "commit": release.get("affected_sha"),
        "digest": release.get("image_digest"),
        "deployment_id": release.get("deployment_id"),
        "deployment_run": release.get("deployment_run"),
        "window_seconds": profile.recovery_seconds,
        "profile_sha256": profile.digest,
    }
    if (
        any(
            type(proof[key]) is not type(item) or proof[key] != item
            for key, item in expected.items()
        )
        or type(proof["samples"]) is not int
        or proof["samples"] < 2
        or type(proof["settling_samples"]) is not int
        or proof["settling_samples"] < 0
    ):
        raise Denied("recovery receipt identity/profile differs")
    if any(
        type(proof[key]) not in {int, float} or not math.isfinite(proof[key])
        for key in ("started_at", "completed_at", "settling_seconds")
    ):
        raise Denied("recovery receipt times invalid")
    if (
        proof["settling_seconds"] < 0
        or proof["started_at"] - proof["settling_seconds"] < publication["published_at"]
        or proof["completed_at"] - proof["started_at"] < profile.recovery_seconds
        or not proof["started_at"]
        <= proof["completed_at"]
        < publication["promotion_deadline"]
        or proof["completed_at"] > time.time()
    ):
        raise Denied("recovery window/deadline proof differs")
