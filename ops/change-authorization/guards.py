"""Entrypoint guards and release-only machine plan enforcement for change authorization.

Protects shared deployment, Terraform, and reconciliation workflows against
unauthorized mutation or privilege escalation.
"""

from __future__ import annotations

import json
import re
from typing import Any

from candidate import is_allowed_path


class PlanViolation(Exception):
    """Raised when a planned change violates machine release-only boundaries."""


# Allowed resource types for machine incident release updates
ALLOWED_RELEASE_RESOURCES = {
    "aws_lightsail_container_service_deployment_version",
    "local_file",
    "null_resource",
}

ALLOWED_PACKAGING_ADDRESS_PATTERNS = [
    r"^(module\.[a-zA-Z0-9_-]+\.)?module\.(cognito_pre_sign_up|oncall_receiver(\[\d+\])?)\.(local_file\.archive_plan|null_resource\.archive)(\[\d+\])?$",
]

# Strictly forbidden resource types for machine remediation
FORBIDDEN_RESOURCE_PATTERNS = [
    r"^aws_iam_",
    r"^aws_cognito_",
    r"^aws_kms_",
    r"^aws_s3_",
    r"^aws_route53_",
    r"^aws_acm_",
    r"^aws_security_group",
    r"^aws_dsql_",
    r"^aws_lambda_",
]


def validate_production_promotion(
    lineage_receipt: dict[str, Any] | None,
    release_commit: str,
    backend_image: str,
    is_machine_route: bool,
) -> bool:
    """Validates that production promotion meets all prerequisites.

    For machine route: requires valid incident lineage, matching release commit,
    and verified image digest.
    For ordinary route: lineage receipt must be None and relies on protected environment approval.
    """
    if not re.fullmatch(r"[0-9a-f]{40}", release_commit):
        raise ValueError("Invalid release commit SHA")

    if not re.fullmatch(r"ghcr\.io/[a-z0-9_.-]+/[a-z0-9_.-]+@sha256:[0-9a-f]{64}", backend_image):
        raise ValueError("Invalid backend image reference")

    if is_machine_route:
        if not lineage_receipt or not isinstance(lineage_receipt, dict):
            raise ValueError("Machine production promotion requires authenticated incident lineage")
        if lineage_receipt.get("schema") != 1:
            raise ValueError("Invalid lineage receipt schema")
        if lineage_receipt.get("release_commit") != release_commit:
            raise ValueError("Lineage receipt release_commit differs from dispatch input")
        if lineage_receipt.get("backend_image") != backend_image:
            raise ValueError("Lineage receipt backend_image differs from dispatch input")
        if not lineage_receipt.get("development_verified"):
            raise ValueError("Development verification missing from lineage receipt")
        if not lineage_receipt.get("recovery_verified"):
            raise ValueError("Development recovery verification missing from lineage receipt")
        return True

    return True


def validate_release_plan_strict(plan_dict: dict[str, Any]) -> None:
    """Strictly validates a Terraform plan for machine incident release.

    Guarantees:
    - No resource deletions ('delete' in actions) unless expected replacement.
    - No unexpected resource creations.
    - Only allowed container service deployment updates/replacements and trusted
      module-local Lambda packaging sidecars are permitted.
    - No modifications to IAM, database, security groups, or secrets.
    """
    resource_changes = plan_dict.get("resource_changes", [])
    if not isinstance(resource_changes, list):
        raise PlanViolation("Plan resource_changes missing or invalid")

    for change in resource_changes:
        resource_type = change.get("type", "")
        resource_name = change.get("name", "")
        address = change.get("address", f"{resource_type}.{resource_name}")
        change_data = change.get("change", {})
        actions = change_data.get("actions", [])

        # Read-only or no-op actions are safe
        if actions == ["no-op"] or actions == ["read"]:
            continue

        # Check against forbidden patterns
        for pattern in FORBIDDEN_RESOURCE_PATTERNS:
            if re.search(pattern, resource_type):
                raise PlanViolation(
                    f"Machine incident plan cannot modify sensitive infrastructure: {resource_type}.{resource_name}"
                )

        # Allow only container service deployment version updates or approved local packaging sidecars
        if resource_type not in ALLOWED_RELEASE_RESOURCES:
            raise PlanViolation(
                f"Machine incident plan contains unapproved resource change: {resource_type}.{resource_name} (actions: {actions})"
            )

        if resource_type in ("local_file", "null_resource"):
            if not any(re.search(pat, address) for pat in ALLOWED_PACKAGING_ADDRESS_PATTERNS):
                raise PlanViolation(
                    f"Machine incident plan contains unapproved local packaging resource: {address}"
                )

        # For allowed release resources, permit create, update, or immutable replacement ({'create', 'delete'})
        expected_replacement = set(actions) == {"create", "delete"}

        # Machine route strictly prohibits resource deletion unless it is the expected replacement
        if "delete" in actions and not expected_replacement:
            raise PlanViolation(
                f"Machine incident plan cannot delete resources: {resource_type}.{resource_name}"
            )

        if actions not in (["update"], ["create"]) and not expected_replacement:
            raise PlanViolation(
                f"Disallowed action combination on release resource {resource_type}: {actions}"
            )


def main():
    import argparse
    import os
    from pathlib import Path

    parser = argparse.ArgumentParser(description="Change authorization guards")
    parser.add_argument("--mode", choices=["validate-promotion", "validate-plan"], required=True)
    parser.add_argument("--plan-file", default="", help="Path to terraform plan JSON")
    parser.add_argument("--is-machine-route", action="store_true", default=False)
    args = parser.parse_args()

    if args.mode == "validate-promotion":
        release_commit = os.environ.get("RELEASE_COMMIT", "")
        backend_image = os.environ.get("BACKEND_IMAGE", "")
        lineage_file = os.environ.get("LINEAGE_RECEIPT_FILE", "")
        lineage_receipt = None
        if lineage_file and Path(lineage_file).exists():
            lineage_receipt = json.loads(Path(lineage_file).read_text(encoding="utf-8"))
        is_machine = args.is_machine_route or bool(lineage_receipt)
        validate_production_promotion(lineage_receipt, release_commit, backend_image, is_machine)
        print("Production promotion authorization verified successfully.")

    elif args.mode == "validate-plan":
        plan_path = Path(args.plan_file)
        if not plan_path.exists():
            raise PlanViolation(f"Plan file missing at {plan_path}")
        plan_dict = json.loads(plan_path.read_text(encoding="utf-8"))
        validate_release_plan_strict(plan_dict)
        print("Strict release plan validation passed successfully.")


if __name__ == "__main__":
    main()
