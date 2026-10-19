import json
import os
import shlex
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WRAPPER = ROOT / "ops" / "run-deployment-adapter.sh"
IMAGE = "ghcr.io/alanlima/pawlocal-api@sha256:" + "a" * 64
ENDPOINT = "fnufjjgjjvrjncowdpzbx42xie.dsql.ap-southeast-2.on.aws"
SECRET_MARKER = "do-not-print-this-private-key"


def _bash_path(path: Path) -> str:
    if os.name != "nt":
        return str(path)
    absolute = str(path.resolve()).replace("\\", "/")
    drive, remainder = absolute[0].lower(), absolute[2:]
    return f"/mnt/{drive}{remainder}"


def _manifest(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "commit": "1" * 40,
                "backend_image": IMAGE,
                "backend_image_digest": "sha256:" + "a" * 64,
                "telemetry_enabled": False,
                "migration_chains": {
                    "aurora_dsql": {
                        "runner": "dsql_baseline",
                        "migration_id": "dsql_0001_initial",
                    }
                },
            }
        ),
        encoding="utf-8",
    )


def _environment(tmp_path: Path) -> dict[str, str]:
    bindir = tmp_path / "bin"
    bindir.mkdir()
    ssh_log = tmp_path / "ssh-args.txt"
    ssh = bindir / "ssh"
    ssh.write_bytes(
        b"#!/bin/sh\nprintf '%s\\n' \"$@\" > \"$SSH_ARGS_LOG\"\n"
    )
    ssh.chmod(0o755)

    return {
        "PATH": f"{_bash_path(bindir)}:/usr/local/bin:/usr/bin:/bin",
        "SSH_ARGS_LOG": _bash_path(ssh_log),
        "PAWLOCAL_DEPLOY_ADAPTER_PATH": "ops/deployment-adapters/lightsail-dsql.sh",
        "PAWLOCAL_DEPLOY_HOST": "192.0.2.10",
        "PAWLOCAL_FRONTEND_BUCKET": "pawlocal-development-example",
        "PAWLOCAL_CLOUDFRONT_DISTRIBUTION_ID": "E1234567890ABC",
        "PAWLOCAL_DSQL_ENDPOINT": ENDPOINT,
        "PAWLOCAL_DSQL_DATABASE_ROLE": "pawlocal_development_app",
        "PAWLOCAL_COGNITO_ISSUER": "https://cognito-idp.ap-southeast-2.amazonaws.com/ap-southeast-2_Abc123",
        "PAWLOCAL_COGNITO_APP_CLIENT_ID": "AbCdEf123456",
        "PAWLOCAL_DEPLOY_SSH_PRIVATE_KEY": SECRET_MARKER,
        "PAWLOCAL_DEPLOY_KNOWN_HOSTS": "192.0.2.10 ssh-ed25519 AAAATEST",
        "AWS_REGION": "ap-southeast-2",
        "PAWLOCAL_DATABASE_PROVIDER": "aurora_dsql",
    }


def _run_adapter(tmp_path: Path, env: dict[str, str], *args: str):
    if os.name != "nt":
        return subprocess.run(
            ["bash", str(WRAPPER), *args],
            cwd=ROOT,
            env={**os.environ, **env},
            text=True,
            capture_output=True,
            check=False,
        )

    runner = tmp_path / "run-adapter.sh"
    exports = "\n".join(
        f"export {name}={shlex.quote(value)}" for name, value in env.items()
    )
    runner.write_text(
        "#!/usr/bin/env bash\nset -euo pipefail\n"
        f"cd {shlex.quote(_bash_path(ROOT))}\n{exports}\n"
        f"exec bash ops/run-deployment-adapter.sh \"$@\"\n",
        encoding="utf-8",
        newline="\n",
    )
    return subprocess.run(
        ["wsl.exe", "bash", _bash_path(runner), *args],
        text=True,
        capture_output=True,
        check=False,
    )


def test_seed_development_uses_release_digest_and_target_without_credentials(tmp_path):
    manifest = tmp_path / "manifest.json"
    _manifest(manifest)
    env = _environment(tmp_path)

    result = _run_adapter(
        tmp_path,
        env,
        "seed",
        "--environment",
        "development",
        "--manifest",
        _bash_path(manifest),
    )

    assert result.returncode == 0, result.stderr
    ssh_args = (tmp_path / "ssh-args.txt").read_text(encoding="utf-8")
    assert f"sudo /usr/local/sbin/pawlocal-deploy seed-development '{IMAGE}'" in ssh_args
    assert ENDPOINT not in ssh_args
    assert SECRET_MARKER not in ssh_args
    assert SECRET_MARKER not in result.stdout
    assert SECRET_MARKER not in result.stderr


def test_seed_operation_rejects_production_before_ssh(tmp_path):
    manifest = tmp_path / "manifest.json"
    _manifest(manifest)
    env = _environment(tmp_path)

    result = _run_adapter(
        tmp_path,
        env,
        "seed",
        "--environment",
        "production",
        "--manifest",
        _bash_path(manifest),
    )

    assert result.returncode != 0
    assert "restricted to development" in result.stderr
    assert not (tmp_path / "ssh-args.txt").exists()
