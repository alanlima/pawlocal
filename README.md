# PawLocal

PawLocal is a community-maintained directory of dog-friendly places across South East Queensland, from the Gold Coast to the Sunshine Coast.

## Project status

**Stages 2, 3, and 3.1 are complete and reviewed. Stage 4 is in progress.** Issue #43 CI/CD workflows define automatic development deployment after successful `main` CI and separate manual production promotion of the same development-verified backend image digest. The owner selected Lightsail + Aurora DSQL and one long-term application IAM key per environment; GitHub deployment uses scoped OIDC roles. Issue #62 adds the adapter and Terraform target, which still require review and deployment configuration. DSQL runtime compatibility requires live validation. No AWS resources or app keys have been provisioned and no full-stack deployment has occurred. Telemetry is disabled for the initial release; enablement is deferred to [Issue #59](https://github.com/alanlima/pawlocal/issues/59). Backup, HA, RPO/RTO, restore, recovery, and rollback are out of MVP scope and deferred to [Issue #44](https://github.com/alanlima/pawlocal/issues/44). CI validates frontend and backend changes, the combined local Compose stack, and Terraform configuration. Mock data is selected only when `VITE_USE_MOCK_BACKEND=true`; the combined Compose stack selects the HTTP adapter. Place access and facility details are not represented as verified facts. See [local development setup](frontend/README.md).

Issue #43 records the full-stack release policy: PR CI, automatic deployment of successful main releases to development, and a separate manually dispatched production promotion of a release already verified in development. The Issue #62 adapter and Terraform target implement the selected Lightsail + DSQL direction, but remain unreviewed/unconfigured and DSQL runtime validation is incomplete. The existing static-site Terraform configuration is not the full-stack deployment target. See the [AWS deployment runbook](docs/deployment-aws-frontend.md), [hosting proposal](docs/stage4-hosting-options.md), and [decision log](docs/decisions.md).

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

React, TypeScript, Vite and Tailwind CSS; Python, FastAPI and Pydantic; PostgreSQL with SQLAlchemy 2 and Alembic; Docker Compose; and OpenTelemetry with Grafana, Prometheus, Loki and Tempo. Local Compose uses PostgreSQL. The owner selected Lightsail + Aurora DSQL with per-environment IAM app keys; DSQL still requires live compatibility validation and deployment setup. Hosted telemetry is disabled for the initial release; backup, HA and recovery are deferred. The MVP budget is approved; no cloud resources or app keys have been provisioned and deployment has not occurred.

## Backend development

Stage 3 backend setup, migration, API, and test instructions are in [backend/README.md](backend/README.md). Protected API operations validate Cognito access tokens; no Cognito or other AWS resources are provisioned in this stage.

## Frontend service mode

The frontend uses `MockPlaceService` only when `VITE_USE_MOCK_BACKEND=true`. When the toggle is false or unset, it selects the typed `HttpPlaceService` and uses `VITE_API_BASE_URL` (default `/api/v1`). Vite's development server proxies that path to `VITE_API_PROXY_TARGET` (default `http://127.0.0.1:8000`); set the target to `http://backend:8000` in Compose. Cloud releases use separate HTTPS API hosts (`api-dev.<domain>` and `api.<domain>`), while CloudFront serves frontend assets only. A failed or unavailable API remains an HTTP error and never silently switches to mock data. The checked-in `.env.example` opts into mock mode for the local demo.

HTTP-mode authentication is a host integration seam, not a PawLocal sign-in flow. The host can inject `window.pawLocalAuth` before the app loads with `getAccessToken()` returning the current Cognito access token (sync or async), and optional `signIn()`/`signOut()` callbacks. The frontend requests a fresh token for each API call, sends it only as a Bearer header, and does not persist it. Hosts own authentication UX and token refresh. Without the host provider, protected actions report that authentication is unavailable; mock demo-member mode never authenticates HTTP requests. See [frontend/README.md](frontend/README.md#host-authentication-integration) for the interface contract.

## Development

For the combined local frontend, API, PostgreSQL and observability stack, first copy `.env.example` to `.env` (`Copy-Item .env.example .env` in PowerShell). The example contains a clearly local-only PostgreSQL password placeholder; keep `.env` out of version control and replace the placeholder for your local environment. Compose requires `PAWLOCAL_POSTGRES_PASSWORD` and has no built-in credential fallback. Then run `docker compose up --build -d` from the repository root. Open PawLocal at <http://localhost:5173>, Grafana at <http://localhost:3000>, and the API health endpoint at <http://localhost:8000/health>. See [frontend README](frontend/README.md) and [backend README](backend/README.md) for ports, health checks, privacy, synthetic failures, shutdown, migrations and tests. All local Compose services bind to localhost; running the local stack requires no cloud resources.

