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

## Development

For the local frontend and observability stack, run `docker compose up --build -d` from the repository root. The Compose project is namespaced `pawlocal-stage2` to keep it separate from the parallel Stage 3 stack. Open PawLocal at <http://localhost:5173> and Grafana at <http://localhost:3000>. See [frontend README](frontend/README.md) for all published host ports, health checks, privacy notes, telemetry controls, synthetic-failure walkthrough, shutdown, tests and the Stage 3 HTTP adapter seam. All services bind to localhost; no hosted telemetry or cloud resources are configured.

