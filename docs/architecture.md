# Architecture

**Status:** Stages 2, 3, and 3.1 are complete and reviewed. Issue #75 accepts Lightsail Container Services and Aurora DSQL. Issue #135 replaces the former shared application-state layout with a clean IAM bootstrap state and separate development and production application states. The final legacy teardown run was partial, so the current AWS/state inventory remains unverified pending read-only inspection. No Issue #135 application root, workflow, plan, apply, or deployment is documented as complete.

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
- Stage 4 release policy is PR CI, immutable backend image publishing, automatic development deployment after successful main CI, and manual production promotion gated on successful development verification. Promotion reuses the same verified image digest. Issue #75 keeps environment-specific Lightsail Container Services, managed TLS endpoints, Route 53 records, public GHCR digest references, and Terraform-managed deployment versions. Issue #135 changes their ownership: bootstrap owns shared OIDC trust, deployment-role identity, baseline permissions, and boundaries; development and production states each own only their application resources, environment policy, and matching attachment. Cross-environment retagging or updates are not accepted. Terraform alone owns AWS infrastructure lifecycle; CLI use is limited to approved artifact operations and read-only inspection. The running service's DSQL credential behavior remains unverified pending live validation. Local Docker Compose continues to use PostgreSQL. Hosted telemetry remains deferred to Issue #59; backup/HA/recovery remain tracked by Issue #44. Cost/provisioning approval remains required before application apply. See DEC-007, DEC-008, the [hosting proposal](stage4-hosting-options.md), and [DSQL compatibility review](dsql-compatibility-validation.md).

## Stage 4 Issue #135 baseline

The checked-in Terraform roots and deployment workflows predate Issue #135 and are reference material only. Do not run them as the greenfield deployment path. The partial legacy teardown and open PR #134 mean repository text alone cannot establish which AWS resources or state bindings remain. Before implementation, perform read-only AWS and Terraform state inspection, reconcile the result with Issue #135, and identify the exact deployment IAM resources eligible for bootstrap adoption.

Issue #135 implementation must define the final root paths, backend keys, workflow names, outputs, GitHub Environment configuration, and operator commands. Until that reviewed implementation exists, no document may supply guessed values. Application resources begin in clean development and production states; former application resources are not imported. Bootstrap adoption is limited to the independently verified deployment identity through a reviewed Terraform import visible in the saved plan. Development must be planned, approved, applied, and verified before production becomes eligible. The deployment-time DSQL runtime identity still requires live verification before production release. See [DEC-008](decisions.md), the [Stage 4 plan](implementation-plan.md), and the historical [deployment record](deployment-aws-frontend.md).

## Security and data integrity

Public reads require no account. Write operations require authentication and backend authorization, validation and rate limits. Personal data must be minimized and excluded from telemetry. AI-produced data stays a draft until a human verifies source and factual claims.

## Open decisions

Geographic taxonomy, moderation operations, source provenance schema, and low-cost deployment target require review before their respective implementation stages. Stage 3 authentication and reportable-contribution API decisions are recorded in `docs/decisions.md` and specified in `openapi.yaml`; they do not authorize provisioning AWS resources.
