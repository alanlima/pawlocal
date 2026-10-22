"""Explicit exact-target GitHub cleanup; absence never triggers this operation."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from urllib.parse import quote

import yaml
from reconcile import GitHub, ReconciliationError, load_mappings

LEGACY_VARIABLES = (
    "PAWLOCAL_BASELINE_SSH_CIDR_BLOCKS_JSON",
    "PAWLOCAL_CERTIFICATE_ARN",
    "PAWLOCAL_COGNITO_APP_CLIENT_ID",
    "PAWLOCAL_COGNITO_ISSUER",
    "PAWLOCAL_DEPLOY_HOST",
    "PAWLOCAL_DEPLOY_KNOWN_HOSTS",
    "PAWLOCAL_DEPLOY_MODE",
    "PAWLOCAL_DEPLOY_SSH_PUBLIC_KEYS_JSON",
    "PAWLOCAL_DOMAIN_NAME",
    "PAWLOCAL_DSQL_DATABASE_ROLE",
    "PAWLOCAL_DSQL_ENDPOINT",
    "PAWLOCAL_TERRAFORM_ROLE_ARN",
    "PAWLOCAL_TF_STATE_BUCKET",
)
LEGACY_SECRETS = (
    "PAWLOCAL_DEPLOY_SSH_PRIVATE_KEY",
    "PAWLOCAL_DSQL_ACCESS_KEY_ID",
    "PAWLOCAL_DSQL_SECRET_ACCESS_KEY",
)


def prove_legacy_unused(root, github, environment):
    # These are the current release consumers. Same-named plan/runtime settings
    # are outside this cleanup's exact release-Environment scope.
    sources = [
        root / ".github/workflows/fullstack-release.yml",
        root / ".github/workflows/deploy-production.yml",
        root / "ops/run-deployment-adapter.sh",
        root / "ops/deployment-adapters/lightsail-dsql.sh",
    ]
    for path in sources:
        source = path.read_text(encoding="utf-8")
        if any(name in source for name in LEGACY_VARIABLES + LEGACY_SECRETS):
            raise ReconciliationError("Legacy release setting still has a consumer")
    adapter = github.request(
        "GET", f"environments/{environment}/variables/PAWLOCAL_DEPLOY_ADAPTER_PATH"
    )
    if (
        not isinstance(adapter, dict)
        or adapter.get("value") != "ops/deployment-adapters/lightsail-dsql.sh"
    ):
        raise ReconciliationError("Unreviewed release adapter blocks legacy cleanup")
    recovery = yaml.safe_load(
        (root / ".github/workflows/terraform-environment-destroy.yml").read_text(
            encoding="utf-8"
        )
    )
    if any(
        job.get("environment") in {"development", "production"}
        for job in recovery.get("jobs", {}).values()
    ):
        raise ReconciliationError(
            "Recovery release consumer requires review before cleanup"
        )


def cleanup(
    mappings,
    github,
    environment,
    operation,
    confirmation,
    root,
    report=print,
    destroy_confirmed=False,
):
    if environment not in ("development", "production"):
        raise ReconciliationError("Unsupported cleanup environment")
    if operation == "legacy-cleanup":
        if confirmation != f"CLEAN legacy {environment}":
            raise ReconciliationError("Exact legacy cleanup confirmation required")
        prove_legacy_unused(root, github, environment)
        targets = [(environment, "variables", name) for name in LEGACY_VARIABLES] + [
            (environment, "secrets", name) for name in LEGACY_SECRETS
        ]
    elif operation == "destroy-cleanup":
        if confirmation != f"DESTROY {environment}" or not destroy_confirmed:
            raise ReconciliationError(
                "Confirmed reviewed destroy and empty-state verification required"
            )
        targets = [
            (m.github_environment, "secrets" if m.secret else "variables", m.env_name)
            for m in mappings
            if m.store_key.split("/")[4] in {"frontend", "api", "auth"}
        ]
        targets += [
            (f"{environment}-{purpose}", "variables", "PAWLOCAL_RUNTIME_ROLE_ARN")
            for purpose in ("plan", "apply")
        ]
    else:
        raise ReconciliationError("Unsupported cleanup operation")
    for target in sorted({target for target, _, _ in targets}):
        github.request("GET", f"environments/{quote(target, safe='')}")
    for target, kind, name in sorted(set(targets)):
        path = f"environments/{quote(target, safe='')}/{kind}/{quote(name, safe='')}"
        current = github.request("GET", path, missing=True)
        if current is None:
            report(f"already-absent {target}/{name}")
            continue
        github.request("DELETE", path)
        if github.request("GET", path, missing=True) is not None:
            raise ReconciliationError("Cleanup read-back failed")
        report(f"deleted {target}/{name}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--environment", required=True, choices=("development", "production")
    )
    parser.add_argument(
        "--operation", required=True, choices=("legacy-cleanup", "destroy-cleanup")
    )
    parser.add_argument("--confirmation", required=True)
    parser.add_argument("--destroy-confirmed", action="store_true")
    args = parser.parse_args()
    try:
        root = Path(__file__).resolve().parents[2]
        mappings = load_mappings(
            Path(__file__).with_name("parameter-mapping.yaml"), args.environment
        )
        github = GitHub(
            os.environ.get("GITHUB_REPOSITORY", ""),
            os.environ.get("PAWLOCAL_CONFIG_GITHUB_TOKEN", ""),
        )
        cleanup(
            mappings,
            github,
            args.environment,
            args.operation,
            args.confirmation,
            root,
            destroy_confirmed=args.destroy_confirmed,
        )
    except Exception:  # noqa: BLE001 - no credential/response payloads
        raise SystemExit(
            "Explicit configuration cleanup failed; inspect targets and permissions privately"
        ) from None


if __name__ == "__main__":
    main()
