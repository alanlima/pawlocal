# Issue #53: offline DSQL facilities prototype

**Status:** Isolated offline prototype, approved by the human on 2026-10-19. This is not an application database adapter and does not establish Aurora DSQL compatibility.

## Scope and isolation

The prototype explores a normalized `place_facilities(place_id, ordinal, facility)` relation and a parameterized `EXISTS` query. It is implemented only in `backend/pawlocal/dsql_facilities_prototype.py` and `backend/scripts/render_dsql_facilities_prototype.py`; nothing imports it into the API runtime.

The ordinal preserves the current PostgreSQL array's list order and duplicate values during fixture conversion. The query uses one correlated `EXISTS` predicate for each distinct requested value, so selecting multiple facilities means all selected facilities must be present, repeated query parameters do not change that result, and a place cannot be duplicated by matching multiple facility rows. Results are ordered by name and UUID before pagination, with an exact count query using the same filters.

The prototype schema declares only `places.id`, `places.name`, `places.is_published` and the facility relation needed for this evaluation. It is not a full replacement schema or a production migration. It has no connection or runtime-selection code.

Production PostgreSQL behavior remains unchanged: default runtime selection remains `postgresql+psycopg`; existing production models, migrations `0001`–`0006`, API and Compose configuration are untouched. Prototype behavior tests execute against an isolated in-memory SQLite database. DSQL-oriented SQL is generated with SQLAlchemy's mock engine; no engine connection or AWS credential is used.

## Reproduce offline checks

From `backend/`, create an isolated Python environment and install the pinned optional tools:

```powershell
python -m venv .venv-dsql-prototype
.\.venv-dsql-prototype\Scripts\python -m pip install -e ".[test,dsql-prototype]"
```

Generate SQL and run the prototype tests and DSQL linter:

```powershell
.\.venv-dsql-prototype\Scripts\python scripts\render_dsql_facilities_prototype.py > ..\docs\generated\dsql-facilities-prototype.sql
.\.venv-dsql-prototype\Scripts\python scripts\render_dsql_facilities_prototype.py --schema-only > ..\docs\generated\dsql-facilities-schema.sql
.\.venv-dsql-prototype\Scripts\python -m pytest tests\test_dsql_facilities_prototype.py
.\.venv-dsql-prototype\Scripts\dsql-lint --version
.\.venv-dsql-prototype\Scripts\dsql-lint --format json ..\docs\generated\dsql-facilities-schema.sql
```

The optional `dsql-prototype` extra pins `aurora-dsql-sqlalchemy[psycopg]==1.3.0` and `dsql-lint==0.2.20`. Do not run the linter with `--fix`; its output is review evidence and must not rewrite the generated SQL automatically.

## Generated DSQL-oriented SQL

The checked-in [generated SQL](generated/dsql-facilities-prototype.sql) is emitted through `create_mock_engine("auroradsql://", ...)` using the AWS SQLAlchemy adapter. The command calls `MetaData.create_all` on SQLAlchemy's mock engine and compiles the query; it never calls `connect()` or the adapter's live-engine helper. The file records the adapter-emitted table, constraints, asynchronous index syntax, paginated query and exact count query, including bound parameter names. The [schema-only SQL](generated/dsql-facilities-schema.sql) is the same adapter-emitted DDL without query statements.

## Offline run evidence

Verified locally on 2026-10-19 with Python 3.12.1, SQLAlchemy 2.1.5, `aurora-dsql-sqlalchemy[psycopg]` 1.3.0, and `dsql-lint` 0.2.20. SQLAlchemy's `auroradsql://` mock engine emitted the checked-in artifacts without opening a database connection or accessing AWS. The DDL-only linter run on `generated/dsql-facilities-schema.sql` returned 0 errors and 0 warnings.

The linter cannot parse the dialect's parameterized query form. Running it on the full `generated/dsql-facilities-prototype.sql` returned two `parse_error` diagnostics at the facility bind markers, because the emitted psycopg placeholders (`%(facility_0)s::VARCHAR`, `%(facility_1)s::VARCHAR`) are not accepted by its offline SQL parser. The query itself remains parameterized in the code and generated artifact; it was checked for compilation and behavior in the isolated SQLite tests, not linted as DSQL SQL. No `--fix` was run.

`python -m pytest tests/test_dsql_facilities_prototype.py -vv` passed **8 tests**. `python -m pytest` passed **58 tests**, with **2 skips** (including the opt-in PostgreSQL integration test because no disposable PG URL was configured); the run emitted one Starlette/httpx deprecation warning. `ruff check .` passed. The real PostgreSQL 17.6 CI service and migrations were not run in this local prototype verification.

The dialect/linter runs verify only that the pinned local tools can render and statically inspect the isolated candidate's DDL. They do not prove that DSQL accepts or executes the DDL/query, that asynchronous index creation has completed, that a clean or upgrade migration works, or that query plans, latency or cost are acceptable.

## Test coverage and limits

The prototype tests cover empty and single-facility filters, multiple selected facilities with all-selected semantics, repeated requested values, duplicate matching facility rows without duplicate places, unknown filter/data values, array-fixture conversion preserving order and duplicates, exact counts, stable ordering and page boundaries. A dialect rendering test asserts that generated SQL has no persisted array type/operator and includes bound parameters and `EXISTS` predicates.

SQLite execution is a local semantic test only. `dsql-lint` findings and SQLAlchemy compilation are static evidence only. The prototype does not validate the existing model's remaining DSQL compatibility, the community transaction/OCC behavior, IAM credential refresh, migration upgrade or backfill against DSQL, query DPU/cost, backup/restore, or application recovery.

## Validation still requiring approved live resources

Only after separate test-resource and spend approval, run the actual AWS dialect against a disposable DSQL cluster to verify clean bootstrap, migration/upgrade and backfill, schema constraints, facility searches and pagination, async index completion, concurrent writes/retries, token refresh and new connections, representative query performance and CloudWatch DPU usage, backup restore and RPO/RTO. No such resource was created or queried for this prototype. DSQL remains provisional; this work does not approve a provider change, spending, provisioning, or deployment.
