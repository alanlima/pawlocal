"""Protected Terraform post-apply setup for the PawLocal Aurora DSQL catalog."""

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass

from sqlalchemy import event

from pawlocal.dsql_migrate import run_dsql_migrations
from pawlocal.dsql_migrations import verify_dsql_baseline
from pawlocal.dsql_role_bootstrap import ensure_app_role
from pawlocal.infrastructure.aws_credentials import (
    create_assume_role_credentials_provider,
)

_REGION_PATTERN = re.compile(r"^[a-z]{2}(?:-gov)?-[a-z]+-\d$")
_ENDPOINT_PATTERN = re.compile(
    r"^[a-z0-9]+\.dsql\.(?P<region>[a-z]{2}(?:-gov)?-[a-z]+-\d)\.on\.aws$"
)


@dataclass(frozen=True)
class SetupConfiguration:
    environment: str
    endpoint: str
    region: str
    database_role: str
    runtime_role_arn: str

    @classmethod
    def from_environment(cls) -> SetupConfiguration:
        names = {
            "environment": "PAWLOCAL_DSQL_SETUP_ENVIRONMENT",
            "endpoint": "PAWLOCAL_DSQL_SETUP_ENDPOINT",
            "region": "PAWLOCAL_DSQL_SETUP_REGION",
            "database_role": "PAWLOCAL_DSQL_SETUP_DATABASE_ROLE",
            "runtime_role_arn": "PAWLOCAL_DSQL_SETUP_RUNTIME_ROLE_ARN",
        }
        values = {
            field: os.environ.get(name, "").strip() for field, name in names.items()
        }
        if any(not value for value in values.values()):
            raise ValueError("protected DSQL setup configuration is incomplete")
        configuration = cls(**values)
        configuration.validate()
        return configuration

    def validate(self) -> None:
        if self.environment not in {"development", "production"}:
            raise ValueError("protected DSQL setup environment is invalid")
        if not _REGION_PATTERN.fullmatch(self.region):
            raise ValueError("protected DSQL setup region is invalid")
        endpoint = _ENDPOINT_PATTERN.fullmatch(self.endpoint)
        if endpoint is None or endpoint.group("region") != self.region:
            raise ValueError("protected DSQL setup endpoint does not match its region")
        if self.database_role != f"pawlocal_{self.environment}_app":
            raise ValueError("protected DSQL setup database role is cross-environment")
        runtime_pattern = re.compile(
            rf"^arn:aws:iam::(?P<account>[0-9]{{12}}):role/"
            rf"pawlocal-{re.escape(self.environment)}-dsql-runtime$"
        )
        if runtime_pattern.fullmatch(self.runtime_role_arn) is None:
            raise ValueError("protected DSQL setup runtime role is cross-environment")

    @property
    def account_id(self) -> str:
        return self.runtime_role_arn.split(":", 5)[4]


def validate_apply_identity(configuration: SetupConfiguration, caller_arn: str) -> None:
    expected = re.compile(
        rf"^arn:aws:sts::{configuration.account_id}:assumed-role/"
        rf"pawlocal-{re.escape(configuration.environment)}-terraform-apply/[^/]+$"
    )
    if expected.fullmatch(caller_arn) is None:
        raise RuntimeError(
            "DSQL setup is not running as the matching protected apply role"
        )


def _set_application_search_path(connection) -> None:
    get_execution_options = getattr(connection, "get_execution_options", None)
    if (
        get_execution_options
        and get_execution_options().get("isolation_level") == "AUTOCOMMIT"
    ):
        return
    connection.exec_driver_sql("SET LOCAL search_path TO pawlocal")


def execute_setup(
    configuration: SetupConfiguration, admin_engine, application_engine
) -> None:
    """Run the admin and application phases, then verify every postcondition."""
    ensure_app_role(
        admin_engine,
        configuration.database_role,
        configuration.runtime_role_arn,
    )
    run_dsql_migrations(application_engine)
    verify_dsql_baseline(
        application_engine,
        expected_owner=configuration.database_role,
    )


def _create_engines(configuration: SetupConfiguration):
    import certifi
    from aurora_dsql_sqlalchemy import create_dsql_engine

    admin_engine = create_dsql_engine(
        host=configuration.endpoint,
        user="admin",
        driver="psycopg",
        dbname="postgres",
        sslmode="verify-full",
        sslrootcert=certifi.where(),
        application_name="pawlocal-terraform-dsql-admin",
        pool_pre_ping=True,
    )
    provider = create_assume_role_credentials_provider(configuration.runtime_role_arn)
    application_engine = create_dsql_engine(
        host=configuration.endpoint,
        user=configuration.database_role,
        driver="psycopg",
        dbname="postgres",
        sslmode="verify-full",
        sslrootcert=certifi.where(),
        application_name="pawlocal-terraform-dsql-baseline",
        connect_args={"custom_credentials_provider": provider},
        pool_pre_ping=True,
    )
    event.listen(application_engine, "begin", _set_application_search_path)
    return admin_engine, application_engine


def main() -> int:
    phase = "configuration"
    admin_engine = None
    application_engine = None
    environment = "unknown"
    try:
        configuration = SetupConfiguration.from_environment()
        environment = configuration.environment

        phase = "identity"
        import boto3

        caller_arn = boto3.client("sts").get_caller_identity()["Arn"]
        validate_apply_identity(configuration, caller_arn)

        phase = "connection"
        admin_engine, application_engine = _create_engines(configuration)

        phase = "admin"
        ensure_app_role(
            admin_engine,
            configuration.database_role,
            configuration.runtime_role_arn,
        )

        phase = "application"
        run_dsql_migrations(application_engine)
        verify_dsql_baseline(
            application_engine,
            expected_owner=configuration.database_role,
        )
    except Exception as exc:  # noqa: BLE001 - output must remain sanitized
        print(
            "Aurora DSQL protected setup failed "
            f"(environment={environment}, phase={phase}, class={type(exc).__name__}).",
            file=sys.stderr,
        )
        return 1
    finally:
        if application_engine is not None:
            application_engine.dispose()
        if admin_engine is not None:
            admin_engine.dispose()

    print(
        "Aurora DSQL protected setup completed "
        f"(environment={environment}, phases=admin,application,postconditions)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
