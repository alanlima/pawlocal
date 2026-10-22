"""Load only reconciled public build/publisher settings, never stale vars context."""

from __future__ import annotations

import json
import os
from pathlib import Path

FIELDS = frozenset(
    {
        "PAWLOCAL_DEPLOY_ROLE_ARN",
        "PAWLOCAL_PUBLIC_BASE_URL",
        "PAWLOCAL_API_HEALTH_URL",
        "PAWLOCAL_FRONTEND_BUCKET",
        "PAWLOCAL_CLOUDFRONT_DISTRIBUTION_ID",
        "VITE_API_BASE_URL",
        "VITE_COGNITO_DOMAIN",
        "VITE_COGNITO_CLIENT_ID",
        "VITE_COGNITO_REDIRECT_URI",
        "VITE_COGNITO_LOGOUT_URI",
        "VITE_COGNITO_SCOPES",
    }
)


def load_public(snapshot):
    try:
        values = json.loads(snapshot)
    except (TypeError, ValueError):
        raise ValueError("Invalid public configuration snapshot") from None
    if (
        not isinstance(values, dict)
        or set(values) != FIELDS
        or any(
            not isinstance(v, str) or not v or any(c in v for c in "\r\n\x00")
            for v in values.values()
        )
    ):
        raise ValueError("Invalid public configuration snapshot")
    return values


def main():
    try:
        values = load_public(os.environ.get("RECONCILED_FRONTEND_CONFIG", ""))
        with Path(os.environ["GITHUB_ENV"]).open("a", encoding="utf-8") as output:
            output.writelines(
                f"{name}={value}\n" for name, value in sorted(values.items())
            )
    except (ValueError, KeyError, OSError):
        raise SystemExit("Cannot load verified public build configuration") from None


if __name__ == "__main__":
    main()
