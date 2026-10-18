# PawLocal

PawLocal is a community-maintained directory of dog-friendly places across South East Queensland, from the Gold Coast to the Sunshine Coast.

## Project status

**Stages 2, 3, and 3.1 are complete and reviewed. Stage 4 is in progress.** The current AWS release serves a static, mock-backed frontend. Human direction is Lightsail for the API and Aurora DSQL as a database candidate pending compatibility, recovery, and cost validation; hosted telemetry is also pending validation. CI validates frontend and backend changes, the combined local Compose stack, and Terraform configuration without provisioning cloud resources. Production alerting, incident response, and a controlled rollback/recovery demonstration remain Stage 4 work. Mock data is selected only when `VITE_USE_MOCK_BACKEND=true`; the combined Compose stack selects the HTTP adapter. Place access and facility details are not represented as verified facts. See [local development setup](frontend/README.md).

## Project documentation

- [Product specification](product-spec.md)
- [OpenAPI contract](openapi.yaml)
- [Architecture](docs/architecture.md)
- [Implementation plan and issue proposals](docs/implementation-plan.md)
- [Agent workflow](docs/agent-workflow.md)
- [Model policy](docs/model-policy.md)
- [Decisions](docs/decisions.md)
- [Testing approach](docs/testing.md)
- [AWS frontend deployment runbook](docs/deployment-aws-frontend.md)
- [AI usage report](docs/ai-usage-report.md)

## Planned stack

React, TypeScript, Vite and Tailwind CSS; Python, FastAPI and Pydantic; PostgreSQL with SQLAlchemy 2 and Alembic; Docker Compose; and OpenTelemetry with Grafana, Prometheus, Loki and Tempo. The initial frontend uses AWS S3/CloudFront. Stage 4 human direction is AWS Lightsail for the API and Aurora DSQL as a database candidate pending compatibility, recovery and cost validation; hosted telemetry is also pending validation. Do not provision paid resources without explicit cost approval.

## Backend development

Stage 3 backend setup, migration, API, and test instructions are in [backend/README.md](backend/README.md). Protected API operations validate Cognito access tokens; no Cognito or other AWS resources are provisioned in this stage.

## Frontend service mode

The frontend uses `MockPlaceService` only when `VITE_USE_MOCK_BACKEND=true`. When the toggle is false or unset, it selects the typed `HttpPlaceService` and uses `VITE_API_BASE_URL` (default `/api/v1`). Vite's development server proxies that path to `VITE_API_PROXY_TARGET` (default `http://127.0.0.1:8000`); set the target to `http://backend:8000` in Compose. Production deployments should route `/api/v1` to the backend through their same-origin reverse proxy. A failed or unavailable API remains an HTTP error and never silently switches to mock data. The checked-in `.env.example` opts into mock mode for the local demo.

HTTP-mode authentication is a host integration seam, not a PawLocal sign-in flow. The host can inject `window.pawLocalAuth` before the app loads with `getAccessToken()` returning the current Cognito access token (sync or async), and optional `signIn()`/`signOut()` callbacks. The frontend requests a fresh token for each API call, sends it only as a Bearer header, and does not persist it. Hosts own authentication UX and token refresh. Without the host provider, protected actions report that authentication is unavailable; mock demo-member mode never authenticates HTTP requests. See [frontend/README.md](frontend/README.md#host-authentication-integration) for the interface contract.

## Development

For the combined local frontend, API, PostgreSQL and observability stack, first copy `.env.example` to `.env` (`Copy-Item .env.example .env` in PowerShell). The example contains a clearly local-only PostgreSQL password placeholder; keep `.env` out of version control and replace the placeholder for your local environment. Compose requires `PAWLOCAL_POSTGRES_PASSWORD` and has no built-in credential fallback. Then run `docker compose up --build -d` from the repository root. Open PawLocal at <http://localhost:5173>, Grafana at <http://localhost:3000>, and the API health endpoint at <http://localhost:8000/health>. See [frontend README](frontend/README.md) and [backend README](backend/README.md) for ports, health checks, privacy, synthetic failures, shutdown, migrations and tests. All local Compose services bind to localhost; running the local stack requires no cloud resources.

