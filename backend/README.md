# Backend development

The API uses FastAPI and SQLAlchemy 2. PostgreSQL is the local development default. The selected cloud runtime supports Aurora DSQL through AWS's SQLAlchemy adapter. Request handlers access persisted data through application queries and repositories. The API does not include seed locations: only approved listing data should be published.

## Local setup

From `backend/`, create and activate a virtual environment, then install the package and test dependencies:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e '.[test]'
```

Set `PAWLOCAL_DATABASE_URL` to a PostgreSQL URL in the shell or root `.env` for local development. The default is a local PostgreSQL socket/localhost connection using the current operating-system user. Root Compose passes host, port, database, user and password as separate settings; the backend uses SQLAlchemy `URL.create` so URL-special characters in the password remain valid. To enable protected writes, configure `PAWLOCAL_COGNITO_ISSUER` and `PAWLOCAL_COGNITO_APP_CLIENT_ID`; configure `PAWLOCAL_COGNITO_RESOURCE_AUDIENCE` and `PAWLOCAL_COGNITO_REQUIRE_RESOURCE_AUDIENCE=true` when Cognito resource binding is enabled. The API accepts signed access tokens only. Stage 3 does not provision Cognito resources. Apply migrations and run the API:

```powershell
alembic -c alembic.ini upgrade head
uvicorn pawlocal.main:app --reload
```

The API health endpoint is `http://127.0.0.1:8000/health`; OpenAPI docs are at `/docs`. Run backend tests with `pytest` from this directory. API/repository tests use isolated SQLite fixtures and do not require approved production place data.

## Aurora DSQL compatibility status

PR #61 CI and GitGuardian checked the provider-neutral release workflow, but did not deploy the application or create a DSQL cluster. This backend change wires the selected Aurora DSQL runtime connector; there is still no live DSQL migration, runtime connection, IAM token refresh, or OCC evidence. No DSQL or other AWS resources were created for this work.

`create_database_engine` preserves the PostgreSQL path and sends Aurora DSQL URLs to AWS's `create_dsql_engine` helper. That helper obtains short-lived DSQL IAM tokens through the AWS DSQL connector and AWS SDK credential chain, and configures TLS certificate verification. The app passes only the endpoint, custom database role, database name, and optional `application_name`; it does not read keys, create tokens, or place credentials in connection URLs. Configure each host's AWS SDK credential source outside the repository and image (for the MVP, one IAM user's key per environment as approved in Issue #43). Do not set DSQL passwords or token/auth URL options. The connector's live connection and token refresh behavior remain unverified.

The deployment can set `PAWLOCAL_DATABASE_URL` to `auroradsql+psycopg://<custom-db-role>@<cluster-endpoint>/postgres?application_name=pawlocal-dev` (use the production role and application name in production). The endpoint includes its AWS Region. For host credentials in a restricted shared credentials file, configure the standard `AWS_SHARED_CREDENTIALS_FILE` variable for the API service; boto3's normal provider chain reads it. Do not put key values in this URL, repository files, or the container image.

Place facilities are represented by the normalized `place_facilities` relation in the current ORM and migration `0007`; search uses one correlated `EXISTS` predicate per selected facility. This removes the prior PostgreSQL array/`ANY` query dependency. The representative SQL generated from the application query compiles with AWS's SQLAlchemy DSQL dialect and passes `dsql-lint` (offline SQL evidence only).

The PostgreSQL/Alembic history remains the local and PostgreSQL path. Migrations `0001` through `0006` create PostgreSQL arrays, synchronous indexes, and contain PostgreSQL-specific backfill/quarantine SQL. Migration `0007` normalizes facilities for PostgreSQL and intentionally fails closed on the DSQL dialect because it migrates from that legacy array schema. Do not point the Alembic chain at DSQL.

For clean DSQL installs, `python -m pawlocal.dsql_migrate` applies the separate `migrations/dsql/0001_initial` baseline through `pawlocal.dsql_migrations.apply_dsql_baseline(engine)`. It executes one DDL statement per transaction, waits for asynchronous index jobs, then verifies each index's catalog validity and requested definition before continuing. When `IF NOT EXISTS` returns no job ID after an interrupted run, the runner verifies the catalog and fails closed if the index is missing, invalid, or different. It records the baseline revision only after all schema work succeeds. Subsequent calls skip the recorded baseline. No forward DSQL upgrade revisions or PostgreSQL-to-DSQL data migration are implemented; future schema changes need numbered DSQL migrations before deployment. `execute_bounded_dml_batches` caps each transaction below DSQL's 3,000-row DML limit. This is a clean-install path for a new, empty DSQL database only.

| Concern | PostgreSQL/Alembic | DSQL clean-install baseline |
|---|---|---|
| Facilities | `0001`-`0006` use a PostgreSQL `varchar[]`; `0007` converts data to `place_facilities` with `unnest` | Starts directly with normalized `place_facilities`; no array conversion |
| Search | ORM query filters normalized facility rows with correlated `EXISTS`; avoids `ANY` and array containment | Same ORM query; AWS dialect SQL compiles offline and rendered search/count SQL passes `dsql-lint` |
| Indexes | Alembic emits synchronous `CREATE INDEX` | Each index is `CREATE INDEX ASYNC`; runner waits for its job before proceeding |
| DDL / DML | Existing history includes migration `0005` mixed DDL and backfill and `0006` quarantine/backfill and cleanup | One DDL per transaction; version ledger and bounded row-by-row DML are separate transactions |
| Existing data | Existing PostgreSQL rows are converted by `0007` | Import/backfill from PostgreSQL is not implemented; this path initializes a new empty database |

The PostgreSQL history therefore cannot be replayed on DSQL; use the separate baseline only for a new, empty DSQL database. No live DSQL cluster has validated the baseline, generated query plans, or runtime OCC behavior.

Offline evidence: the DSQL baseline statements pass `dsql-lint`; unit tests exercise transaction separation, async-index wait ordering, ledger behavior, and DML batching. The AWS dialect compiles the normalized facility search query. Review submission retries DSQL optimistic concurrency conflicts with a bounded three-attempt policy and rolls back the full failed transaction before retry. These checks do not prove a live DSQL migration, runtime query, token refresh, concurrency result, or query plan.

The application is configured to keep local Compose on PostgreSQL; select DSQL in the cloud only after the endpoint and approved environment-specific AWS SDK credentials are installed on that host. The DSQL adapter uses the default AWS SDK credential chain, so later migration to temporary credentials is a host-configuration change. No live Aurora DSQL connection, migration, token refresh, OCC, query plan, or DPU behavior is claimed verified. Live validation requires provisioned DSQL test resources and environment credentials, which are outside this backend-only change.

## Local tracing, logs and synthetic failures

The combined root Compose stack sets `PAWLOCAL_TELEMETRY_ENABLED=true` and exports API spans and structured logs to the local Collector at `PAWLOCAL_OTLP_ENDPOINT` (`http://otel-collector:4318`). Outside Compose, telemetry and demo faults default to disabled. API spans accept W3C `traceparent` for correlation and deliberately discard inbound `tracestate`; database spans record only the database system and a generic query operation, never SQL or bind values. Structured API logs contain fixed event codes, route templates, status, duration, and trace/span IDs. Health probes are excluded to keep local logs useful.

With `PAWLOCAL_DEMO_FAULTS_ENABLED=true`, send the exact allowlisted header `X-PawLocal-Demo-Failure: api` or `database` to a local API request to produce a safe 503 with a correlated error span/log. (The separate `PAWLOCAL_DEMO_FAULTS` variable controls the frontend demo fault.) FastAPI's built-in telemetry is disabled so only the explicitly configured spans are exported; in particular, raw request query strings are not attached to traces. For example:

```powershell
curl.exe -i -H "traceparent: 00-11111111111111111111111111111111-2222222222222222-01" -H "X-PawLocal-Demo-Failure: database" http://127.0.0.1:8000/api/v1/places
```

The control accepts only those two fixed values, is disabled by default, and does not log request headers or bodies. Stop the combined stack with `docker compose down`; use `docker compose down -v` only when you also intend to erase the local PostgreSQL and observability volumes.

To reset a disposable local database, drop and recreate the local `pawlocal` database, then run the migration command again. Stop Uvicorn with Ctrl+C and stop the local database using the command/container that started it. Root Compose wiring and PostgreSQL startup are coordinated with the Stage 2/3.1 workstreams.

Write rate limits are per subject and per API process. This is suitable for local single-instance development; it is not a distributed production limiter. Public reportable contributions include published content fields only and omit contributor identity.

## Browser integration authentication

`tests/e2e_local_server.py` is a test-only runner that applies migrations to a dedicated database, seeds one clearly synthetic place, and starts the real API plus a disposable OIDC issuer. It creates an ephemeral RSA key and short-lived access tokens on each run. The API uses its normal issuer, JWKS, expiry, token-use and client-ID validation; the helper adds no production authentication bypass. Never point it at a database containing data you need: it resets records for its fixed synthetic subject and place IDs.

With the backend virtual environment and dependencies installed, set `PAWLOCAL_E2E_DATABASE_URL` to a disposable PostgreSQL database whose name contains a `_test`, `_e2e`, or `_verify` segment. Explicitly opt into migration and fixture reset with `PAWLOCAL_E2E_ALLOW_RESET=true`, then run from `backend/`:

```powershell
$env:PAWLOCAL_E2E_DATABASE_URL = "postgresql+psycopg://pawlocal:pawlocal-local@host.docker.internal:55432/pawlocal_stage3_verify"
$env:PAWLOCAL_E2E_ALLOW_RESET = "true"
python tests/e2e_local_server.py
```

The runner fails before migrations or cleanup unless both settings are present, the opt-in value is exactly `true`, the URL uses PostgreSQL, and its database name includes one of the disposable-name segments. It does not fall back to `PAWLOCAL_DATABASE_URL`.

The helper listens on `127.0.0.1:18001` for the API and `127.0.0.1:18002` for its issuer by default. In a second terminal, run from `frontend/`:

```powershell
npm run test:e2e:backend
```

The dedicated Vite test configuration aliases only the test build to `HttpPlaceService` and proxies requests to the real API. It obtains a token from the local issuer, then covers anonymous rejection, place discovery and detail, contribution, favourite, report, and reloading saved/reportable state in a fresh browser context. The demo-member control only reveals mock-stage form UI; it does not authenticate API requests. The regular service factory uses the HTTP adapter unless `VITE_USE_MOCK_BACKEND=true` explicitly selects the mock; the HTTP adapter remains wrapped by the frontend observability layer.

Verified on 2026-10-18: the opt-in PostgreSQL repository test passed, and `npm run test:e2e:backend` passed the anonymous rejection, real JWT validation, discovery/detail/share, contribution, favourite, report, and fresh-browser-context persistence flow against PostgreSQL. A second API process connected to the same database and read back the saved favourite and reportable contribution. The E2E harness records were then removed; reports, favourites, contributions, and the synthetic place each had zero rows remaining. This verifies API-process restart persistence, but the PostgreSQL container itself was not restarted, so database-restart persistence remains unverified.
