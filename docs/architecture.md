# Architecture

**Status:** Stages 2, 3, and 3.1 are complete and reviewed. Issue #75 accepts Lightsail Container Services for implementation. The Terraform migration, release workflows, live DSQL credential behavior, complete migration plan review, and cost/provisioning approval remain outstanding.

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
- Stage 4 release policy is PR CI, immutable backend image publishing, automatic development deployment after successful main CI, and manual production promotion gated on successful development verification. Promotion reuses the same verified image digest. Issue #75 replaces API VMs/static IPs with environment-specific Lightsail Container Services, managed TLS endpoints, Route 53 CNAMEs, public GHCR digest references, and Terraform-managed deployment versions in the existing root state. Terraform alone owns AWS infrastructure lifecycle; CLI use is limited to artifact publication and inspection. The service principal's ability to provide refreshable AWS credentials to the running app is unverified: Lightsail's IAM documentation does not establish this runtime credential path, so no DSQL compatibility claim is made pending live validation. Local Docker Compose continues to use PostgreSQL. Hosted telemetry remains deferred to Issue #59; backup/HA/recovery remain tracked by Issue #44. The new container size estimate is higher than the earlier VM estimate and requires fresh cost/provisioning approval before apply. See DEC-007, the [hosting proposal](stage4-hosting-options.md), and [DSQL compatibility review](dsql-compatibility-validation.md).

## Stage 4 full-stack release

The current worktree contains `.github/workflows/fullstack-release.yml` and `.github/workflows/deploy-production.yml`. PR checks gate release publishing; a successful `main` run builds an immutable backend image, records its digest and both provider-specific migration chains, then invokes the development environment adapter and records health/release evidence. Production is a separate manual dispatch that validates the commit's main history, successful CI, and successful dev deployment before promoting that exact backend digest. It builds the production frontend from the same commit with production public authentication settings. Telemetry is explicitly disabled in both frontend builds and the release manifest.

Issue #75's implementation composes the container runtime with existing DSQL, Cognito, DNS, and frontend state. The workflow deployment script uses a full plan and allows only the selected environment's deployment-version resource change. No AWS infrastructure mutation is included. The deployment-time DSQL runtime identity still requires live verification before release. See [DEC-007](decisions.md), the [Stage 4 plan](implementation-plan.md), and the [deployment runbook](deployment-aws-frontend.md).

## Security and data integrity

Public reads require no account. Write operations require authentication and backend authorization, validation and rate limits. Personal data must be minimized and excluded from telemetry. AI-produced data stays a draft until a human verifies source and factual claims.

## Open decisions

Geographic taxonomy, moderation operations, source provenance schema, and low-cost deployment target require review before their respective implementation stages. Stage 3 authentication and reportable-contribution API decisions are recorded in `docs/decisions.md` and specified in `openapi.yaml`; they do not authorize provisioning AWS resources.
