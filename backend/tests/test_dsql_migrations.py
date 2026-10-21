import re
from contextlib import contextmanager

import pytest
from sqlalchemy import text

from pawlocal.dsql_migrations import (
    BASELINE_DIRECTORY,
    BASELINE_REVISION,
    apply_dsql_baseline,
    execute_bounded_dml_batches,
    reject_dsql_alembic_dialect,
    verify_dsql_baseline,
)


class _Scalars:
    def __init__(self, values):
        self.values = values

    def all(self):
        return self.values


class _Result:
    def __init__(self, value=None, rowcount=0, scalar_values=None):
        self.value = value
        self.rowcount = rowcount
        self.scalar_values = scalar_values

    def first(self):
        if isinstance(self.value, tuple):
            return self.value
        return (self.value,) if self.value is not None else None

    def scalar_one(self):
        return self.value

    def scalar_one_or_none(self):
        return self.value

    def scalars(self):
        return _Scalars(self.scalar_values)


class _Connection:
    def __init__(self, engine):
        self.engine = engine
        self.transaction_id = None

    def execution_options(self, **_options):
        return self

    @contextmanager
    def begin(self):
        self.transaction_id = self.engine.new_transaction()
        yield self
        self.transaction_id = None

    def execute(self, statement, parameters=None):
        sql = str(statement).strip()
        self.engine.operations.append((self.transaction_id, sql, parameters or {}))
        upper = sql.upper()
        if upper == "SELECT REVISION FROM PAWLOCAL_SCHEMA_VERSION ORDER BY REVISION":
            return _Result(
                scalar_values=[BASELINE_REVISION]
                if self.engine.revision_applied
                else []
            )
        if upper.startswith("SELECT REVISION"):
            value = BASELINE_REVISION if self.engine.revision_applied else None
            return _Result(value)
        if "PG_CATALOG.PG_CLASS AS TABLE_DATA" in upper:
            return _Result(
                self.engine.table_owners.get((parameters or {}).get("table_name"))
            )
        if "PG_CATALOG.PG_INDEX" in upper:
            return _Result(
                self.engine.index_records.get((parameters or {}).get("index_name"))
            )
        if upper.startswith(("CREATE INDEX ASYNC", "CREATE UNIQUE INDEX ASYNC")):
            match = re.match(
                r"CREATE\s+(UNIQUE\s+)?INDEX\s+ASYNC\s+"
                r"(?:IF\s+NOT\s+EXISTS\s+)?(\w+)\s+ON\s+(\w+)\s+"
                r"\(([^)]+)\)(?:\s+WHERE\s+(.+?))?;?$",
                sql,
                re.IGNORECASE,
            )
            if match:
                unique, name, table, columns, predicate = match.groups()
                definition = (
                    f"CREATE {'UNIQUE ' if unique else ''}INDEX {name} ON public.{table} "
                    f"USING btree_index ({columns})"
                )
                if predicate:
                    definition += f" WHERE {predicate.rstrip(';')}"
                self.engine.index_records[name] = (
                    name,
                    table,
                    True,
                    bool(unique),
                    definition,
                    self.engine.index_owner,
                )
            self.engine.job_counter += 1
            return _Result(f"job-{self.engine.job_counter}")
        if upper.startswith("CALL SYS.WAIT_FOR_JOB"):
            return _Result(True)
        if upper.startswith("INSERT INTO PAWLOCAL_SCHEMA_VERSION"):
            self.engine.revision_applied = True
            return _Result(rowcount=1)
        return _Result(rowcount=(parameters or {}).get("changed_rows", 0))


class _Engine:
    def __init__(self):
        self.operations = []
        self.revision_applied = False
        self.job_counter = 0
        self.transaction_counter = 0
        self.index_records = {}
        self.table_owners = {}
        self.index_owner = "pawlocal_development_app"

    def new_transaction(self):
        self.transaction_counter += 1
        return self.transaction_counter

    @contextmanager
    def begin(self):
        connection = _Connection(self)
        with connection.begin():
            yield connection

    @contextmanager
    def connect(self):
        yield _Connection(self)


def test_dsql_initial_schema_is_final_shape_and_has_one_statement_per_file():
    statements = [
        path.read_text(encoding="utf-8").strip()
        for path in sorted(BASELINE_DIRECTORY.glob("*.sql"))
    ]
    assert len(statements) >= 10
    for statement in statements:
        assert statement.endswith(";")
        assert statement.count(";") == 1
    all_sql = "\n".join(statements).upper()
    assert "PLACE_FACILITIES" in all_sql
    assert "ARRAY" not in all_sql
    assert "UNNEST" not in all_sql
    assert "!~" not in all_sql
    assert "TARGET_CONTRIBUTION_ID" in all_sql
    assert "CREATE INDEX ASYNC" in all_sql
    assert "CREATE UNIQUE INDEX ASYNC" in all_sql
    assert "ORDINAL INTEGER NOT NULL CHECK (ORDINAL >= 0)" in all_sql


def test_executable_dsql_migration_command_applies_only_to_dsql():
    from types import SimpleNamespace

    from pawlocal.dsql_migrate import run_dsql_migrations

    engine = _Engine()
    engine.dialect = SimpleNamespace(name="auroradsql")
    assert run_dsql_migrations(engine)
    assert not run_dsql_migrations(engine)

    engine.dialect = SimpleNamespace(name="postgresql")
    with pytest.raises(RuntimeError, match="requires an Aurora DSQL database URL"):
        run_dsql_migrations(engine)


def test_dsql_baseline_commits_one_ddl_each_waits_indexes_then_records_revision():
    engine = _Engine()

    assert apply_dsql_baseline(engine)

    transactions = {}
    for transaction_id, statement, _parameters in engine.operations:
        transactions.setdefault(transaction_id, []).append(statement)
    for statements in transactions.values():
        ddl_statements = [
            statement
            for statement in statements
            if statement.upper().startswith(
                ("CREATE TABLE", "CREATE INDEX", "CREATE UNIQUE INDEX")
            )
        ]
        assert len(ddl_statements) <= 1

    for index, (_tx, statement, _parameters) in enumerate(engine.operations):
        if statement.upper().startswith(
            ("CREATE INDEX ASYNC", "CREATE UNIQUE INDEX ASYNC")
        ):
            wait_tx, wait_statement, _ = engine.operations[index + 1]
            assert wait_statement.upper().startswith("CALL SYS.WAIT_FOR_JOB")
            assert wait_tx != _tx

    assert (
        engine.operations[-1][1]
        .upper()
        .startswith("INSERT INTO PAWLOCAL_SCHEMA_VERSION")
    )
    assert engine.revision_applied


def test_dsql_baseline_rerun_skips_schema_after_version_recorded():
    engine = _Engine()
    engine.revision_applied = True

    assert not apply_dsql_baseline(engine)
    assert [
        operation[1]
        for operation in engine.operations
        if operation[1].upper().startswith("CREATE TABLE")
    ]
    assert not any(
        "CREATE INDEX" in operation[1].upper() for operation in engine.operations
    )
    assert not any(
        operation[1].upper().startswith("INSERT INTO PAWLOCAL_SCHEMA_VERSION")
        for operation in engine.operations
    )


def test_dsql_baseline_postconditions_verify_revision_tables_owners_and_indexes():
    engine = _Engine()
    owner = "pawlocal_development_app"

    assert apply_dsql_baseline(engine)
    engine.table_owners = {
        "pawlocal_schema_version": owner,
        "places": owner,
        "place_facilities": owner,
        "contributions": owner,
        "favourites": owner,
        "reports": owner,
    }

    verify_dsql_baseline(engine, expected_owner=owner)


def test_dsql_baseline_postconditions_reject_wrong_table_owner():
    engine = _Engine()
    owner = "pawlocal_development_app"
    engine.revision_applied = True
    engine.table_owners = {
        "pawlocal_schema_version": owner,
        "places": "admin",
        "place_facilities": owner,
        "contributions": owner,
        "favourites": owner,
        "reports": owner,
    }

    with pytest.raises(RuntimeError, match="unexpected owner"):
        verify_dsql_baseline(engine, expected_owner=owner)


def test_dsql_baseline_postconditions_reject_wrong_index_owner():
    engine = _Engine()
    owner = "pawlocal_development_app"

    assert apply_dsql_baseline(engine)
    engine.table_owners = {
        "pawlocal_schema_version": owner,
        "places": owner,
        "place_facilities": owner,
        "contributions": owner,
        "favourites": owner,
        "reports": owner,
    }
    index_name = next(iter(engine.index_records))
    record = engine.index_records[index_name]
    engine.index_records[index_name] = (*record[:-1], "admin")

    with pytest.raises(RuntimeError, match="invalid or differs"):
        verify_dsql_baseline(engine, expected_owner=owner)


def test_dsql_async_index_already_present_is_verified_before_skipping():
    from pawlocal import dsql_migrations

    class _ExistingIndexConnection(_Connection):
        def execute(self, statement, parameters=None):
            if (
                str(statement)
                .upper()
                .startswith(("CREATE INDEX ASYNC", "CREATE UNIQUE INDEX ASYNC"))
            ):
                self.engine.operations.append(
                    (self.transaction_id, str(statement), parameters or {})
                )
                return _Result(None)
            return super().execute(statement, parameters)

    class _ExistingIndexEngine(_Engine):
        @contextmanager
        def connect(self):
            yield _ExistingIndexConnection(self)

    engine = _ExistingIndexEngine()
    engine.index_records["review_idx"] = (
        "review_idx",
        "contributions",
        True,
        True,
        (
            "CREATE UNIQUE INDEX review_idx ON public.contributions USING btree_index "
            "(contributor_subject, place_id) WHERE ((kind = 'review'::character varying) "
            "AND (place_id IS NOT NULL))"
        ),
        "pawlocal_development_app",
    )
    dsql_migrations._execute_one_ddl(
        engine,
        "CREATE UNIQUE INDEX ASYNC IF NOT EXISTS review_idx ON contributions "
        "(contributor_subject, place_id) WHERE kind = 'review' AND place_id IS NOT NULL",
    )
    assert not any(
        statement.upper().startswith("CALL SYS.WAIT_FOR_JOB")
        for _, statement, _ in engine.operations
    )
    assert any(
        "PG_CATALOG.PG_INDEX" in statement.upper()
        for _, statement, _ in engine.operations
    )


@pytest.mark.parametrize(
    "index_record, message",
    [
        (None, "is absent"),
        (
            (
                "sample_idx",
                "sample",
                False,
                False,
                "CREATE INDEX sample_idx ON public.sample USING btree_index (id)",
                "role",
            ),
            "invalid or differs",
        ),
        (
            (
                "sample_idx",
                "sample",
                True,
                False,
                "CREATE INDEX sample_idx ON public.sample USING btree_index (other_id)",
                "role",
            ),
            "invalid or differs",
        ),
        (
            (
                "sample_idx",
                "sample",
                True,
                False,
                "CREATE INDEX sample_idx ON public.sample USING btree_index (id) WHERE enabled",
                "role",
            ),
            "invalid or differs",
        ),
    ],
)
def test_dsql_async_index_without_job_id_fails_closed_unless_definition_is_valid(
    index_record, message
):
    from pawlocal import dsql_migrations

    class _ExistingIndexConnection(_Connection):
        def execute(self, statement, parameters=None):
            if (
                str(statement)
                .upper()
                .startswith(("CREATE INDEX ASYNC", "CREATE UNIQUE INDEX ASYNC"))
            ):
                self.engine.operations.append(
                    (self.transaction_id, str(statement), parameters or {})
                )
                return _Result(None)
            return super().execute(statement, parameters)

    class _ExistingIndexEngine(_Engine):
        @contextmanager
        def connect(self):
            yield _ExistingIndexConnection(self)

    engine = _ExistingIndexEngine()
    if index_record is not None:
        engine.index_records["sample_idx"] = index_record

    with pytest.raises(RuntimeError, match=message):
        dsql_migrations._execute_one_ddl(
            engine, "CREATE INDEX ASYNC IF NOT EXISTS sample_idx ON sample (id)"
        )


def test_postgresql_alembic_guard_rejects_dsql_and_allows_local_postgres():
    with pytest.raises(RuntimeError, match="PostgreSQL Alembic history is unsupported"):
        reject_dsql_alembic_dialect("auroradsql")
    reject_dsql_alembic_dialect("postgresql")


def test_dsql_baseline_does_not_record_revision_when_index_job_fails(tmp_path):
    class _FailedJobConnection(_Connection):
        def execute(self, statement, parameters=None):
            if str(statement).upper().startswith("CALL SYS.WAIT_FOR_JOB"):
                return _Result(False)
            return super().execute(statement, parameters)

    class _FailedJobEngine(_Engine):
        @contextmanager
        def connect(self):
            yield _FailedJobConnection(self)

    migration = tmp_path / "001_index.sql"
    migration.write_text(
        "CREATE INDEX ASYNC IF NOT EXISTS sample_idx ON sample (id);",
        encoding="utf-8",
    )
    engine = _FailedJobEngine()

    with pytest.raises(RuntimeError, match="index build did not complete"):
        apply_dsql_baseline(engine, directory=tmp_path)

    assert not engine.revision_applied


def test_dsql_bounded_dml_batches_keep_each_transaction_under_configured_limit():
    engine = _Engine()
    statements = [
        (
            text("UPDATE fixtures SET value = :id WHERE id = :id"),
            {"id": row_id, "changed_rows": 1},
        )
        for row_id in range(5)
    ]

    assert execute_bounded_dml_batches(engine, statements, batch_size=2) == 5
    update_counts = {}
    for transaction_id, statement, _parameters in engine.operations:
        if statement.upper().startswith("UPDATE"):
            update_counts[transaction_id] = update_counts.get(transaction_id, 0) + 1
    assert sorted(update_counts.values()) == [1, 2, 2]


@pytest.mark.parametrize("batch_size", [0, 3000, -1])
def test_dsql_bounded_dml_rejects_batch_sizes_outside_safe_range(batch_size):
    with pytest.raises(ValueError, match="batch_size"):
        execute_bounded_dml_batches(_Engine(), [], batch_size=batch_size)


def test_dsql_bounded_dml_rejects_a_statement_that_changes_multiple_rows():
    engine = _Engine()
    statements = [(text("UPDATE fixtures SET value = 1"), {"changed_rows": 2})]

    with pytest.raises(RuntimeError, match="at most one changed row"):
        execute_bounded_dml_batches(engine, statements)
