import json
import os
import shlex
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
WRAPPER = ROOT / "ops" / "run-deployment-adapter.sh"


def _bash_path(path: Path) -> str:
    if os.name != "nt":
        return str(path)
    absolute = str(path.resolve()).replace("\\", "/")
    drive, remainder = absolute[0].lower(), absolute[2:]
    return f"/mnt/{drive}{remainder}"


def _manifest(path: Path) -> None:
    path.write_text(json.dumps({
        "schema_version": 2,
        "commit": "1" * 40,
        "backend_image": "ghcr.io/alanlima/pawlocal-api@sha256:" + "a" * 64,
        "backend_image_digest": "sha256:" + "a" * 64,
        "telemetry_enabled": False,
        "migration_chains": {"aurora_dsql": {
            "runner": "dsql_baseline", "migration_id": "dsql_0001_initial"
        }},
    }), encoding="utf-8")


def _run_adapter(tmp_path: Path, *args: str):
    env = {**os.environ, "PAWLOCAL_DEPLOY_ADAPTER_PATH": "ops/deployment-adapters/lightsail-dsql.sh"}
    if os.name != "nt":
        return subprocess.run(["bash", str(WRAPPER), *args], cwd=ROOT, env=env, text=True, capture_output=True, check=False)
    runner = tmp_path / "run-adapter.sh"
    exports = "\n".join(f"export {name}={shlex.quote(value)}" for name, value in env.items() if name == "PAWLOCAL_DEPLOY_ADAPTER_PATH")
    runner.write_text("#!/usr/bin/env bash\nset -euo pipefail\n" f"cd {shlex.quote(_bash_path(ROOT))}\n{exports}\n" f"exec bash ops/run-deployment-adapter.sh \"$@\"\n", encoding="utf-8", newline="\n")
    return subprocess.run(["wsl.exe", "bash", _bash_path(runner), *args], text=True, capture_output=True, check=False)


def test_seed_development_fails_closed_without_a_container_seed_mechanism(tmp_path):
    manifest = tmp_path / "manifest.json"
    _manifest(manifest)
    result = _run_adapter(tmp_path, "seed", "--environment", "development", "--manifest", _bash_path(manifest))
    assert result.returncode != 0
    assert "container-compatible, audited mechanism" in result.stderr
    assert "PAWLOCAL_DEPLOY_SSH_PRIVATE_KEY" not in result.stderr
