"""Refreshable AWS credentials for the Aurora DSQL runtime."""

from __future__ import annotations

from threading import Lock
from typing import Any

from botocore.credentials import CredentialProvider, RefreshableCredentials


class AssumeRoleCredentialProvider(CredentialProvider):
    """Assume a customer-account role using the Lightsail runtime identity.

    The DSQL connector creates a new Botocore session for each connection. This
    provider keeps one refreshable role credential object so SDK token generation
    transparently refreshes STS credentials rather than assuming a role on every
    database connection.
    """

    METHOD = "pawlocal-assume-role"
    CANONICAL_NAME = "custom:pawlocal-assume-role"

    def __init__(self, role_arn: str, source_session: Any | None = None) -> None:
        super().__init__()
        self._role_arn = role_arn
        if source_session is None:
            import boto3

            source_session = boto3.Session()
        self._source_session = source_session
        self._credentials: RefreshableCredentials | None = None
        self._lock = Lock()

    def load(self) -> RefreshableCredentials:
        with self._lock:
            if self._credentials is None:
                self._credentials = RefreshableCredentials.create_from_metadata(
                    metadata=self._assume_role(),
                    refresh_using=self._assume_role,
                    method=self.METHOD,
                )
            return self._credentials

    def _assume_role(self) -> dict[str, str]:
        response = self._source_session.client("sts").assume_role(
            RoleArn=self._role_arn,
            RoleSessionName="pawlocal-dsql-runtime",
        )
        credentials = response["Credentials"]
        return {
            "access_key": credentials["AccessKeyId"],
            "secret_key": credentials["SecretAccessKey"],
            "token": credentials["SessionToken"],
            "expiry_time": credentials["Expiration"].isoformat(),
        }


def create_assume_role_credentials_provider(role_arn: str) -> CredentialProvider:
    """Create a provider that assumes ``role_arn`` from the default AWS chain."""
    if not role_arn.startswith("arn:aws:iam::") or ":role/" not in role_arn:
        raise ValueError("DSQL assume-role ARN must identify an IAM role")
    return AssumeRoleCredentialProvider(role_arn)
