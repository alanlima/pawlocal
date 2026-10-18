from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VALIDATOR = ROOT / "ops" / "validate-release-metadata.py"


def release_manifest(environment: str = "development") -> dict:
    return {
        "schema_version": 2,
        "commit": "a" * 40,
        "backend_image": f"ghcr.io/alanlima/pawlocal-api@sha256:{'b' * 64}",
        "backend_image_digest": f"sha256:{'b' * 64}",
        "migration_chains": {
            "postgresql": {
                "runner": "alembic",
                "migration_id": "0007_normalize_place_facilities",
            },
            "aurora_dsql": {
                "runner": "dsql_baseline",
                "migration_id": "dsql_0001_initial",
            },
        },
        "telemetry_enabled": False,
        "frontend": {
            "environment": environment,
            "artifact_digest": f"sha256:{'c' * 64}",
        },
    }


def deployment_evidence(manifest: dict, provider: str) -> dict:
    chain = manifest["migration_chains"][provider]
    return {
        "schema_version": 1,
        "environment": manifest["frontend"]["environment"],
        "commit": manifest["commit"],
        "backend_image_digest": manifest["backend_image_digest"],
        "frontend_artifact_digest": manifest["frontend"]["artifact_digest"],
        "database_provider": provider,
        "migration_runner": chain["runner"],
        "migration_id": chain["migration_id"],
        "telemetry_enabled": False,
        "public_endpoint_health": {"frontend": True, "api": True},
        "verified_at": "2026-10-19T01:02:03Z",
    }


class ReleaseMetadataTests(unittest.TestCase):
    def validate(self, manifest: dict, evidence: dict | None = None, environment: str | None = None) -> subprocess.CompletedProcess:
        with tempfile.TemporaryDirectory() as directory:
            manifest_path = Path(directory) / "release-manifest.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            command = [sys.executable, str(VALIDATOR), "--manifest", str(manifest_path)]
            if evidence is not None:
                evidence_path = Path(directory) / "deployment-evidence.json"
                evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
                command.extend(("--evidence", str(evidence_path), "--environment", environment or "development"))
            return subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)

    def test_manifest_contains_both_provider_specific_migration_chains(self) -> None:
        result = self.validate(release_manifest())
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_evidence_accepts_each_matching_provider_chain(self) -> None:
        manifest = release_manifest()
        for provider in ("postgresql", "aurora_dsql"):
            with self.subTest(provider=provider):
                result = self.validate(manifest, deployment_evidence(manifest, provider))
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_evidence_rejects_migration_id_from_another_provider(self) -> None:
        manifest = release_manifest()
        evidence = deployment_evidence(manifest, "aurora_dsql")
        evidence["migration_id"] = manifest["migration_chains"]["postgresql"]["migration_id"]
        result = self.validate(manifest, evidence)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("migration_id does not match", result.stderr)

    def test_evidence_rejects_unhealthy_endpoints_and_enabled_telemetry(self) -> None:
        manifest = release_manifest()
        evidence = deployment_evidence(manifest, "postgresql")
        evidence["public_endpoint_health"]["api"] = False
        result = self.validate(manifest, evidence)
        self.assertNotEqual(result.returncode, 0)

        evidence = deployment_evidence(manifest, "postgresql")
        evidence["telemetry_enabled"] = True
        result = self.validate(manifest, evidence)
        self.assertNotEqual(result.returncode, 0)

    def test_release_schemas_describe_provider_and_migration_selection(self) -> None:
        manifest_schema = json.loads((ROOT / "ops" / "release-manifest.schema.json").read_text())
        evidence_schema = json.loads((ROOT / "ops" / "deployment-evidence.schema.json").read_text())
        migration_chains = manifest_schema["properties"]["migration_chains"]["properties"]
        evidence = evidence_schema["properties"]
        self.assertEqual(set(migration_chains), {"postgresql", "aurora_dsql"})
        self.assertIn("database_provider", evidence_schema["required"])
        self.assertIn("migration_runner", evidence_schema["required"])
        self.assertIn("migration_id", evidence_schema["required"])
        self.assertEqual(evidence["database_provider"]["enum"], ["postgresql", "aurora_dsql"])


if __name__ == "__main__":
    unittest.main()
