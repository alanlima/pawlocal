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
- Stage 4 release policy is PR CI, immutable backend image publishing, automatic development deployment after successful main CI, and manual production promotion gated on successful development verification. Promotion reuses the same verified image digest. Issue #75 keeps environment-specific Lightsail Container Services, managed TLS endpoints, Route 53 records, public GHCR digest references, and Terraform-managed deployment versions. Issue #135 changes their ownership: bootstrap owns shared OIDC trust, deployment-role identity, baseline permissions, and boundaries; development and production states each own only their application resources, environment policies, and matching attachments. Cross-environment retagging or updates are not accepted. Terraform alone owns AWS infrastructure lifecycle; CLI use is limited to approved artifact operations and read-only inspection. Each protected environment apply gates Lightsail deployment on a two-phase DSQL setup: the matching apply identity has exact-cluster administrative connection access to verify the application role, singleton runtime mapping, schema, and grants, then assumes only the matching runtime identity to apply and verify the clean application-owned baseline. Terraform records digest triggers and successful execution, not continuous ownership of native catalog objects. Local Docker Compose continues to use PostgreSQL. Hosted telemetry remains deferred to Issue #59; backup/HA/recovery remain tracked by Issue #44. Cost/provisioning approval remains required before application apply. See DEC-007, DEC-008, the [hosting proposal](stage4-hosting-options.md), and [DSQL compatibility review](dsql-compatibility-validation.md).
- Stage 4 identity uses one Terraform-managed Cognito user pool per environment. Both pools use case-insensitive usernames and passwords, open self sign-up, required `name`, no email/phone verification, and MFA off. Only minimum password length and the lowercase, uppercase, and number requirements vary by environment. A pre sign-up Lambda auto-confirms only self-service sign-ups so the user can sign in immediately without a confirmation code or privileged backend call; Cognito does not generally require this Lambda when another confirmation mechanism is used. See [DEC-009](decisions.md) and master [Issue #184](https://github.com/alanlima/pawlocal/issues/184).

## Stage 4 Issue #135 baseline

The former combined roots and workflows are reference material only. The legacy automatic release was fail-closed before the new roots were added; the former combined-state operation and rollback workflows remain inert. The active application entry points are `infra/terraform/environments/development` and `infra/terraform/environments/production`, called through `.github/workflows/terraform-environment.yml`. The existing `infra/terraform/iam-bootstrap` state remains authoritative for shared identity and boundaries.

The final backend keys are `pawlocal/iam-bootstrap/terraform.tfstate`, `pawlocal/development/terraform.tfstate`, and `pawlocal/production/terraform.tfstate`. Application resources begin in clean states; former application resources are never imported. Bootstrap declaratively adopts only the verified development publisher identity and the shared fixed identities selected by explicit reviewed inputs. Environment states own their resources, policies, and matching attachments; the module cannot manage role identity/trust/boundaries. Development must be planned, approved, applied, and verified before production becomes eligible.

Bootstrap permissions boundaries must not depend on generated full resource ARNs. Their write ceilings use a stable ARN for the intended resource family or a deterministic environment/name prefix. `Resource = "*"` is not a substitute for that scope: it is used only where an AWS create action has no resource-level authorization, and request-tag conditions constrain it where the service supports them. After the first environment apply, exact generated resource ARNs may tighten the environment-owned application, publisher, and runtime policies; effective access remains the intersection of those exact grants and the stable bootstrap boundary, so no bootstrap boundary rewrite is required. Runtime trust remains a separate staged handoff: the generated Lightsail service principal is supplied through an independently reviewed bootstrap plan. A trust principal is not a permissions-boundary resource exception. The DSQL runtime identity and refresh behavior still require live verification. See [DEC-008](decisions.md), the [operator guide](terraform-greenfield-operations.md), and the historical [deployment record](deployment-aws-frontend.md).

For DEC-009, the bootstrap state owns the deterministic Lambda execution roles and the environment deployment identities' bounded Lambda, log-group, and exact-role pass permissions. Environment states own their Cognito pools and dependent clients/domains, Lambda functions and packages, finite-retention log groups, Cognito invoke permissions, environment policies, and matching attachments. [Issue #186](https://github.com/alanlima/pawlocal/issues/186) implements and reviews the IAM boundary independently from [Issue #187](https://github.com/alanlima/pawlocal/issues/187). They may be developed in parallel only after the documentation issue is merged; the IAM change must be complete and merged before the Cognito change can complete or merge. No plan or apply gate is waived.

## Security and data integrity

Public reads require no account. Write operations require authentication and backend authorization, validation and rate limits. Personal data must be minimized and excluded from telemetry. AI-produced data stays a draft until a human verifies source and factual claims.

## Open decisions

Moderation operations and source provenance schema require review before their respective implementation stages. Stage 3 token validation and reportable-contribution API decisions are recorded in DEC-002 and `openapi.yaml`; the approved Stage 4 Cognito identity lifecycle is recorded in DEC-009. Issues #185 and #187 do not configure or test self-service password recovery, and users without a verified email address or phone number cannot use `ForgotPassword`. A future recovery policy, account deletion and retention, social federation, sign-up abuse controls, and production deletion protection remain separate decisions. Documentation approval does not authorize provisioning AWS resources.
