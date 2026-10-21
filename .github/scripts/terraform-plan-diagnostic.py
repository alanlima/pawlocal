#!/usr/bin/env python3
"""Print a small, opt-in, redacted Terraform failure summary for GitHub Actions."""

from __future__ import annotations

import argparse
import os
import pathlib
import re


PHASE_MESSAGES = {
    "apply": "Terraform apply failed; raw provider output was withheld.",
    "plan": "Terraform planning failed; raw provider output was withheld.",
}

ALLOWED_AWS_OPERATIONS = {
    "CloudFront": {
        "CreateDistributionWithTags",
        "CreateFunction",
        "CreateOriginAccessControl",
        "DescribeFunction",
        "GetDistribution",
        "GetOriginAccessControl",
        "PublishFunction",
        "UpdateDistribution",
        "UpdateOriginAccessControl",
    },
    "Cognito Identity Provider": {
        "CreateUserPool",
        "CreateUserPoolClient",
        "CreateUserPoolDomain",
        "DescribeUserPool",
        "DescribeUserPoolClient",
        "DescribeUserPoolDomain",
    },
    "DSQL": {"CreateCluster", "GetCluster"},
    "IAM": {
        "AttachRolePolicy",
        "CreatePolicy",
        "GetPolicy",
        "GetPolicyVersion",
        "ListAttachedRolePolicies",
    },
    "Lightsail": {
        "CreateCertificate",
        "CreateContainerService",
        "GetCertificates",
        "GetContainerServices",
    },
    "Route 53": {"ChangeResourceRecordSets", "GetChange"},
    "S3": {
        "CreateBucket",
        "DeleteBucket",
        "GetBucketEncryption",
        "GetBucketOwnershipControls",
        "GetBucketPolicy",
        "GetBucketTagging",
        "GetPublicAccessBlock",
        "HeadBucket",
        "PutBucketEncryption",
        "PutBucketOwnershipControls",
        "PutBucketPolicy",
        "PutBucketTagging",
        "PutPublicAccessBlock",
    },
    "STS": {"GetCallerIdentity"},
}

ALLOWED_AWS_ERROR_CODES = {
    "AccessDenied",
    "AccessDeniedException",
    "AuthorizationError",
    "BucketAlreadyExists",
    "BucketAlreadyOwnedByYou",
    "ConflictException",
    "EntityAlreadyExists",
    "ExpiredToken",
    "InternalError",
    "InvalidClientTokenId",
    "InvalidParameter",
    "InvalidParameterException",
    "LimitExceeded",
    "MalformedPolicyDocument",
    "NoSuchBucket",
    "NoSuchEntity",
    "NotFoundException",
    "OperationAborted",
    "RequestTimeout",
    "ResourceAlreadyExistsException",
    "ServiceUnavailable",
    "Throttling",
    "ThrottlingException",
    "TooManyRequestsException",
    "UnauthorizedOperation",
    "ValidationException",
}

ALLOWED_TERRAFORM_FILES = {
    "environment_permissions.tf",
    "iam.tf",
    "identity_permissions.tf",
    "identity_roles.tf",
    "main.tf",
    "outputs.tf",
    "variables.tf",
    "versions.tf",
}


def generic_explanation(text: str) -> str | None:
    """Return only a fixed explanation for a recognized provider failure class."""
    lowered = text.lower()
    if "accessdenied" in lowered or "not authorized" in lowered or "unauthorized" in lowered:
        return "The provider request was not authorized."
    if "timeout" in lowered or "timed out" in lowered or "waiting for" in lowered:
        return "Terraform timed out while waiting for the resource operation."
    if "throttl" in lowered or "toomanyrequests" in lowered:
        return "The provider request was throttled."
    if "alreadyexists" in lowered or "already exists" in lowered:
        return "The requested resource already exists."
    if "conflict" in lowered:
        return "The provider reported a conflicting resource state."
    return None


def print_sanitized_diagnostics(text: str) -> None:
    fields_printed = 0

    operation = re.search(r"operation error\s+([^:\r\n]{1,40}):\s*([A-Za-z0-9]{1,64})", text)
    if operation:
        service = operation.group(1).strip()
        action = operation.group(2)
        if action in ALLOWED_AWS_OPERATIONS.get(service, set()):
            print(f"AWS operation: {service} {action}")
            fields_printed += 1

    error_code = re.search(r"api error\s+([A-Za-z][A-Za-z0-9._-]{0,63})", text)
    if error_code and error_code.group(1) in ALLOWED_AWS_ERROR_CODES:
        print(f"AWS error code: {error_code.group(1)}")
        fields_printed += 1

    status_code = re.search(r"StatusCode:\s*(\d{3})", text)
    if status_code and 400 <= int(status_code.group(1)) <= 599:
        print(f"HTTP status: {int(status_code.group(1))}")
        fields_printed += 1

    explanation = generic_explanation(text)
    if explanation:
        print(f"Explanation: {explanation}")
        fields_printed += 1

    location = re.search(r"(?m)^\s+on\s+([^\s]+)\s+line\s+(\d+),", text)
    if location:
        filename = pathlib.PurePosixPath(location.group(1)).name
        line_number = int(location.group(2))
        if filename in ALLOWED_TERRAFORM_FILES and 1 <= line_number <= 99999:
            print(f"Configuration file: {filename}:{line_number}")
            fields_printed += 1

    if fields_printed == 0:
        print("No allowlisted diagnostic fields were found; provider details were withheld.")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("log", type=pathlib.Path)
    parser.add_argument("--phase", choices=sorted(PHASE_MESSAGES), required=True)
    args = parser.parse_args()

    print(PHASE_MESSAGES[args.phase])
    if os.environ.get("PAWLOCAL_TERRAFORM_DIAGNOSTIC_LOGS") != "true":
        return 0

    try:
        text = args.log.read_text(encoding="utf-8", errors="replace")
    except OSError:
        print("Terraform diagnostic log unavailable; provider details were withheld.")
        return 0

    print_sanitized_diagnostics(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
