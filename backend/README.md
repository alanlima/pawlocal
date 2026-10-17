# Backend development

The API uses FastAPI and SQLAlchemy 2. PostgreSQL is the runtime database; request handlers use a `PlaceService`-independent API boundary and access persisted data through application queries and repositories. The API does not include seed locations: only approved listing data should be published.

## Local setup

From `backend/`, create and activate a virtual environment, then install the package and test dependencies:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e '.[test]'
```

Set `PAWLOCAL_DATABASE_URL` to a PostgreSQL URL in the shell or root `.env`. The default is a local PostgreSQL socket/localhost connection using the current operating-system user. To enable protected writes, configure `PAWLOCAL_COGNITO_ISSUER` and `PAWLOCAL_COGNITO_APP_CLIENT_ID`; configure `PAWLOCAL_COGNITO_RESOURCE_AUDIENCE` and `PAWLOCAL_COGNITO_REQUIRE_RESOURCE_AUDIENCE=true` when Cognito resource binding is enabled. The API accepts signed access tokens only. Stage 3 does not provision Cognito resources. Apply migrations and run the API:

```powershell
alembic -c alembic.ini upgrade head
uvicorn pawlocal.main:app --reload
```

The API health endpoint is `http://127.0.0.1:8000/health`; OpenAPI docs are at `/docs`. Run backend tests with `pytest` from this directory. API/repository tests use isolated SQLite fixtures and do not require approved production place data.

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

The dedicated Vite test configuration aliases only the test build to `HttpPlaceService` and proxies requests to the real API. It obtains a token from the local issuer, then covers anonymous rejection, place discovery and detail, contribution, favourite, report, and reloading saved/reportable state in a fresh browser context. The demo-member control only reveals mock-stage form UI; it does not authenticate API requests. The production service factory remains unchanged, including the Stage 2 observability wrapper when that workstream is integrated.

Verified on 2026-10-18: the opt-in PostgreSQL repository test passed, and `npm run test:e2e:backend` passed the anonymous rejection, real JWT validation, discovery/detail/share, contribution, favourite, report, and fresh-browser-context persistence flow against PostgreSQL. A second API process connected to the same database and read back the saved favourite and reportable contribution. The E2E harness records were then removed; reports, favourites, contributions, and the synthetic place each had zero rows remaining. This verifies API-process restart persistence, but the PostgreSQL container itself was not restarted, so database-restart persistence remains unverified.
