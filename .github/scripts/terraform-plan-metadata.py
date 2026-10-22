"""Create or verify metadata binding an opaque Terraform plan to one workflow run."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


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
    plan_digest = digest(args.plan)
    if args.mode == "create":
        args.metadata.write_text(
            json.dumps({**expected, "sha256": plan_digest}, separators=(",", ":")),
            encoding="utf-8",
        )
        print(plan_digest)
        return

    actual = json.loads(args.metadata.read_text(encoding="utf-8"))
    if any(actual.get(key) != value for key, value in expected.items()):
        raise SystemExit("Saved plan metadata does not match this workflow run")
    if actual.get("sha256") != plan_digest:
        raise SystemExit("Saved Terraform plan digest mismatch")
    print(plan_digest)


if __name__ == "__main__":
    main()
