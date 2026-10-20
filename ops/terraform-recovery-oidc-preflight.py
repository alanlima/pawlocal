"""Read-only guard: reject deleting the GitHub OIDC provider if a foreign role uses it."""

from __future__ import annotations

import argparse
import sys
from typing import Any

EXPECTED_URL = "https://token.actions.githubusercontent.com"
ALLOWED_ROLE_NAMES = {
    "pawlocal-frontend-github-deploy",
    "pawlocal-development-github-deploy",
    "pawlocal-production-github-deploy",
    "pawlocal-development-terraform-deploy",
    "pawlocal-production-terraform-deploy",
    "pawlocal-development-dsql-runtime",
    "pawlocal-development-terraform-plan",
    "pawlocal-development-terraform-apply",
    "pawlocal-production-terraform-plan",
    "pawlocal-production-terraform-apply",
    "pawlocal-terraform-recovery-plan",
    "pawlocal-terraform-recovery-apply",
    "pawlocal-identity-terraform-plan",
    "pawlocal-identity-terraform-apply",
}


def _contains(value: Any, target: str) -> bool:
    if isinstance(value, str):
        return target in value
    if isinstance(value, dict):
        return any(_contains(key, target) or _contains(item, target) for key, item in value.items())
    if isinstance(value, (list, tuple)):
        return any(_contains(item, target) for item in value)
    return False


def provider_arn(iam: Any) -> str:
    matches = []
    marker = None
    while True:
        args = {} if marker is None else {"Marker": marker}
        page = iam.list_open_id_connect_providers(**args)
        for provider in page.get("OpenIDConnectProviderList", []):
            arn = provider.get("Arn")
            if not isinstance(arn, str) or not arn.startswith("arn:"):
                raise ValueError("OIDC provider listing contains an invalid ARN")
            detail = iam.get_open_id_connect_provider(OpenIDConnectProviderArn=arn)
            url = detail.get("Url")
            if url == EXPECTED_URL or url == EXPECTED_URL.removeprefix("https://"):
                matches.append(arn)
        if not page.get("IsTruncated"):
            break
        marker = page.get("Marker")
        if not marker:
            raise ValueError("OIDC provider pagination is incomplete")
    if len(matches) != 1:
        raise ValueError("Expected exactly one GitHub Actions OIDC provider in the account")
    return matches[0]


def verify(iam: Any) -> tuple[str, list[str]]:
    arn = provider_arn(iam)
    used_by: list[str] = []
    marker = None
    while True:
        args = {"MaxItems": 1000} if marker is None else {"MaxItems": 1000, "Marker": marker}
        page = iam.list_roles(**args)
        for role in page.get("Roles", []):
            role_name = role.get("RoleName")
            if not isinstance(role_name, str) or not role_name:
                raise ValueError("IAM role inventory contains an invalid role name")
            policy = role.get("AssumeRolePolicyDocument")
            if not isinstance(policy, dict):
                raise ValueError("IAM role inventory omitted a trust policy")
            if _contains(policy, arn):
                used_by.append(role_name)
                if role_name not in ALLOWED_ROLE_NAMES:
                    raise ValueError("GitHub OIDC provider is trusted by a role outside the PawLocal allowlist")
        if not page.get("IsTruncated"):
            break
        marker = page.get("Marker")
        if not marker:
            raise ValueError("IAM role pagination is incomplete")
    return arn, sorted(used_by)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    try:
        import boto3

        _, roles = verify(boto3.client("iam"))
        print(f"GitHub OIDC dependency check passed; PawLocal roles found: {len(roles)}")
    except Exception as exc:
        print(f"GitHub OIDC dependency check failed closed: {type(exc).__name__}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
