"""Execute the production GitHub deployment recorder with synthetic evidence."""

import hashlib
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


class ProductionDeploymentRecordTests(unittest.TestCase):
    def test_disabled_record(self):
        with tempfile.TemporaryDirectory() as directory:
            self.record(Path(directory), False)

    def test_enabled_record(self):
        with tempfile.TemporaryDirectory() as directory:
            self.record(Path(directory), True)

    def test_independent_browser_only_record(self):
        with tempfile.TemporaryDirectory() as directory:
            self.record(Path(directory), False, frontend=True)

    def test_rollback_record_retains_verified_evidence_and_lineage(self):
        with tempfile.TemporaryDirectory() as directory:
            self.record(Path(directory), True, rollback=True)

    def record(self, tmp_path, enabled, frontend=None, rollback=False):
        workflow = yaml.safe_load(
            (ROOT / ".github/workflows/deploy-production.yml").read_text()
        )
        step = next(
            s
            for job in workflow["jobs"].values()
            for s in job.get("steps", [])
            if s.get("name") == "Record successful production deployment"
        )
        script = step["with"]["script"]
        manifest = {"schema_version": 2, "commit": "a" * 40}
        evidence = {
            "schema_version": 1,
            "backend_image_digest": "sha256:" + "b" * 64,
            "running_image_digest": "sha256:" + "b" * 64,
            "frontend_artifact_digest": "sha256:" + "c" * 64,
            "database_provider": "aurora_dsql",
            "migration_runner": "dsql_baseline",
            "migration_id": "dsql_0001_initial",
            "telemetry_enabled": enabled,
            "public_endpoint_health": {"frontend": True, "api": True},
            "database_query_smoke": {
                "route": "/api/v1/places",
                "result": "valid_place_page",
            },
        }
        if frontend is not None:
            manifest["schema_version"] = 3
            evidence["schema_version"] = 2
            evidence["frontend_telemetry_enabled"] = frontend
        release = tmp_path / "release"
        release.mkdir()
        manifest_bytes = json.dumps(manifest).encode()
        evidence_bytes = json.dumps(evidence).encode()
        (release / "release-manifest.json").write_bytes(manifest_bytes)
        (release / "production-verification.json").write_bytes(evidence_bytes)
        harness = """
    const calls = [];
    const summary = {addHeading(){return this},addTable(){return this},addRaw(){return this},addCodeBlock(){return this},async write(){}};
    const core = {summary};
    const context = {repo:{owner:'alanlima',repo:'pawlocal'},runId:123,serverUrl:'https://github.com'};
    const github = {rest:{repos:{
     createDeployment: async value => {calls.push(value);return {data:{id:456}}},
     createDeploymentStatus: async value => {calls.push(value)}
    }}};
    (async () => { SCRIPT; process.stdout.write(JSON.stringify(calls)); })().catch(e=>{console.error(e);process.exit(1)});
    """.replace("SCRIPT", script)
        result = subprocess.run(
            ["node", "-e", harness],
            cwd=tmp_path,
            env={
                **os.environ,
                "RELEASE_COMMIT": manifest["commit"],
                "RUN_ATTEMPT": "2",
                "BACKEND_IMAGE": "ghcr.io/alanlima/pawlocal-api@"
                + evidence["backend_image_digest"],
                "ENVIRONMENT_URL": "https://pawlocal.example.test",
                "ROLLBACK_FROM": "7309" if rollback else "",
                "ROLLBACK_TO": "7308" if rollback else "",
                "ROLLBACK_REASON": "Incident #404" if rollback else "",
            },
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        record, status = json.loads(result.stdout)
        payload = record["payload"]
        assert record["environment"] == "production"
        assert payload["record_schema_version"] == 1
        assert payload["manifest_schema_version"] == manifest["schema_version"]
        assert payload["evidence_schema_version"] == evidence["schema_version"]
        assert payload["evidence_validated"] is True
        assert payload["workflow_run_id"] == 123
        assert payload["workflow_run_attempt"] == 2
        assert payload["release_commit"] == manifest["commit"]
        assert (
            payload["release_manifest_digest"]
            == "sha256:" + hashlib.sha256(manifest_bytes).hexdigest()
        )
        assert (
            payload["verification_evidence_digest"]
            == "sha256:" + hashlib.sha256(evidence_bytes).hexdigest()
        )
        for name in evidence.keys() - {"schema_version"}:
            assert payload[name] == evidence[name]
        if rollback:
            assert payload["operation"] == "rollback"
            assert payload["rollback_from_deployment_id"] == 7309
            assert payload["rollback_to_deployment_id"] == 7308
            assert payload["rollback_reason"] == "Incident #404"
        else:
            assert "operation" not in payload
            assert "rollback_from_deployment_id" not in payload
        assert status["deployment_id"] == 456
        assert status["state"] == "success"
