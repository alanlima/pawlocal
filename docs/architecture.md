# Architecture

**Status:** Stage 0 proposal; no runtime components are implemented.

## System shape

```text
React/Vite client ── typed service interface ── mock adapter (Stage 1)
                                            └── HTTP adapter (Stage 3)
                                                      │ OpenAPI
                                                      ▼
                                             FastAPI application
                                      API → use cases → domain rules
                                                      │ repositories
                                                      ▼
                                      PostgreSQL (Stage 3; persistence)

Search → API → database → place details
  └──────── logs, metrics and correlated traces ────────┘
```

## Boundaries and sequence

- The browser owns presentation and client interaction. Feature modules use shared typed services; components do not construct requests.
- Mock and HTTP adapters implement the same service contracts. Stage 1 uses mock data; Stage 3 replaces adapters after the backend/API contract is reviewed.
- FastAPI route handlers handle HTTP concerns only. Application use cases coordinate domain behavior. Domain rules do not depend on FastAPI or SQLAlchemy.
- SQLAlchemy repositories and Alembic migrations live in infrastructure. PostgreSQL is introduced in Stage 3.
- `openapi.yaml` is the shared contract. Contract changes must be reflected in client types, backend schemas, tests and docs.
- Observability configuration is introduced in Stage 2, before persistent backend implementation, and must pass its human review gate.
- Hosting choice remains open. Terraform is documentation/scaffolding only until cost review and explicit approval.

## Security and data integrity

Public reads require no account. Write operations require authentication and backend authorization, validation and rate limits. Personal data must be minimized and excluded from telemetry. AI-produced data stays a draft until a human verifies source and factual claims.

## Open decisions

Authentication provider and token lifecycle, geographic taxonomy, moderation operations, source provenance schema, and low-cost deployment target require review before their respective implementation stages.

