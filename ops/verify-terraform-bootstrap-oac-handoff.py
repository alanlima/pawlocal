"""Read-only check that the bootstrap IAM OAC policy handoff is applied."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any
from urllib.parse import unquote


DEV_ROLE = "pawlocal-development-terraform-apply"
PROD_ROLE = "pawlocal-production-terraform-apply"
DEV_POLICY = f"{DEV_ROLE}-permissions"
PROD_POLICY = f"{PROD_ROLE}-permissions"
READ_ACTIONS = {"cloudfront:GetOriginAccessControl", "cloudfront:GetOriginAccessControlConfig"}
MUTATE_ACTIONS = {"cloudfront:UpdateOriginAccessControl", "cloudfront:DeleteOriginAccessControl"}
CREATE_ACTION = "cloudfront:CreateOriginAccessControl"
LIST_ACTION = "cloudfront:ListOriginAccessControls"


def parse_document(document: Any) -> dict[str, Any]:
    if isinstance(document, str):
        document = json.loads(unquote(document))
    if not isinstance(document, dict):
        raise ValueError("IAM inline policy document is not a mapping")
    statements = document.get("Statement")
    if isinstance(statements, dict):
        document["Statement"] = [statements]
    elif not isinstance(statements, list):
        raise ValueError("IAM inline policy has no statement list")
    return document


def allowed_cloudfront(policy: dict[str, Any]) -> list[tuple[str, str]]:
    result: list[tuple[str, str]] = []
    for statement in policy["Statement"]:
        if not isinstance(statement, dict) or statement.get("Effect") != "Allow":
            continue
        actions = statement.get("Action", [])
        resources = statement.get("Resource", [])
        actions = [actions] if isinstance(actions, str) else actions
        resources = [resources] if isinstance(resources, str) else resources
        if not isinstance(actions, list) or not isinstance(resources, list):
            raise ValueError("IAM statement action/resource shape is unsupported")
        for action in actions:
            if isinstance(action, str) and action.casefold().startswith("cloudfront:"):
                if not resources:
                    raise ValueError("CloudFront permission has no resource scope")
                result.extend((action, str(resource)) for resource in resources)
    return result


def verify_handoff(dev_policy_document: Any, prod_policy_document: Any, dev_arn: str, prod_arn: str = "", account_id: str = "") -> str:
    if not dev_arn.startswith("arn:") or ":cloudfront::" not in dev_arn or "origin-access-control/" not in dev_arn:
        raise ValueError("Development OAC ARN is missing or malformed")
    if account_id and f"cloudfront::{account_id}:" not in dev_arn:
        raise ValueError("Development OAC ARN belongs to a different AWS account")
    dev = allowed_cloudfront(parse_document(dev_policy_document))
    prod = allowed_cloudfront(parse_document(prod_policy_document))

    if any(action not in READ_ACTIONS | MUTATE_ACTIONS for action, _ in dev):
        raise ValueError("Development apply policy has an unexpected CloudFront permission")
    if set(dev) != {(action, dev_arn) for action in READ_ACTIONS | MUTATE_ACTIONS}:
        raise ValueError("Development apply policy does not pin OAC permissions to the exact development ARN")

    if prod_arn:
        if not prod_arn.startswith("arn:") or ":cloudfront::" not in prod_arn or "origin-access-control/" not in prod_arn:
            raise ValueError("Production OAC ARN is malformed")
        if account_id and f"cloudfront::{account_id}:" not in prod_arn:
            raise ValueError("Production OAC ARN belongs to a different AWS account")
        expected = {(action, prod_arn) for action in READ_ACTIONS | MUTATE_ACTIONS}
        if set(prod) != expected:
            raise ValueError("Production apply policy does not pin OAC permissions to the exact production ARN")
        return "existing-production-oac-pinned"

    if any(action not in READ_ACTIONS | {CREATE_ACTION} for action, _ in prod):
        raise ValueError("Initial production apply policy has an unexpected CloudFront permission")
    if set(prod) != {(action, "*") for action in READ_ACTIONS | {CREATE_ACTION}}:
        raise ValueError("Initial production apply policy does not match the production OAC creation window")
    if any(action == LIST_ACTION for action, _ in prod):
        raise ValueError("Production apply policy unexpectedly allows OAC listing")
    return "production-oac-create-window-enabled"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--account-id", required=True)
    parser.add_argument("--development-oac-arn", required=True)
    parser.add_argument("--production-oac-arn", default="")
    parser.add_argument("--region", required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        import boto3

        iam = boto3.client("iam", region_name=args.region)
        dev = iam.get_role_policy(RoleName=DEV_ROLE, PolicyName=DEV_POLICY)["PolicyDocument"]
        prod = iam.get_role_policy(RoleName=PROD_ROLE, PolicyName=PROD_POLICY)["PolicyDocument"]
        phase = verify_handoff(dev, prod, args.development_oac_arn, args.production_oac_arn, args.account_id)
        print(f"Bootstrap OAC handoff verified: {phase}")
    except Exception as exc:  # AWS/client errors fail closed without dumping response contents.
        print(f"Bootstrap OAC handoff verification failed: {type(exc).__name__}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
