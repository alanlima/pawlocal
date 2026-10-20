"""Fail-closed check of the bootstrap-managed CloudFront tagging grants."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any
from urllib.parse import unquote


ENVIRONMENTS = ("development", "production")
TAG_STATEMENT_SID = "TagAccountCloudFrontDistributionsForMVP"
UPDATE_STATEMENT_SID = "UpdateTaggedAccountCloudFrontDistributionsForMVP"
UPDATE_ACTION = "cloudfront:UpdateDistribution"
TAG_KEYS = {"project", "environment", "managedby", "component", "workload", "costcenter"}


def _values(value: Any) -> list[Any]:
    return value if isinstance(value, list) else [value]


def parse_document(document: Any) -> dict[str, Any]:
    if isinstance(document, str):
        document = json.loads(unquote(document))
    if not isinstance(document, dict):
        raise ValueError("IAM inline policy document is not a mapping")
    statements = document.get("Statement")
    if isinstance(statements, dict):
        document["Statement"] = [statements]
    elif not isinstance(statements, list) or not all(isinstance(item, dict) for item in statements):
        raise ValueError("IAM inline policy has an unsupported statement list")
    return document


def _expected_statement(environment: str, account_id: str) -> dict[str, Any]:
    return {
        "Sid": TAG_STATEMENT_SID,
        "Effect": "Allow",
        "Action": "cloudfront:TagResource",
        "Resource": f"arn:aws:cloudfront::{account_id}:distribution/*",
        "Condition": {
            "StringEquals": {
                "aws:RequestTag/project": "pawlocal",
                "aws:RequestTag/environment": environment,
            },
            "ForAllValues:StringEquals": {"aws:TagKeys": sorted(TAG_KEYS)},
        },
    }


def _expected_update_statement(environment: str, account_id: str) -> dict[str, Any]:
    return {
        "Sid": UPDATE_STATEMENT_SID,
        "Effect": "Allow",
        "Action": UPDATE_ACTION,
        "Resource": f"arn:aws:cloudfront::{account_id}:distribution/*",
        "Condition": {
            "StringEquals": {
                "aws:ResourceTag/project": "pawlocal",
                "aws:ResourceTag/environment": environment,
            }
        },
    }


def _matches_expected(statement: dict[str, Any], expected: dict[str, Any]) -> bool:
    if set(statement) != set(expected):
        return False
    if any(statement.get(key) != expected[key] for key in ("Sid", "Effect")):
        return False
    if _values(statement.get("Action")) != [expected["Action"]]:
        return False
    if _values(statement.get("Resource")) != [expected["Resource"]]:
        return False
    condition = statement.get("Condition")
    if not isinstance(condition, dict) or set(condition) != {"StringEquals", "ForAllValues:StringEquals"}:
        return False
    equals = condition.get("StringEquals")
    tag_keys = condition.get("ForAllValues:StringEquals")
    if not isinstance(equals, dict) or not isinstance(tag_keys, dict):
        return False
    expected_equals = expected["Condition"]["StringEquals"]
    if set(equals) != set(expected_equals):
        return False
    if any(_values(equals[key]) != [value] for key, value in expected_equals.items()):
        return False
    if set(tag_keys) != {"aws:TagKeys"} or set(_values(tag_keys["aws:TagKeys"])) != TAG_KEYS:
        return False
    return len(_values(tag_keys["aws:TagKeys"])) == len(TAG_KEYS)


def list_all(iam: Any, operation: str, role_name: str, key: str) -> list[Any]:
    result: list[Any] = []
    marker = None
    while True:
        kwargs: dict[str, Any] = {"RoleName": role_name}
        if marker:
            kwargs["Marker"] = marker
        if operation == "list_role_policies":
            response = iam.list_role_policies(**kwargs)
        elif operation == "list_attached_role_policies":
            response = iam.list_attached_role_policies(**kwargs)
        else:
            raise ValueError("Unsupported IAM inspection operation")
        page = response.get(key)
        if not isinstance(page, list):
            raise ValueError("IAM role policy listing returned an unsupported response")
        result.extend(page)
        if response.get("IsTruncated") is not True:
            return result
        next_marker = response.get("Marker")
        if not isinstance(next_marker, str) or not next_marker or next_marker == marker:
            raise ValueError("IAM role policy listing pagination is incomplete")
        marker = next_marker


def fetch_role_policy_documents(iam: Any, role_name: str) -> dict[str, dict[str, Any]]:
    expected_names = {f"{role_name}-permissions", role_name.replace("-terraform-apply", "-terraform-application-services")}
    inline_names = list_all(iam, "list_role_policies", role_name, "PolicyNames")
    if any(not isinstance(name, str) for name in inline_names) or set(inline_names) != expected_names or len(inline_names) != len(expected_names):
        raise ValueError("Apply role has missing or unexpected inline policies")
    if list_all(iam, "list_attached_role_policies", role_name, "AttachedPolicies"):
        raise ValueError("Apply role has an attached managed policy that cannot be inspected")
    documents = {}
    for name in sorted(expected_names):
        response = iam.get_role_policy(RoleName=role_name, PolicyName=name)
        if "PolicyDocument" not in response:
            raise ValueError("IAM inline policy document could not be read")
        documents[name] = parse_document(response["PolicyDocument"])
    return documents


def verify_role_tag_grant(documents: dict[str, dict[str, Any]], environment: str, account_id: str) -> None:
    expected_policy = f"pawlocal-{environment}-terraform-application-services"
    expected = _expected_statement(environment, account_id)
    matching_expected = 0
    for policy_name, document in documents.items():
        for statement in document["Statement"]:
            if statement.get("Effect") != "Allow":
                continue
            if "NotAction" in statement or "NotResource" in statement:
                raise ValueError("Apply role has a negated Allow statement whose CloudFront scope cannot be verified")
            actions = _values(statement.get("Action", []))
            if any(not isinstance(action, str) for action in actions):
                raise ValueError("Apply role policy contains a non-string action")
            if "*" in actions or any(action.casefold().startswith("cloudfront:") and "*" in action for action in actions):
                raise ValueError("Apply role has a wildcard action that could grant broader CloudFront access")
            if "cloudfront:TagResource" not in actions:
                continue
            if policy_name != expected_policy or not _matches_expected(statement, expected):
                raise ValueError("CloudFront TagResource grant does not match the exact account/environment/tag-key scope")
            matching_expected += 1
    if matching_expected != 1:
        raise ValueError("Apply role is missing the single expected CloudFront distribution tag grant")


def verify_role_update_grant(documents: dict[str, dict[str, Any]], environment: str, account_id: str) -> None:
    expected_policy = f"pawlocal-{environment}-terraform-application-services"
    expected = _expected_update_statement(environment, account_id)
    matching_expected = 0
    for policy_name, document in documents.items():
        for statement in document["Statement"]:
            if statement.get("Effect") != "Allow":
                continue
            if "NotAction" in statement or "NotResource" in statement:
                raise ValueError("Apply role has a negated Allow statement whose CloudFront scope cannot be verified")
            actions = _values(statement.get("Action", []))
            if any(not isinstance(action, str) for action in actions):
                raise ValueError("Apply role policy contains a non-string action")
            if "*" in actions or any(action.casefold().startswith("cloudfront:") and "*" in action for action in actions):
                raise ValueError("Apply role has a wildcard action that could grant broader CloudFront access")
            if UPDATE_ACTION not in actions:
                continue
            if policy_name != expected_policy or not _matches_simple_expected(statement, expected):
                raise ValueError("CloudFront UpdateDistribution grant does not match the approved account/tag scope")
            matching_expected += 1
    if matching_expected != 1:
        raise ValueError("Apply role is missing the single approved account-wide CloudFront UpdateDistribution grant")


def _matches_simple_expected(statement: dict[str, Any], expected: dict[str, Any]) -> bool:
    if set(statement) != set(expected):
        return False
    if any(statement.get(key) != expected[key] for key in ("Sid", "Effect")):
        return False
    if _values(statement.get("Action")) != [expected["Action"]]:
        return False
    if _values(statement.get("Resource")) != [expected["Resource"]]:
        return False
    condition = statement.get("Condition")
    expected_condition = expected.get("Condition")
    if not isinstance(condition, dict) or not isinstance(expected_condition, dict) or set(condition) != set(expected_condition):
        return False
    for operator, expected_values in expected_condition.items():
        actual_values = condition.get(operator)
        if not isinstance(actual_values, dict) or set(actual_values) != set(expected_values):
            return False
        if any(_values(actual_values[key]) != [value] for key, value in expected_values.items()):
            return False
    return True


def verify(iam: Any, account_id: str, environment: str = "") -> str:
    if not account_id.isdigit() or len(account_id) != 12:
        raise ValueError("AWS account ID must contain exactly 12 digits")
    if environment and environment not in ENVIRONMENTS:
        raise ValueError("Environment must be development or production")
    environments = (environment,) if environment else ENVIRONMENTS
    for role_environment in environments:
        role_name = f"pawlocal-{role_environment}-terraform-apply"
        documents = fetch_role_policy_documents(iam, role_name)
        verify_role_tag_grant(documents, role_environment, account_id)
        verify_role_update_grant(documents, role_environment, account_id)
    return "CloudFront TagResource and UpdateDistribution policies match the approved account/tag scope; cross-environment retagging and configuration risk is accepted for MVP"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--account-id", required=True)
    parser.add_argument("--region", required=True)
    parser.add_argument("--environment", choices=ENVIRONMENTS, default="")
    args = parser.parse_args()
    try:
        import boto3

        result = verify(boto3.client("iam", region_name=args.region), args.account_id, args.environment)
        print(f"Bootstrap CloudFront tagging grant verified: {result}")
    except Exception as exc:  # Do not expose IAM policy contents or AWS response details in logs.
        print(f"Bootstrap CloudFront tagging grant verification failed: {type(exc).__name__}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
