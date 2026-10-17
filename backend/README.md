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

## Browser integration authentication (planned, not yet verified)

Authenticated Playwright runs must use the same `get_current_subject` validation path as production, with a disposable local OIDC test issuer. Generate a fresh RSA signing key for the test run, serve its public key from `<test-issuer>/.well-known/jwks.json`, and set `PAWLOCAL_COGNITO_ISSUER` and `PAWLOCAL_COGNITO_APP_CLIENT_ID` to that issuer and a test client ID. Sign short-lived access tokens with the exact issuer, a synthetic `sub`, `token_use=access`, `client_id`, and `exp`; include the configured resource audience when that check is enabled. Run the real API and PostgreSQL with these test-only values, and let Playwright obtain its token from a test-only frontend auth provider. Keep the private key and token ephemeral; never commit them or reuse them in production.

The frontend factory currently uses the mock service and Stage 2 owns its observability wrapper. Coordinate the HTTP-mode switch with that workstream and preserve its wrapper. The existing demo-member UI is mock-only and does not authenticate against the API. No browser-to-PostgreSQL authenticated journey has been run yet; this acceptance item remains open until the local issuer, HTTP adapter, database and browser flow are exercised together.
