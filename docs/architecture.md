# Architecture

**Status:** Stages 2, 3, and 3.1 are complete and reviewed. Issue #43 workflow code is implemented in PR #61; the Lightsail hosting direction and MVP budget are approved. Database-provider/runtime-identity validation and the deployable cloud target/adapter configuration remain outstanding.

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
- Stage 4 workflow code in PR #61 provides PR checks, immutable backend image publishing, automatic development deployment control flow after successful main CI, and manual production promotion gated on successful development verification. Promotion reuses the same verified backend image digest; frontend assets are built with environment-specific public Cognito settings. Deployment is behind a provider-neutral adapter interface. The Lightsail hosting direction and MVP budget are approved, but the adapter, deployable app target, and GitHub environment/OIDC role configuration are absent. No AWS resources have been provisioned through this work and no cloud deployment has occurred. Aurora DSQL remains a candidate pending schema/migration compatibility and a secure runtime identity/credential path; see [the hosting proposal](stage4-hosting-options.md) and [DSQL compatibility review](dsql-compatibility-validation.md). Local Docker Compose continues to use PostgreSQL by default. The initial release keeps hosted telemetry disabled; enablement is deferred to [Issue #59](https://github.com/alanlima/pawlocal/issues/59). Backup, HA, RPO/RTO, restore, recovery, and rollback remain outside MVP scope and deferred to [Issue #44](https://github.com/alanlima/pawlocal/issues/44). The MVP budget is approved; deployment remains gated on database validation and a configured target/identity path.

## Stage 4 full-stack release

The current worktree contains `.github/workflows/fullstack-release.yml` and `.github/workflows/deploy-production.yml`. PR checks gate release publishing; a successful `main` run builds an immutable backend image, records its digest and both provider-specific migration chains, then invokes the development environment adapter and records health/release evidence. Production is a separate manual dispatch that validates the commit's main history, successful CI, and successful dev deployment before promoting that exact backend digest. It builds the production frontend from the same commit with production public authentication settings. Telemetry is explicitly disabled in both frontend builds and the release manifest.

The workflows are implementation code, not a completed deployment. The environment adapter is intentionally not implemented; GitHub development/production environments, their scoped AWS OIDC roles and endpoint/configuration variables are not configured. The Lightsail application-hosting direction is approved, but database-provider selection and DSQL runtime identity remain unresolved. No AWS resources have been provisioned through this work and no full-stack deployment has occurred. The static frontend Terraform configuration documents a separate legacy S3/CloudFront option and does not implement the full-stack adapter. Backup, HA, RPO/RTO, restore, recovery, and rollback are excluded from this release and deferred to Issue #44; telemetry enablement is deferred to Issue #59. See [DEC-004 and DRAFT-002](decisions.md), the [Stage 4 plan](implementation-plan.md), and the [deployment runbook](deployment-aws-frontend.md).

## Security and data integrity

Public reads require no account. Write operations require authentication and backend authorization, validation and rate limits. Personal data must be minimized and excluded from telemetry. AI-produced data stays a draft until a human verifies source and factual claims.

## Open decisions

Geographic taxonomy, moderation operations, source provenance schema, and low-cost deployment target require review before their respective implementation stages. Stage 3 authentication and reportable-contribution API decisions are recorded in `docs/decisions.md` and specified in `openapi.yaml`; they do not authorize provisioning AWS resources.
