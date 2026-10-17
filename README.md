# PawLocal

PawLocal is a community-maintained directory of dog-friendly places across South East Queensland, from the Gold Coast to the Sunshine Coast.

## Project status

**Stage 2 (local frontend and observability) and Stage 3 (backend and persistence) are underway in parallel** in isolated worktrees. Stage 2 review remains a gate before Stage 3.1 and before Stage 3 can be considered complete. The frontend still uses demo seed records; place access and facility details are not represented as verified facts. See [frontend and local observability setup](frontend/README.md).

## Project documentation

- [Product specification](product-spec.md)
- [OpenAPI contract](openapi.yaml)
- [Architecture](docs/architecture.md)
- [Implementation plan and issue proposals](docs/implementation-plan.md)
- [Agent workflow](docs/agent-workflow.md)
- [Model policy](docs/model-policy.md)
- [Decisions](docs/decisions.md)
- [Testing approach](docs/testing.md)
- [AI usage report](docs/ai-usage-report.md)

## Planned stack

React, TypeScript, Vite and Tailwind CSS; Python, FastAPI and Pydantic; PostgreSQL with SQLAlchemy 2 and Alembic; Docker Compose; and OpenTelemetry with Grafana, Prometheus, Loki and Tempo. Hosting is undecided. Do not provision paid resources without explicit cost approval.

## Backend development

Stage 3 backend setup, migration, API, and test instructions are in [backend/README.md](backend/README.md). Protected API operations validate Cognito access tokens; no Cognito or other AWS resources are provisioned in this stage.

## Frontend service mode

The frontend uses `MockPlaceService` only when `VITE_USE_MOCK_BACKEND=true`. When the toggle is false or unset, it selects the typed `HttpPlaceService` and uses `VITE_API_BASE_URL` (default `/api/v1`). Vite's development server proxies that path to `VITE_API_PROXY_TARGET` (default `http://127.0.0.1:8000`); set the target to `http://backend:8000` in Compose. Production deployments should route `/api/v1` to the backend through their same-origin reverse proxy. A failed or unavailable API remains an HTTP error and never silently switches to mock data. The checked-in `.env.example` opts into mock mode for the local demo.

HTTP-mode authentication is a host integration seam, not a PawLocal sign-in flow. The host can inject `window.pawLocalAuth` before the app loads with `getAccessToken()` returning the current Cognito access token (sync or async), and optional `signIn()`/`signOut()` callbacks. The frontend requests a fresh token for each API call, sends it only as a Bearer header, and does not persist it. Hosts own authentication UX and token refresh. Without the host provider, protected actions report that authentication is unavailable; mock demo-member mode never authenticates HTTP requests. See [frontend/README.md](frontend/README.md#host-authentication-integration) for the interface contract.

## Development

For the local frontend and observability stack, run `docker compose up --build -d` from the repository root. The Compose project is namespaced `pawlocal-stage2` to keep it separate from the parallel Stage 3 stack. Open PawLocal at <http://localhost:5173> and Grafana at <http://localhost:3000>. See [frontend README](frontend/README.md) for all published host ports, health checks, privacy notes, telemetry controls, synthetic-failure walkthrough, shutdown, tests and the Stage 3 HTTP adapter seam. All services bind to localhost; no hosted telemetry or cloud resources are configured.

