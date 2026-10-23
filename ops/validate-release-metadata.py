#!/usr/bin/env python3
"""Validate provider-neutral release manifests and deployment evidence."""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

MIGRATION_PROVIDERS = {
    "postgresql": "alembic",
    "aurora_dsql": "dsql_baseline",
}
SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
COMMIT = re.compile(r"^[0-9a-f]{40}$")


def fail(message: str) -> None:
    raise ValueError(message)


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        fail(f"Could not read JSON from {path}: {error}")
    if not isinstance(value, dict):
        fail(f"Expected a JSON object in {path}")
    return value


def validate_manifest(manifest: dict[str, Any]) -> None:
    if manifest.get("schema_version") != 2:
        fail("Release manifest schema_version must be 2")
    if not COMMIT.fullmatch(str(manifest.get("commit", ""))):
        fail("Release manifest commit must be a full lowercase commit SHA")
    digest = manifest.get("backend_image_digest")
    if not isinstance(digest, str) or not SHA256.fullmatch(digest):
        fail("Release manifest backend_image_digest must be a SHA-256 digest")
    image = manifest.get("backend_image")
    if not isinstance(image, str) or image != f"{image.split('@')[0]}@{digest}":
        fail("Release manifest backend_image must be pinned to backend_image_digest")
    if type(manifest.get("telemetry_enabled")) is not bool:
        fail("Release manifest must declare a boolean telemetry mode")

    chains = manifest.get("migration_chains")
    if not isinstance(chains, dict) or set(chains) != set(MIGRATION_PROVIDERS):
        fail("Release manifest must describe PostgreSQL and Aurora DSQL migration chains")
    for provider, runner in MIGRATION_PROVIDERS.items():
        chain = chains[provider]
        if not isinstance(chain, dict) or chain.get("runner") != runner:
            fail(f"{provider} migration chain must use runner {runner}")
        migration_id = chain.get("migration_id")
        if not isinstance(migration_id, str) or not migration_id:
            fail(f"{provider} migration chain must have a migration_id")
        if provider == "postgresql" and not re.fullmatch(r"[A-Za-z0-9_-]+", migration_id):
            fail("PostgreSQL Alembic migration_id must be a revision identifier")
        if provider == "aurora_dsql" and migration_id != "dsql_0001_initial":
            fail("Aurora DSQL clean-install baseline migration_id is not recognized")

    frontend = manifest.get("frontend")
    if frontend is not None:
        if not isinstance(frontend, dict):
            fail("Release manifest frontend metadata must be an object")
        if frontend.get("environment") not in {"development", "production"}:
            fail("Release manifest frontend environment is invalid")
        if not isinstance(frontend.get("artifact_digest"), str) or not SHA256.fullmatch(frontend["artifact_digest"]):
            fail("Release manifest frontend artifact_digest must be a SHA-256 digest")
        source_digest = frontend.get("source_development_artifact_digest")
        if source_digest is not None and (not isinstance(source_digest, str) or not SHA256.fullmatch(source_digest)):
            fail("Release manifest source development artifact digest is invalid")


def validate_evidence(
    manifest: dict[str, Any],
    evidence: dict[str, Any],
    environment: str,
    database_provider: str | None,
    migration_runner: str | None,
    migration_id: str | None,
) -> None:
    if evidence.get("schema_version") != 1:
        fail("Deployment evidence schema_version must be 1")
    if evidence.get("environment") != environment:
        fail("Deployment evidence environment does not match the target")
    if evidence.get("commit") != manifest["commit"]:
        fail("Deployment evidence commit does not match the release manifest")
    if evidence.get("backend_image_digest") != manifest["backend_image_digest"]:
        fail("Deployment evidence backend digest does not match the release manifest")
    if evidence.get("running_image_digest") != manifest["backend_image_digest"]:
        fail("Deployment evidence running image digest does not match the release manifest")
    frontend = manifest.get("frontend")
    if frontend is None or frontend.get("environment") != environment:
        fail("Release manifest does not contain frontend metadata for this environment")
    if evidence.get("frontend_artifact_digest") != frontend["artifact_digest"]:
        fail("Deployment evidence frontend digest does not match the release manifest")
    provider = evidence.get("database_provider")
    if not isinstance(provider, str) or provider not in MIGRATION_PROVIDERS:
        fail("Deployment evidence database_provider is unsupported")
    if database_provider is not None and provider != database_provider:
        fail("Deployment evidence database_provider does not match the selected target")
    chain = manifest["migration_chains"][provider]
    if evidence.get("migration_runner") != chain["runner"]:
        fail("Deployment evidence migration_runner does not match the selected provider")
    if evidence.get("migration_id") != chain["migration_id"]:
        fail("Deployment evidence migration_id does not match the selected provider chain")
    if migration_runner is not None and chain["runner"] != migration_runner:
        fail("Deployment evidence migration_runner does not match the verified development release")
    if migration_id is not None and chain["migration_id"] != migration_id:
        fail("Deployment evidence migration_id does not match the verified development release")
    if type(evidence.get("telemetry_enabled")) is not bool or evidence["telemetry_enabled"] != manifest["telemetry_enabled"]:
        fail("Deployment evidence telemetry mode must match the selected release")
    health = evidence.get("public_endpoint_health")
    if not isinstance(health, dict) or health != {"frontend": True, "api": True}:
        fail("Deployment evidence must confirm healthy frontend and API endpoints")
    query_smoke = evidence.get("database_query_smoke")
    if query_smoke != {"route": "/api/v1/places", "result": "valid_place_page"}:
        fail("Deployment evidence must confirm a successful public /api/v1/places database-query smoke")
    verified_at = evidence.get("verified_at")
    if not isinstance(verified_at, str):
        fail("Deployment evidence verified_at must be an ISO-8601 timestamp")
    try:
        parsed_time = datetime.fromisoformat(verified_at.replace("Z", "+00:00"))
    except ValueError:
        fail("Deployment evidence verified_at must be an ISO-8601 timestamp")
    if parsed_time.tzinfo is None:
        fail("Deployment evidence verified_at must include a timezone")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--evidence", type=Path)
    parser.add_argument("--environment", choices=("development", "production"))
    parser.add_argument("--database-provider", choices=tuple(MIGRATION_PROVIDERS))
    parser.add_argument("--migration-runner", choices=tuple(MIGRATION_PROVIDERS.values()))
    parser.add_argument("--migration-id")
    args = parser.parse_args()
    try:
        manifest = load_json(args.manifest)
        validate_manifest(manifest)
        if args.evidence:
            if not args.environment:
                fail("--environment is required when validating deployment evidence")
            validate_evidence(
                manifest,
                load_json(args.evidence),
                args.environment,
                args.database_provider,
                args.migration_runner,
                args.migration_id,
            )
    except ValueError as error:
        print(f"Release metadata validation failed: {error}", file=sys.stderr)
        return 1
    print("Release metadata is valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
