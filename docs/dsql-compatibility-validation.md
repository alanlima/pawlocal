# Aurora DSQL compatibility review

**Review date:** 2026-10-19

**Status:** This review reflects [PR #61 head `57df341`](https://github.com/alanlima/pawlocal/pull/61/commits/57df34182b96e9bdbeab96abe55ce1aead1f90fd) on branch `43-fullstack-mvp`. Standalone [Backend CI](https://github.com/alanlima/pawlocal/actions/runs/39178777978) and [frontend PR checks](https://github.com/alanlima/pawlocal/actions/runs/39178777999), reusable backend/frontend jobs in the [full-stack release run](https://github.com/alanlima/pawlocal/actions/runs/39178777998), [workflow validation](https://github.com/alanlima/pawlocal/actions/runs/39178777965), and GitGuardian passed. Full-stack image publication and development deployment were skipped because this was a pull request. This is CI/offline compatibility evidence, not evidence of a DSQL cluster migration or runtime. Aurora DSQL remains a candidate, not a validated or selected runtime provider. No DSQL cluster/resources were created or used for this validation; no production DSQL runtime integration or credential path is configured. The Lightsail application-hosting direction is approved, while the secure AWS identity/credential path from that host to a potential DSQL database remains unresolved.

## Scope and release boundaries

This review covers DSQL schema/query compatibility and migration preparation for the MVP. Local Docker Compose continues to use PostgreSQL. No provider switch, cloud resource creation, deployment, or DSQL connection was performed. The initial cloud release keeps telemetry disabled; telemetry enablement remains tracked by [Issue #59](https://github.com/alanlima/pawlocal/issues/59).

Backup, HA, restore, RPO/RTO, and recovery are excluded from this release and deferred to [Issue #44](https://github.com/alanlima/pawlocal/issues/44), to be reviewed after the MVP is deployed to cloud. They are not gates for this DSQL compatibility work.

## Current implementation and compatibility matrix

| Area                         | Current implementation                                                                                                                                                                                                                                                                                                                                   | Evidence and limitation                                                                                                                                                                      |
| ---------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Facilities schema            | `PlaceRecord` now maps facilities through normalized `place_facilities` rows. PostgreSQL migration `0007` converts legacy arrays while preserving ordinal order.                                                                                                                                                                                         | Local backend tests and PostgreSQL offline Alembic SQL generation only; no live PostgreSQL migration was run for this worktree.                                                              |
| Place search                 | The application uses a correlated `EXISTS` predicate per distinct selected facility. The query no longer uses PostgreSQL `ANY(array)` or a JSON-specific branch.                                                                                                                                                                                         | The production query compiles with the AWS SQLAlchemy DSQL dialect and the generated search/count SQL passes `dsql-lint`. This is offline SQL evidence, not execution or a query-plan check. |
| DSQL clean install           | A separate static SQL baseline at `backend/migrations/dsql/0001_initial/` creates the normalized final schema directly. `pawlocal.dsql_migrations.apply_dsql_baseline(engine)` runs one DDL statement per transaction, records a version only after the schema succeeds, and provides bounded row-by-row DML batches for future data changes.            | Fake-engine unit tests exercise transaction separation, ledger ordering, rerun behavior when DDL exists, and the DML batch cap. The baseline has not been applied to a DSQL cluster.         |
| Async indexes                | The runner waits for each returned index job. It then checks the DSQL catalog for a valid index and compares its table, uniqueness, method, ordered columns, and predicate to the requested definition. If `IF NOT EXISTS` returns no job ID, the runner performs the same verification and fails closed if the index is missing, invalid, or different. | Unit/fake-catalog tests plus AWS dialect/linter checks only. Index completion and catalog-query behavior remain unverified against a live cluster.                                           |
| PostgreSQL migration history | Alembic revisions `0001`-`0007` remain the local/PostgreSQL path. The generic Alembic environment rejects DSQL URLs before offline rendering and checks online connections before running revisions.                                                                                                                                                     | PostgreSQL offline `alembic upgrade head --sql` succeeds. A manual offline DSQL-URL invocation exits at the early guard before revision SQL. No live PostgreSQL or DSQL migration was run.   |
| Legacy cloud data            | No PostgreSQL-to-DSQL import/backfill sequence is implemented.                                                                                                                                                                                                                                                                                           | The DSQL baseline is suitable only for an empty initial cloud database. Existing PostgreSQL data migration is still required if the deployment starts with non-empty legacy data.            |
| Runtime engine and IAM       | The application still builds its PostgreSQL psycopg engine. No DSQL engine configuration, token provider, token refresh, host identity integration, or runtime environment variables have been added. Static AWS keys and environment-supplied auth tokens are not accepted.                                                                             | No DSQL connection or runtime credential behavior is validated. The owner must decide how the chosen host obtains short-lived AWS credentials before runtime integration can proceed.        |
| OCC behavior                 | Review submissions have a bounded retry around the complete transaction for selected DSQL conflict codes; PostgreSQL behavior remains single-attempt.                                                                                                                                                                                                    | Unit tests simulate retryable and non-retryable errors. No DSQL OCC response, concurrent transaction, or retry-exhaustion scenario was observed live.                                        |
| CI checks                    | Backend CI installs the optional DSQL tools and lints the checked-in baseline plus generated application search/count SQL.                                                                                                                                                                                                                              | On PR #61 head `57df341`, standalone Backend CI/frontend checks, full-stack backend/frontend checks, workflow validation, and GitGuardian passed. Image publication and development deployment were skipped because this was a PR. This does not validate DSQL runtime behavior. |

The current DSQL baseline deliberately does not replay PostgreSQL migrations `0001`-`0007`. Those revisions include a persisted PostgreSQL array, synchronous index creation, PostgreSQL-specific `unnest`/regex/CTAS operations, and multi-statement or mixed DDL/DML transformations. A separate baseline avoids applying those operations to DSQL, but it does not migrate existing records.

## Evidence status

Local offline evidence recorded for this implementation:

- Backend test suite: **79 passed, 2 skipped**.
- DSQL-focused tests: **21 passed**.
- Targeted Ruff checks: passed.
- DSQL baseline SQL lint: passed.
- Generated application search/count SQL lint: passed.
- PostgreSQL Alembic offline SQL generation: passed.
- Offline Alembic invocation with an Aurora DSQL URL: rejected before any revision SQL was emitted.

On PR #61 head `57df341`, the standalone Backend CI/frontend checks, full-stack backend/frontend checks, workflow validation, and GitGuardian passed; the immutable-image publication and development deployment jobs were skipped as expected for a PR. Passing CI, lint, compilation, offline migration generation, and fake-engine/catalog tests do not establish that DSQL accepts or executes the statements, that indexes become valid, or that queries have acceptable behavior or cost. No DSQL cluster or other DSQL resources were created or available for validation. No live DSQL compatibility claim is made.

## Remaining decisions and validation

The owner needs to select and approve the Lightsail-to-DSQL identity/credential path. The backend currently has no DSQL engine or runtime token integration, and no DSQL resources exist for testing, so runtime validation must wait for both the identity decision and an authorized DSQL test environment. Do not add static credentials or silently change the database provider.

After runtime identity is approved and a DSQL test environment is authorized, the remaining DSQL validation is:

1. Apply the clean-install baseline to an empty test cluster and verify catalog objects, index validity, and schema constraints.
2. Exercise the repository/API journey, including place search, contributions, favourites, reports, duplicate review handling, rating updates, and bounded conflict retries.
3. Verify connection token refresh/reconnect and concurrent OCC behavior through the approved runtime identity path.
4. Capture representative query plans and DPU measurements before making performance or cost claims.
5. If cloud data already exists, design and test a separate PostgreSQL-to-DSQL import/backfill process with bounded DML; the current baseline does not provide it.

These steps do not add backup, HA, restore, RPO/RTO, or recovery requirements to the MVP compatibility gate. Those topics remain deferred to Issue #44 after cloud deployment.

## Official references

- [Aurora DSQL region and compatibility overview](https://docs.aws.amazon.com/aurora-dsql/latest/userguide/what-is-aurora-dsql.html)
- [PostgreSQL migration guide and DSQL transaction limits](https://docs.aws.amazon.com/aurora-dsql/latest/userguide/working-with-postgresql-compatibility-migration-guide.html)
- [ALTER TABLE constraint requirements](https://docs.aws.amazon.com/aurora-dsql/latest/userguide/alter-table-syntax-support.html)
- [Supported data types](https://docs.aws.amazon.com/aurora-dsql/latest/userguide/working-with-postgresql-compatibility-supported-data-types.html)
- [CREATE INDEX syntax and asynchronous index creation](https://docs.aws.amazon.com/aurora-dsql/latest/userguide/create-index-syntax-support.html) and [async index operations](https://docs.aws.amazon.com/aurora-dsql/latest/userguide/working-with-create-index-async.html)
- [Concurrency control and OCC retry behavior](https://docs.aws.amazon.com/aurora-dsql/latest/userguide/working-with-concurrency-control.html)
- [Authentication and authorization](https://docs.aws.amazon.com/aurora-dsql/latest/userguide/authentication-authorization.html) and [Python SQLAlchemy adapter](https://github.com/awslabs/aurora-dsql-orms/tree/main/python/sqlalchemy)
- [Lightsail IAM guidance](https://docs.aws.amazon.com/lightsail/latest/userguide/security_iam.html)
