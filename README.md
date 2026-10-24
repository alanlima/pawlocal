# PawLocal

PawLocal is a community-maintained directory of dog-friendly places across South East Queensland, from the Gold Coast to the Sunshine Coast.

## Project status

**Stages 2, 3, and 3.1 are complete and reviewed. Stage 4 is in progress.** Issue #135 implements a greenfield Terraform design with a standalone IAM bootstrap state and clean development and production application states while preserving the Issue #75 Lightsail Container Services and Aurora DSQL architecture. Read-only inventory verified the former application state is empty and that no PawLocal application resources survive; an unrelated account-level personal workload was verified out of scope. The configuration and workflows are not evidence of an apply or deployment. Telemetry is disabled for the initial release and backup, HA, restore, recovery, and rollback remain deferred.

Issue #43's release path runs applicable PR checks, publishes an immutable backend image from `main`, plans and applies the matching development Terraform state through protected GitHub Environments, then verifies development. Production promotion is a separate manual workflow that accepts only the same commit and image recorded by a successful development deployment. No development or production infrastructure apply is authorized by this documentation.

## Project documentation

- [Product specification](product-spec.md)
- [OpenAPI contract](openapi.yaml)
- [Architecture](docs/architecture.md)
- [Implementation plan and issue proposals](docs/implementation-plan.md)
- [Agent workflow](docs/agent-workflow.md)
- [Model policy](docs/model-policy.md)
- [Decisions](docs/decisions.md)
- [Testing approach](docs/testing.md)
- [GitHub Actions workflow reference](docs/github-actions.md)
- [On-call responder setup guide](docs/oncall-setup.md)
- [Issue #135 Terraform operator guide](docs/terraform-greenfield-operations.md)
- [Historical AWS deployment record](docs/deployment-aws-frontend.md)
- [AI usage report](docs/ai-usage-report.md)

## Planned stack

React, TypeScript, Vite and Tailwind CSS; Python, FastAPI and Pydantic; PostgreSQL with SQLAlchemy 2 and Alembic; Docker Compose; and OpenTelemetry with Grafana, Prometheus, Loki and Tempo. Local Compose uses PostgreSQL. The owner selected Lightsail Container Services + Aurora DSQL with short-lived GitHub OIDC deployment identities. Hosted telemetry is disabled for the initial release; backup, HA and recovery are deferred. Live DSQL compatibility and runtime credential refresh remain deployment gates.

## Backend development

Stage 3 backend setup, migration, API, and test instructions are in [backend/README.md](backend/README.md). Protected API operations validate Cognito access tokens; no Cognito or other AWS resources are provisioned by local development.

## Frontend service mode

The frontend uses `MockPlaceService` only when `VITE_USE_MOCK_BACKEND=true`. When the toggle is false or unset, it selects the typed `HttpPlaceService` and uses `VITE_API_BASE_URL` (default `/api/v1`). Vite's development server proxies that path to `VITE_API_PROXY_TARGET` (default `http://127.0.0.1:8000`); set the target to `http://backend:8000` in Compose. Cloud releases use separate HTTPS API hosts (`api-dev.<domain>` and `api.<domain>`), while CloudFront serves frontend assets only. A failed or unavailable API remains an HTTP error and never silently switches to mock data. The checked-in `.env.example` opts into mock mode for the local demo.

HTTP-mode authentication is a host integration seam, not a PawLocal sign-in flow. The host can inject `window.pawLocalAuth` before the app loads with `getAccessToken()` returning the current Cognito access token (sync or async), and optional `signIn()`/`signOut()` callbacks. The frontend requests a fresh token for each API call, sends it only as a Bearer header, and does not persist it. Hosts own authentication UX and token refresh. Without the host provider, protected actions report that authentication is unavailable; mock demo-member mode never authenticates HTTP requests. See [frontend/README.md](frontend/README.md#host-authentication-integration) for the interface contract.

## Development

For the combined local frontend, API, PostgreSQL and observability stack, first copy `.env.example` to `.env` (`Copy-Item .env.example .env` in PowerShell). Keep `.env` out of version control and replace the local-only password placeholder. Then run `docker compose up --build -d` from the repository root. Open PawLocal at <http://localhost:5173>, Grafana at <http://localhost:3000>, and the API health endpoint at <http://localhost:8000/health>. See the frontend and backend READMEs for ports, health checks, privacy, synthetic failures, shutdown, migrations and tests.

## Issue #135 Terraform structure

The active roots are `infra/terraform/iam-bootstrap`, `infra/terraform/environments/development`, and `infra/terraform/environments/production`. They use the distinct backend keys `pawlocal/iam-bootstrap/terraform.tfstate`, `pawlocal/development/terraform.tfstate`, and `pawlocal/production/terraform.tfstate`. The application roots share only `infra/terraform/modules/pawlocal-environment`.

Bootstrap owns GitHub OIDC trust, plan/apply and publisher role identity, baseline permissions, and permissions boundaries. Each application state owns its resources, environment-specific managed policies, and only the matching attachments. Plan roles have AWS read permissions plus their own state lock and private plan upload. Apply roles cannot create roles, alter trust or boundaries, attach another environment's policy, or exceed their bootstrap-owned boundary. Lightsail update/deployment authorization requires the matching project and environment resource tags; the roles have no `UntagResource` permission and can set the authorization tags only once on exact environment-named resources.

Application plans and applies run through `.github/workflows/terraform-environment.yml`. It publishes a value-free resource-type/action summary, transfers the opaque plan through the private bootstrap bucket, binds it to the commit, repository, run, attempt, environment, state key, one-way backend-target fingerprint, and SHA-256 digest, and applies only that saved plan after approval in `<environment>-apply`. Production first requires a successful matching development deployment. See [the operator guide](docs/terraform-greenfield-operations.md) for bootstrap planning, protected configuration, staged immutable-ARN/runtime handoffs, release commands, and verification gates.
