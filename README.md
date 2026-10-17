# PawLocal

PawLocal is a community-maintained directory of dog-friendly places across South East Queensland, from the Gold Coast to the Sunshine Coast.

## Project status

The project has started **Stage 1: Frontend with mock API**. See [frontend setup and adapter notes](frontend/README.md). The application uses demo seed records only; place access and facility details are not represented as verified facts.

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

## Development

Run the frontend from the repository root with `cd frontend`, `npm install`, then `npm run dev`. See [frontend README](frontend/README.md) for tests and the future HTTP adapter seam. Stage 1 ends at its human review gate; observability and backend work are not included here.

