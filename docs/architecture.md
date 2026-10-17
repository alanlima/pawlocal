# Architecture

**Status:** Stage 0 foundations were approved on 2026-10-17. Stage 1 frontend is implemented; the Stage 2/3 specifications were approved on 2026-10-18. Stage 2/3 implementation and Stage 3.1 integration follow the gates below.

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
- Stage 2 local frontend/observability and Stage 3 backend/persistence may start in parallel after their specifications are human-approved and both issues are open. They must use separate branches and Git worktrees because both may edit root Compose configuration.
- Stage 2's monitoring review gate must pass before Stage 3 is considered complete and before Stage 3.1 starts. Stage 3.1 adds browser-to-API-to-database tracing and structured backend logs and reconciles the two Compose stacks; it may proceed in its own coordinated worktree while Stage 3 continues. Stage 3 cannot be marked complete until Stage 3.1 integration and independent review evidence are complete.
- Hosting choice remains open. Terraform is documentation/scaffolding only until cost review and explicit approval.

## Security and data integrity

Public reads require no account. Write operations require authentication and backend authorization, validation and rate limits. Personal data must be minimized and excluded from telemetry. AI-produced data stays a draft until a human verifies source and factual claims.

## Open decisions

Geographic taxonomy, moderation operations, source provenance schema, and low-cost deployment target require review before their respective implementation stages. Stage 3 authentication and reportable-contribution API decisions are recorded in `docs/decisions.md` and specified in `openapi.yaml`; they do not authorize provisioning AWS resources.

