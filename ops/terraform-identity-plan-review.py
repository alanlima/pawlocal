"""Sanitize the identity stage, which may attach only fixed bootstrap policies."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any


EXPECTED = {
    "development": {
        'aws_iam_role_policy_attachment.app["development_frontend"]': (
            "pawlocal-development-github-deploy", "development_frontend"
        ),
        'aws_iam_role_policy_attachment.app["development_runtime"]': (
            "pawlocal-development-dsql-runtime", "development_runtime"
        ),
    },
    "production": {
        'aws_iam_role_policy_attachment.app["production_frontend"]': (
            "pawlocal-production-github-deploy", "production_frontend"
        ),
    },
}


def render(plan: dict[str, Any], environment: str, policy_arns: dict[str, str]) -> str:
    if not isinstance(plan.get("format_version"), str) or not isinstance(plan.get("resource_changes"), list):
        raise ValueError("Input is not a Terraform plan JSON document")
    if plan.get("applyable") is not True or plan.get("complete") is not True or plan.get("errored") is not False:
        raise ValueError("Identity plan must be complete, applyable, and error-free")
    if plan.get("deferred_changes") or plan.get("output_changes"):
        raise ValueError("Identity plan contains deferred or output changes")
    expected = EXPECTED[environment]
    seen: set[str] = set()
    rows: list[str] = []
    for item in plan["resource_changes"]:
        change = item.get("change", {})
        actions = change.get("actions")
        if item.get("mode", "managed") == "data":
            if actions not in (["read"], ["no-op"]):
                raise ValueError("Identity plan contains an unsupported data-source action")
            continue
        address = item.get("address")
        if item.get("type") != "aws_iam_role_policy_attachment" or address not in expected:
            raise ValueError("Identity state may manage only the exact approved policy attachments")
        if actions not in (["create"], ["no-op"]):
            raise ValueError("Identity plan may create or retain attachments only; updates and detachments are blocked")
        role_name, policy_key = expected[address]
        after = change.get("after")
        if not isinstance(after, dict) or after.get("role") != role_name or after.get("policy_arn") != policy_arns.get(policy_key):
            raise ValueError("Identity attachment does not match its exact bootstrap-owned role and managed policy")
        if address in seen:
            raise ValueError("Identity plan contains a duplicate attachment address")
        seen.add(address)
        rows.append(f"| `{address}` | `{actions[0]}` |")
    if seen != set(expected):
        raise ValueError("Identity plan does not contain all exact selected environment attachments")
    return "\n".join([
        f"### {environment.title()} IAM identity plan", "",
        "| Exact Terraform address | Action |", "|---|---|", *sorted(rows), "",
        "Only fixed bootstrap-managed policies are attached to exact pre-existing application roles. This state cannot create roles, change trust, edit policy documents, or change permissions boundaries.",
    ])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--environment", choices=("development", "production"), required=True)
    parser.add_argument("--development-frontend-policy-arn", required=True)
    parser.add_argument("--production-frontend-policy-arn", required=True)
    parser.add_argument("--development-dsql-policy-arn", required=True)
    args = parser.parse_args()
    try:
        print(render(json.load(sys.stdin), args.environment, {
            "development_frontend": args.development_frontend_policy_arn,
            "production_frontend": args.production_frontend_policy_arn,
            "development_runtime": args.development_dsql_policy_arn,
        }))
    except (json.JSONDecodeError, ValueError) as exc:
        print(f"Identity plan review rejected: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
