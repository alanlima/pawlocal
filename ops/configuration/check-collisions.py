"""Reject existing Parameter Store keys for Terraform's planned new ownership."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from reconcile import ReconciliationError, load_mappings


def check(plan, client, allowed):
    for resource in plan.get("resource_changes", []):
        if resource.get("type") != "aws_ssm_parameter":
            continue
        change = resource.get("change", {})
        if change.get("importing"):
            raise ReconciliationError("Parameter adoption is not authorized")
        if "create" not in change.get("actions", []):
            continue
        name = (change.get("after") or {}).get("name")
        if name not in allowed:
            raise ReconciliationError("Unapproved parameter creation or adoption")
        if change.get("before") is not None:
            raise ReconciliationError("Parameter replacement requires separate review")
        try:
            client.get_parameter(Name=name, WithDecryption=False)
        except Exception as error:  # noqa: BLE001 - retain normal SDK error context
            if (
                getattr(error, "response", {}).get("Error", {}).get("Code")
                == "ParameterNotFound"
            ):
                continue
            raise ReconciliationError(f"Parameter collision inventory failed: {error}") from error
        raise ReconciliationError("Existing parameter blocks new Terraform ownership")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plan", type=Path)
    parser.add_argument(
        "--environment",
        choices=("development", "production", "bootstrap"),
        required=True,
    )
    args = parser.parse_args()
    try:
        selected = (
            ("development", "production")
            if args.environment == "bootstrap"
            else (args.environment,)
        )
        manifest = Path(__file__).with_name("parameter-mapping.yaml")
        allowed = {
            m.store_key for env in selected for m in load_mappings(manifest, env)
        }
        if args.environment == "bootstrap":
            allowed = {
                key
                for key in allowed
                if key.split("/")[4] in {"iam", "aws", "terraform"}
            }
        else:
            allowed = {
                key
                for key in allowed
                if key.split("/")[4] in {"frontend", "api", "auth"}
            }
        import boto3

        check(
            json.loads(args.plan.read_text(encoding="utf-8")),
            boto3.client("ssm"),
            allowed,
        )
    except Exception as error:  # noqa: BLE001 - keep standard operational errors
        raise SystemExit(
            f"Parameter collision check failed: {type(error).__name__}: {error}"
        ) from error
    print("Parameter creation collision inventory passed")


if __name__ == "__main__":
    main()
