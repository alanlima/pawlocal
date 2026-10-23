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
}

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

    if not re.fullmatch(r"ghcr\.io/alanlima/pawlocal-api@sha256:[0-9a-f]{64}", backend_image):
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
    - No resource deletions ('delete' in actions).
    - No unexpected resource creations.
    - Only allowed container service deployment updates are permitted.
    - No modifications to IAM, database, security groups, or secrets.
    """
    resource_changes = plan_dict.get("resource_changes", [])
    if not isinstance(resource_changes, list):
        raise PlanViolation("Plan resource_changes missing or invalid")

    for change in resource_changes:
        resource_type = change.get("type", "")
        resource_name = change.get("name", "")
        change_data = change.get("change", {})
        actions = change_data.get("actions", [])

        # Read-only or no-op actions are safe
        if actions == ["no-op"] or actions == ["read"]:
            continue

        # Machine route strictly prohibits resource deletion
        if "delete" in actions:
            raise PlanViolation(
                f"Machine incident plan cannot delete resources: {resource_type}.{resource_name}"
            )

        # Check against forbidden patterns
        for pattern in FORBIDDEN_RESOURCE_PATTERNS:
            if re.search(pattern, resource_type):
                raise PlanViolation(
                    f"Machine incident plan cannot modify sensitive infrastructure: {resource_type}.{resource_name}"
                )

        # Allow only container service deployment version updates
        if resource_type not in ALLOWED_RELEASE_RESOURCES:
            raise PlanViolation(
                f"Machine incident plan contains unapproved resource change: {resource_type}.{resource_name} (actions: {actions})"
            )

        # For allowed resources, allow only update or create (for deployment version)
        if actions not in (["update"], ["create"]):
            raise PlanViolation(
                f"Disallowed action combination on release resource {resource_type}: {actions}"
            )
