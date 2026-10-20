#!/usr/bin/env python3
"""Verify that Lightsail reports the Terraform-selected container image active."""

from __future__ import annotations

import argparse
import re


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--environment", choices=("development", "production"), required=True)
    parser.add_argument("--image", required=True)
    args = parser.parse_args()

    if not re.fullmatch(r"ghcr\.io/alanlima/pawlocal-api@sha256:[0-9a-f]{64}", args.image):
        raise SystemExit("Selected image must be a digest-pinned PawLocal API image")

    try:
        import boto3
    except ImportError as exc:
        raise SystemExit("boto3 is required for Lightsail deployment verification") from exc

    service_name = f"pawlocal-{args.environment}-api"
    response = boto3.client("lightsail").get_container_services(serviceName=service_name)
    services = response.get("containerServices", [])
    if len(services) != 1:
        raise SystemExit("Lightsail did not return the selected environment's container service")

    service = services[0]
    deployment = service.get("currentDeployment") or {}
    containers = deployment.get("containers") or {}
    container = containers.get("pawlocal-api") or {}
    if service.get("state") != "RUNNING" or deployment.get("state") != "ACTIVE":
        raise SystemExit("Lightsail service does not report a running active deployment")
    if container.get("image") != args.image:
        raise SystemExit("Lightsail active deployment image does not match the selected release digest")
    print(f"Verified active Lightsail {args.environment} service image digest")


if __name__ == "__main__":
    main()
