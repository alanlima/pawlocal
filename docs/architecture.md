# Architecture

**Status:** Stages 2, 3, and 3.1 are complete and reviewed. Issue #75 accepts Lightsail Container Services and Aurora DSQL. Issue #135 replaces the former shared application-state layout with the existing standalone IAM bootstrap state plus clean development and production application states. Corrected read-only inventory verified the former application state is empty, no PawLocal application resources survive, and an unrelated account-level personal workload is out of scope. The new roots and workflows are implemented, but no bootstrap import/apply, application apply, or deployment is complete.

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

The former combined roots and workflows are reference material only. The legacy automatic release was fail-closed before the new roots were added; the former combined-state operation and rollback workflows remain inert. The active application entry points are `infra/terraform/environments/development` and `infra/terraform/environments/production`, called through `.github/workflows/terraform-environment.yml`. The existing `infra/terraform/iam-bootstrap` state remains authoritative for shared identity and boundaries.

The final backend keys are `pawlocal/iam-bootstrap/terraform.tfstate`, `pawlocal/development/terraform.tfstate`, and `pawlocal/production/terraform.tfstate`. Application resources begin in clean states; former application resources are never imported. Bootstrap declaratively adopts only the verified development publisher identity and the shared fixed identities selected by explicit reviewed inputs. Environment states own their resources, policies, and matching attachments; the module cannot manage role identity/trust/boundaries. Development must be planned, approved, applied, and verified before production becomes eligible. Bootstrap permissions boundaries use stable pre/post-deploy resource-family ceilings and do not accept generated CloudFront distribution or OAC ARNs. After the first environment apply, the exact CloudFront ARNs tighten only the environment-owned application policy, whose grants remain intersected with the stable boundary; this does not require another bootstrap plan. Runtime trust remains a separate staged handoff: the generated Lightsail service principal is supplied through an independently reviewed bootstrap plan. The DSQL runtime identity and refresh behavior still require live verification. See [DEC-008](decisions.md), the [operator guide](terraform-greenfield-operations.md), and the historical [deployment record](deployment-aws-frontend.md).

## Security and data integrity

Public reads require no account. Write operations require authentication and backend authorization, validation and rate limits. Personal data must be minimized and excluded from telemetry. AI-produced data stays a draft until a human verifies source and factual claims.

## Open decisions

Geographic taxonomy, moderation operations, source provenance schema, and low-cost deployment target require review before their respective implementation stages. Stage 3 authentication and reportable-contribution API decisions are recorded in `docs/decisions.md` and specified in `openapi.yaml`; they do not authorize provisioning AWS resources.
