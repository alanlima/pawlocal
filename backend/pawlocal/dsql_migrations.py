"""Clean-install migrations for Aurora DSQL.

This runner intentionally accepts an already configured Engine. Credential
selection is supplied by the deployment runtime and is not inferred here.
The PostgreSQL/Alembic history remains separate and unchanged.
"""

import re
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, text
from sqlalchemy.sql import Executable

BASELINE_REVISION = "dsql_0001_initial"
MAX_DML_ROWS_PER_TRANSACTION = 2999
DEFAULT_DML_BATCH_SIZE = 1000
BASELINE_DIRECTORY = (
    Path(__file__).resolve().parents[1] / "migrations" / "dsql" / "0001_initial"
)
VERSION_TABLE_DDL = """CREATE TABLE IF NOT EXISTS pawlocal_schema_version (
    revision varchar(64) PRIMARY KEY,
    applied_at timestamp with time zone NOT NULL DEFAULT now()
)"""


def _ddl_files(directory: Path = BASELINE_DIRECTORY) -> list[Path]:
    return sorted(directory.glob("*.sql"), key=lambda path: path.name)


def reject_dsql_alembic_dialect(dialect_name: str) -> None:
    """Prevent the PostgreSQL Alembic chain from running against Aurora DSQL."""
    if "auroradsql" in dialect_name.lower():
        raise RuntimeError(
            "The PostgreSQL Alembic history is unsupported on Aurora DSQL; "
            "use pawlocal.dsql_migrations.apply_dsql_baseline for clean installs."
        )


def _read_revision(engine: Engine, revision: str) -> bool:
    with engine.begin() as connection:
        result = connection.execute(
            text(
                "SELECT revision FROM pawlocal_schema_version "
                "WHERE revision = :revision"
            ),
            {"revision": revision},
        )
        return result.first() is not None


_ASYNC_INDEX_DDL = re.compile(
    r"^CREATE\s+(?P<unique>UNIQUE\s+)?INDEX\s+ASYNC\s+"
    r"(?:IF\s+NOT\s+EXISTS\s+)?(?P<name>[\w]+)\s+ON\s+"
    r"(?P<table>[\w]+)\s*\((?P<columns>[\w]+(?:\s*,\s*[\w]+)*)\)"
    r"(?:\s+WHERE\s+(?P<predicate>.+?))?\s*;?$",
    re.IGNORECASE | re.DOTALL,
)
_INDEX_DEFINITION = re.compile(
    r"^CREATE\s+(?P<unique>UNIQUE\s+)?INDEX\s+"
    r"(?:[\w\"]+\.)?[\"]?(?P<name>[\w]+)[\"]?\s+ON\s+"
    r"(?:[\w\"]+\.)?[\"]?(?P<table>[\w]+)[\"]?\s+"
    r"USING\s+(?P<method>[\w]+)\s+"
    r"\((?P<columns>[\w\"]+(?:\s*,\s*[\w\"]+)*)\)"
    r"(?:\s+WHERE\s+(?P<predicate>.+?))?\s*$",
    re.IGNORECASE | re.DOTALL,
)


def _normalize_index_expression(expression: str | None) -> str | None:
    if expression is None:
        return None
    normalized = re.sub(
        r"::\s*(?:character\s+varying|varchar|text|boolean|integer|uuid)"
        r"(?:\s*\(\s*\d+\s*\))?",
        "",
        expression,
        flags=re.IGNORECASE,
    )
    return re.sub(r"[\s()\"]+", "", normalized).lower()


def _verify_async_index(engine: Engine, statement: str) -> None:
    expected = _ASYNC_INDEX_DDL.match(statement.strip())
    if expected is None:
        raise RuntimeError(f"Cannot verify Aurora DSQL async index DDL: {statement}")

    expected_name = expected.group("name")
    with engine.begin() as connection:
        row = connection.execute(
            text(
                "SELECT index_class.relname, table_class.relname, "
                "index_data.indisvalid, index_data.indisunique, "
                "pg_catalog.pg_get_indexdef(index_data.indexrelid) "
                "FROM pg_catalog.pg_index AS index_data "
                "JOIN pg_catalog.pg_class AS index_class "
                "ON index_class.oid = index_data.indexrelid "
                "JOIN pg_catalog.pg_class AS table_class "
                "ON table_class.oid = index_data.indrelid "
                "JOIN pg_catalog.pg_namespace AS index_namespace "
                "ON index_namespace.oid = index_class.relnamespace "
                "WHERE index_class.relname = :index_name "
                "AND table_class.relname = :table_name "
                "AND index_namespace.nspname = current_schema()"
            ),
            {"index_name": expected_name, "table_name": expected.group("table")},
        ).first()

    if row is None:
        raise RuntimeError(
            f"Aurora DSQL returned no job id and index {expected_name!r} is absent"
        )
    index_name, table_name, is_valid, is_unique, actual_definition = row
    actual = _INDEX_DEFINITION.match(actual_definition)
    if actual is None:
        raise RuntimeError(
            f"Could not inspect Aurora DSQL index definition for {expected_name!r}"
        )

    expected_columns = _normalize_index_expression(expected.group("columns"))
    actual_columns = _normalize_index_expression(actual.group("columns"))
    expected_predicate = _normalize_index_expression(expected.group("predicate"))
    actual_predicate = _normalize_index_expression(actual.group("predicate"))
    expected_unique = expected.group("unique") is not None
    if (
        index_name != expected_name
        or table_name != expected.group("table")
        or not is_valid
        or bool(is_unique) != expected_unique
        or actual.group("name") != expected_name
        or actual.group("table") != expected.group("table")
        or actual.group("method").lower() != "btree_index"
        or actual_columns != expected_columns
        or actual_predicate != expected_predicate
    ):
        raise RuntimeError(
            f"Aurora DSQL index {expected_name!r} is invalid or differs from "
            "the requested baseline definition"
        )


def _execute_one_ddl(engine: Engine, statement: str) -> None:
    is_async_index = statement.lstrip().upper().startswith(
        ("CREATE INDEX ASYNC", "CREATE UNIQUE INDEX ASYNC")
    )
    with engine.connect() as connection:
        with connection.begin():
            result = connection.execute(text(statement))
            # IF NOT EXISTS can produce no row when a prior interrupted run
            # already created the index. In that case there is no job to wait
            # for, and the next idempotent migration statement can proceed.
            job_id = result.scalar_one_or_none() if is_async_index else None
        if job_id:
            # Aurora DSQL requires wait_for_job to run outside a transaction
            # block, so use a fresh autocommit connection for the procedure.
            with engine.connect() as wait_connection:
                wait_connection = wait_connection.execution_options(
                    isolation_level="AUTOCOMMIT"
                )
                wait_result = wait_connection.execute(
                    text("CALL sys.wait_for_job(:job_id)"), {"job_id": job_id}
                )
                completed = wait_result.scalar_one()
                if completed is not True:
                    raise RuntimeError("Aurora DSQL index build did not complete")
        if is_async_index:
            # A retry of CREATE INDEX IF NOT EXISTS may return no job even if
            # the prior asynchronous build left an invalid or wrong index.
            # Inspect the catalog before treating that DDL as complete.
            _verify_async_index(engine, statement)


def apply_dsql_baseline(
    engine: Engine, *, directory: Path = BASELINE_DIRECTORY
) -> bool:
    """Apply the idempotent DSQL clean-install schema and return whether applied.

    Every table/index statement runs in its own committed DDL transaction.
    Async indexes are awaited before the next migration operation. The version
    ledger insert is issued only after all DDL and index jobs have completed.
    """
    _execute_one_ddl(engine, VERSION_TABLE_DDL)
    if _read_revision(engine, BASELINE_REVISION):
        return False

    migration_files = _ddl_files(directory)
    if not migration_files:
        raise RuntimeError(f"No DSQL migration statements found in {directory}")
    for migration_file in migration_files:
        statement = migration_file.read_text(encoding="utf-8").strip()
        if not statement:
            raise RuntimeError(f"Empty DSQL migration statement: {migration_file.name}")
        _execute_one_ddl(engine, statement)

    # DML must be in a separate transaction from every DDL statement.
    with engine.begin() as connection:
        connection.execute(
            text("INSERT INTO pawlocal_schema_version (revision) VALUES (:revision)"),
            {"revision": BASELINE_REVISION},
        )
    return True


def execute_bounded_dml_batches(
    engine: Engine,
    statements: Iterable[tuple[Executable, Mapping[str, Any]]],
    *,
    batch_size: int = DEFAULT_DML_BATCH_SIZE,
) -> int:
    """Run single-row DML statements in transactions below DSQL's row limit.

    Callers must supply statements that target at most one row each. The helper
    verifies affected-row counts when the driver reports them and caps each
    transaction below DSQL's 3,000 modified-row ceiling.
    """
    if not 1 <= batch_size <= MAX_DML_ROWS_PER_TRANSACTION:
        raise ValueError(
            f"batch_size must be between 1 and {MAX_DML_ROWS_PER_TRANSACTION}"
        )

    pending: list[tuple[Executable, Mapping[str, Any]]] = []
    total = 0

    def flush() -> None:
        nonlocal total
        if not pending:
            return
        changed = 0
        with engine.begin() as connection:
            for statement, parameters in pending:
                result = connection.execute(statement, parameters)
                if result.rowcount < 0 or result.rowcount > 1:
                    raise RuntimeError(
                        "DSQL migration DML must report at most one changed row per statement"
                    )
                changed += result.rowcount
                if changed > MAX_DML_ROWS_PER_TRANSACTION:
                    raise RuntimeError("DSQL migration batch exceeds the row limit")
        total += changed
        pending.clear()

    for statement in statements:
        pending.append(statement)
        if len(pending) == batch_size:
            flush()
    flush()
    return total
