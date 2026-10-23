"""Reject existing Parameter Store keys for Terraform's planned new ownership."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from reconcile import ReconciliationError


def check(plan, client):
    checked = 0
    for resource in plan.get("resource_changes", []):
        if resource.get("type") != "aws_ssm_parameter":
            continue
        change = resource.get("change", {})
        address = resource.get("address", "aws_ssm_parameter (address unavailable)")
        if change.get("importing"):
            raise ReconciliationError(
                f"Parameter adoption is not authorized: {address}"
            )
        if "create" not in change.get("actions", []):
            continue
        name = (change.get("after") or {}).get("name")
        if not isinstance(name, str) or not name:
            raise ReconciliationError(
                f"Planned parameter name must be known for collision inventory: {address}"
            )
        if change.get("before") is not None:
            raise ReconciliationError(
                f"Parameter replacement requires separate review: {name!r} ({address})"
            )
        print(f"Checking Parameter Store key: {name!r}", flush=True)
        checked += 1
        try:
            client.get_parameter(Name=name, WithDecryption=False)
        except Exception as error:
            code = getattr(error, "response", {}).get("Error", {}).get("Code")
            if code == "ParameterNotFound":
                print(f"Key available for creation: {name!r}", flush=True)
                continue
            raise ReconciliationError(
                f"Parameter collision inventory failed for {name!r}: "
                f"ssm:GetParameter returned {code or type(error).__name__}"
            ) from error
        raise ReconciliationError(
            f"Existing parameter blocks new Terraform ownership: {name!r}"
        )
    print(
        f"Parameter creation collision inventory passed: {checked} key(s) checked",
        flush=True,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plan", type=Path)
    parser.add_argument(
        "--environment",
        choices=("development", "production", "bootstrap"),
        required=True,
    )
    args = parser.parse_args()
    print(f"Checking Parameter Store collisions for {args.environment}", flush=True)
    try:
        import boto3

        check(
            json.loads(args.plan.read_text(encoding="utf-8")),
            boto3.client("ssm"),
        )
    except Exception as error:
        raise SystemExit(
            f"Parameter collision check failed: {type(error).__name__}: {error}"
        ) from error


if __name__ == "__main__":
    main()
