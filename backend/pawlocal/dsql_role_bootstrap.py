"""Create and map the app database role as part of Terraform provisioning."""

from __future__ import annotations

import argparse
import re
import sys

from botocore.exceptions import BotoCoreError
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

_ROLE_PATTERN = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")
_APP_SCHEMA = "pawlocal"
_USER_ARN_PATTERN = re.compile(
    r"^arn:aws:iam::[0-9]{12}:user/(?:[A-Za-z0-9+=,.@_-]+/)*[A-Za-z0-9+=,.@_-]+$"
)


def ensure_app_role(engine, database_role: str, iam_user_arn: str) -> None:
    """Ensure the custom role, IAM mapping, and app schema access exist idempotently."""
    if not _ROLE_PATTERN.fullmatch(database_role):
        raise ValueError("database role has an invalid format")
    if not _USER_ARN_PATTERN.fullmatch(iam_user_arn):
        raise ValueError("IAM user ARN has an invalid format")

    with engine.begin() as connection:
        role_exists = connection.execute(
            text("SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = :role"),
            {"role": database_role},
        ).scalar_one_or_none()
    if role_exists is None:
        with engine.begin() as connection:
            connection.exec_driver_sql(f'CREATE ROLE "{database_role}" WITH LOGIN')

    with engine.begin() as connection:
        existing_mapping = connection.execute(
            text(
                "SELECT pg_role_name FROM sys.iam_pg_role_mappings "
                "WHERE arn = :iam_user_arn"
            ),
            {"iam_user_arn": iam_user_arn},
        ).scalar_one_or_none()
    if existing_mapping is None:
        with engine.begin() as connection:
            connection.exec_driver_sql(
                f"AWS IAM GRANT {database_role} TO '{iam_user_arn}'"
            )
    elif existing_mapping != database_role:
        raise RuntimeError(
            "IAM user is already mapped to a different DSQL database role"
        )

    with engine.begin() as connection:
        schema_exists = connection.execute(
            text("SELECT 1 FROM pg_catalog.pg_namespace WHERE nspname = :schema"),
            {"schema": _APP_SCHEMA},
        ).scalar_one_or_none()
    if schema_exists is None:
        with engine.begin() as connection:
            connection.exec_driver_sql(f'CREATE SCHEMA "{_APP_SCHEMA}"')

    # Aurora DSQL reserves public for admin-owned objects. Application DDL
    # belongs in a user-created schema, with privileges applied separately.
    with engine.begin() as connection:
        connection.exec_driver_sql(
            f'GRANT USAGE, CREATE ON SCHEMA "{_APP_SCHEMA}" TO "{database_role}"'
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--region", required=True)
    parser.add_argument("--database-role", required=True)
    parser.add_argument("--iam-user-arn", required=True)
    args = parser.parse_args(argv)

    try:
        if not args.endpoint.endswith(f".dsql.{args.region}.on.aws"):
            raise ValueError("DSQL endpoint does not match the selected region")
        from aurora_dsql_sqlalchemy import create_dsql_engine

        engine = create_dsql_engine(
            host=args.endpoint,
            user="admin",
            driver="psycopg",
            dbname="postgres",
            application_name="pawlocal-terraform-role-bootstrap",
            pool_pre_ping=True,
        )
        try:
            ensure_app_role(engine, args.database_role, args.iam_user_arn)
        finally:
            engine.dispose()
    except (BotoCoreError, ImportError, OSError, RuntimeError, SQLAlchemyError, ValueError) as exc:
        # Connector errors can include connection details; keep Terraform output
        # free of tokens and credential-bearing diagnostics.
        print(
            f"Aurora DSQL app-role bootstrap failed ({type(exc).__name__}).",
            file=sys.stderr,
        )
        return 1

    print(f"Configured Aurora DSQL role {args.database_role}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
