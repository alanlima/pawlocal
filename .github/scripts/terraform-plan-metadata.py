"""Create or verify metadata binding an opaque Terraform plan to one workflow run."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


COGNITO_ARCHIVE_NAME = "cognito-pre-sign-up.zip"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def target_fingerprint(account_id: str, backend_bucket: str, backend_region: str) -> str:
    return hashlib.sha256(f"{account_id}\0{backend_bucket}\0{backend_region}".encode()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("create", "verify"))
    parser.add_argument("plan", type=Path)
    parser.add_argument("metadata", type=Path)
    parser.add_argument("--environment", choices=("development", "production"), required=True)
    parser.add_argument("--state-key", required=True)
    parser.add_argument("--account-id", required=True)
    parser.add_argument("--backend-bucket", required=True)
    parser.add_argument("--backend-region", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--repository-id", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--run-attempt", required=True)
    parser.add_argument("--archive", type=Path)
    args = parser.parse_args()

    expected = {
        "environment": args.environment,
        "state_key": args.state_key,
        "target_fingerprint": target_fingerprint(args.account_id, args.backend_bucket, args.backend_region),
        "commit": args.commit,
        "repository_id": args.repository_id,
        "run_id": args.run_id,
        "run_attempt": args.run_attempt,
    }
    archive = None
    if args.archive is not None:
        archive = {
            "name": COGNITO_ARCHIVE_NAME,
            "terraform_path": (
                f".terraform/pawlocal-{args.environment}-cognito-pre-signup.zip"
            ),
            "sha256": digest(args.archive),
        }
    plan_digest = digest(args.plan)
    if args.mode == "create":
        payload = {**expected, "sha256": plan_digest}
        if archive is not None:
            payload["cognito_archive"] = archive
        args.metadata.write_text(
            json.dumps(payload, separators=(",", ":")),
            encoding="utf-8",
        )
        print(plan_digest)
        return

    actual = json.loads(args.metadata.read_text(encoding="utf-8"))
    if any(actual.get(key) != value for key, value in expected.items()):
        raise SystemExit("Saved plan metadata does not match this workflow run")
    if actual.get("sha256") != plan_digest:
        raise SystemExit("Saved Terraform plan digest mismatch")
    if archive is None:
        if "cognito_archive" in actual:
            raise SystemExit("Saved plan unexpectedly requires a Cognito archive")
    elif actual.get("cognito_archive") != archive:
        raise SystemExit("Saved Cognito archive metadata or digest mismatch")
    print(plan_digest)


if __name__ == "__main__":
    main()
