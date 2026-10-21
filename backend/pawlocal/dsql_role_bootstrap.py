"""Create, map, and verify an application role for Terraform DSQL setup."""

from __future__ import annotations

import re

from sqlalchemy import text

_ROLE_PATTERN = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")
_APP_SCHEMA = "pawlocal"
_PRINCIPAL_ARN_PATTERN = re.compile(
    r"^arn:aws:iam::[0-9]{12}:(?:user|role)/(?:[A-Za-z0-9+=,.@_-]+/)*[A-Za-z0-9+=,.@_-]+$"
)


class DSQLRolePostconditionError(RuntimeError):
    """The application database role is absent or unsafe."""


class DSQLMappingPostconditionError(RuntimeError):
    """The runtime IAM mapping is absent, ambiguous, or cross-role."""


class DSQLSchemaGrantPostconditionError(RuntimeError):
    """The application schema grants are missing or too broad."""


def ensure_app_role(
    engine,
    database_role: str,
    iam_principal_arn: str,
) -> None:
    """Ensure the custom role, singleton IAM mapping, and schema grants."""
    if not _ROLE_PATTERN.fullmatch(database_role):
        raise ValueError("database role has an invalid format")
    if not _PRINCIPAL_ARN_PATTERN.fullmatch(iam_principal_arn):
        raise ValueError("IAM principal ARN has an invalid format")

    with engine.begin() as connection:
        role_can_login = connection.execute(
            text("SELECT rolcanlogin FROM pg_catalog.pg_roles WHERE rolname = :role"),
            {"role": database_role},
        ).scalar_one_or_none()
    if role_can_login is None:
        with engine.begin() as connection:
            connection.exec_driver_sql(f'CREATE ROLE "{database_role}" WITH LOGIN')
    elif role_can_login is not True:
        raise DSQLRolePostconditionError(
            "application database role exists without LOGIN"
        )

    with engine.begin() as connection:
        role_principals = (
            connection.execute(
                text(
                    "SELECT arn FROM sys.iam_pg_role_mappings "
                    "WHERE pg_role_name = :role ORDER BY arn"
                ),
                {"role": database_role},
            )
            .scalars()
            .all()
        )
        principal_roles = (
            connection.execute(
                text(
                    "SELECT pg_role_name FROM sys.iam_pg_role_mappings "
                    "WHERE arn = :iam_user_arn ORDER BY pg_role_name"
                ),
                {"iam_user_arn": iam_principal_arn},
            )
            .scalars()
            .all()
        )
    if not role_principals and not principal_roles:
        with engine.begin() as connection:
            connection.exec_driver_sql(
                f"AWS IAM GRANT {database_role} TO '{iam_principal_arn}'"
            )
    elif role_principals != [iam_principal_arn] or principal_roles != [database_role]:
        raise DSQLMappingPostconditionError(
            "application role or runtime IAM principal has a missing, duplicate, "
            "or competing mapping"
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

    verify_app_role(engine, database_role, iam_principal_arn)


def verify_app_role(engine, database_role: str, iam_principal_arn: str) -> None:
    """Fail closed unless the role, singleton mapping, and grants are exact."""
    with engine.begin() as connection:
        role_can_login = connection.execute(
            text("SELECT rolcanlogin FROM pg_catalog.pg_roles WHERE rolname = :role"),
            {"role": database_role},
        ).scalar_one_or_none()
        role_principals = (
            connection.execute(
                text(
                    "SELECT arn FROM sys.iam_pg_role_mappings "
                    "WHERE pg_role_name = :role ORDER BY arn"
                ),
                {"role": database_role},
            )
            .scalars()
            .all()
        )
        principal_roles = (
            connection.execute(
                text(
                    "SELECT pg_role_name FROM sys.iam_pg_role_mappings "
                    "WHERE arn = :iam_user_arn ORDER BY pg_role_name"
                ),
                {"iam_user_arn": iam_principal_arn},
            )
            .scalars()
            .all()
        )
        grants = connection.execute(
            text(
                "SELECT "
                "has_schema_privilege(:role, :schema, 'USAGE'), "
                "has_schema_privilege(:role, :schema, 'CREATE')"
            ),
            {"role": database_role, "schema": _APP_SCHEMA},
        ).one()
        public_grants = connection.execute(
            text(
                "SELECT "
                "EXISTS ("
                "SELECT 1 FROM pg_catalog.pg_namespace AS schema_data "
                "CROSS JOIN LATERAL pg_catalog.aclexplode("
                "COALESCE(schema_data.nspacl, "
                "pg_catalog.acldefault('n', schema_data.nspowner))"
                ") AS privilege_data "
                "WHERE schema_data.nspname = :schema "
                "AND privilege_data.grantee = 0 "
                "AND privilege_data.privilege_type = 'USAGE'"
                "), "
                "EXISTS ("
                "SELECT 1 FROM pg_catalog.pg_namespace AS schema_data "
                "CROSS JOIN LATERAL pg_catalog.aclexplode("
                "COALESCE(schema_data.nspacl, "
                "pg_catalog.acldefault('n', schema_data.nspowner))"
                ") AS privilege_data "
                "WHERE schema_data.nspname = :schema "
                "AND privilege_data.grantee = 0 "
                "AND privilege_data.privilege_type = 'CREATE'"
                ")"
            ),
            {"schema": _APP_SCHEMA},
        ).one()

    if role_can_login is not True:
        raise DSQLRolePostconditionError(
            "application database role is absent or cannot login"
        )
    if role_principals != [iam_principal_arn] or principal_roles != [database_role]:
        raise DSQLMappingPostconditionError(
            "application database role does not have one exact IAM mapping"
        )
    usage, create = grants
    public_usage, public_create = public_grants
    if usage is not True or create is not True:
        raise DSQLSchemaGrantPostconditionError(
            "application database role is missing required schema grants"
        )
    if public_usage is True or public_create is True:
        raise DSQLSchemaGrantPostconditionError(
            "application schema grants access to PUBLIC"
        )
