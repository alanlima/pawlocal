# PawLocal implementation plan

Repository: [alanlima/pawlocal](https://github.com/alanlima/pawlocal). Stage 0 was approved for Stage 1 on 2026-10-17. The Stage 2 and Stage 3 specifications were approved on 2026-10-18; their issues are tracked in GitHub. Do not commit implementation to `main`.

## Staged plan

| Stage | Scope | Gate |
|---|---|---|
| 0 Foundations | Review product requirements, API, architecture, agent workflow and backlog; resolve open decisions; establish repository conventions. | Human review of Stage 0 docs and plan. |
| 1 Frontend with mock API | Responsive accessible React app, typed services, realistic mock data and MVP journeys/tests. | Stop for human review before Stage 2. |
| 2 Local frontend and observability | Dockerized frontend, local OpenTelemetry, Grafana, Prometheus, Loki, Tempo, user-journey instrumentation and synthetic failures. | Use a dedicated branch/worktree. Review monitoring, dashboards, privacy and failure evidence before Stage 3.1 starts and before Stage 3 is complete. |
| 3 Backend and persistence | FastAPI, modular domain/use cases, PostgreSQL, SQLAlchemy/Alembic, auth/contributions and HTTP adapter. | May start in parallel with Stage 2 in a separate branch/worktree. Demonstrate frontend-to-backend-to-database persistence; do not complete until the Stage 2 review gate passes and Stage 3.1 cross-layer instrumentation and Compose integration are completed and reviewed. |
| 3.1 Cross-layer instrumentation and Compose integration | Extend traces/logs through browser, API and database; reconcile and verify Stage 2/3 Compose services. | Start after Stage 2 review; use a coordinated separate worktree and may proceed while Stage 3 continues. |
| 4 Production readiness | Compose startup, CI/CD, costed hosting proposal, and full-stack deployment. The owner selected Aurora DSQL and confirmed Lightsail with access-key runtime authentication. Credential values are local or GitHub Actions environment variables and must remain outside Terraform inputs/state. Key issuance and runtime delivery are blocked pending direction because external key creation would violate Terraform-only ownership. GitHub deployments use scoped OIDC roles. Local Compose keeps PostgreSQL by default. The MVP budget is approved. Keep application telemetry disabled until Issue #59; backup/HA/recovery planning is deferred to Issue #44 after both environments deploy. Release policy is PR CI, automatic development deployment after a successful main merge, and separate manually dispatched production promotion of a release verified in development. | Live DSQL compatibility/runtime validation, an approved access-key issuance/runtime path, a reviewed Terraform plan, and separate configured targets remain gates. Do not claim hosted telemetry, backup, HA, RPO/RTO, restore, or rollback guarantees for the MVP. |
| 5 Submission | Rubric evidence, reproducibility, docs, demo and peer reviews. | Verify against the current course rubric. |

## Proposed issues

### P0 — Review and approve Stage 0 product and API foundations

**Context:** `product-spec.md`, `openapi.yaml`, and `docs/architecture.md` establish a draft MVP scope and contract.  
**Acceptance criteria:**
- Review unresolved product decisions in the specification and record outcomes.
- Confirm MVP acceptance criteria and out-of-scope boundaries.
- Review endpoints, authorization, validation and error behavior in OpenAPI.
- Approve or amend architecture boundaries and stage gates.
- Record decisions in `docs/decisions.md`; update contract and docs consistently.

### P1 — Establish Stage 1 frontend with interchangeable mock services

**Context:** Begin only after Stage 0 review. Build MVP journeys against the approved spec and contract.  
**Acceptance criteria:**
- Responsive React/TypeScript/Vite/Tailwind application follows feature-based modules.
- Typed service interfaces isolate all data access; mock adapter and realistic sample data work without a backend.
- Search/filter, place details/permanent URL, favourites and contribution/report journeys match approved scope.
- Loading, error and empty states are accessible and tested with Vitest/RTL; relevant E2E flows are covered.
- No future-scope feature is added; Stage 1 review evidence is recorded and gate approval requested.

### P2 — Add local frontend and observability

**Context:** Stage 2 is a required architectural stage. Its implementation may run in parallel with Stage 3 after both specs are approved and both issues are open; its review gate remains required before Stage 3 completion.
**Acceptance criteria:**
- Instrument search-to-place-details behavior with structured logs, correlated traces and latency/error/user-impact metrics.
- Provide inspectable Grafana dashboards backed by approved telemetry components.
- Demonstrate synthetic failure scenarios and recovery evidence.
- Exclude personal information and document retention/configuration.
- Use a dedicated branch and worktree, separate from Stage 3.
- Obtain human review before Stage 3.1 starts and before Stage 3 is marked complete.

### P3 — Implement backend and persistence against the approved contract

**Acceptance criteria:**
- FastAPI route handlers remain thin; use cases, domain rules and persistence are separated.
- PostgreSQL models, SQLAlchemy repositories and Alembic migrations support approved MVP data.
- Public browse and authenticated contribution/favourite/report operations match `openapi.yaml`.
- Validation, authorization, rate limits and duplicate review protection are enforced server-side.
- HTTP frontend adapter replaces mock adapter behind the same interface; tests cover unit/integration/E2E behavior.
- Demonstrate full frontend-to-API-to-database persistence and update contract/docs.
- Complete and review Stage 3.1 correlated tracing/logging and combined Compose integration evidence before marking Stage 3 complete.
- Use a dedicated branch and worktree, separate from Stage 2.
- Obtain Stage 2 review before Stage 3 is marked complete.

### P3.1 — Extend observability across the backend and integrate Compose

**Context:** Begin after Stage 2 is complete and reviewed. Stage 3.1 may proceed while Stage 3 backend implementation continues, using a separate coordinated worktree.

**Acceptance criteria:**
- Propagate trace context across browser, API and database and add concise structured backend logs with privacy-safe correlation context.
- Reconcile the Stage 2 and Stage 3 root Compose changes while preserving all required services.
- Verify the combined stack, synthetic failures and clean shutdown; report exact evidence in the PR.

### P4 — Prepare production readiness with cost and safety review

**Acceptance criteria:**
- Docker Compose starts the approved local stack reproducibly; CI runs relevant checks.
- Compare hosting alternatives and estimate idle/low-traffic monthly costs, including database, network, telemetry and backups.
- Validate Aurora DSQL against the actual models, repositories and Alembic migrations; compare PostgreSQL alternatives if material incompatibilities remain.
- Define dev-to-prod promotion of the same tested image and separate credentials/data. Keep hosted telemetry disabled for the initial release; hosted telemetry provider, data residency, dashboards and alerts are deferred to Issue #59. Backup, HA, RPO/RTO, restore, and recovery/rollback planning are excluded from the MVP and deferred to Issue #44 after both environments are deployed. Preserve migration compatibility with the currently deployed application during each rollout.
- For Issue #43, implement PR checks followed by automatic dev deployment after successful main CI, then a separate `workflow_dispatch` production promotion of a validated release verified in dev. Validate main ancestry, required CI and successful dev verification; promote the same backend image by immutable digest. Do not automatically deploy production on main merges.
- Separate GitHub `development` and `production` environments and frontend/API/database endpoints, secrets and deployment credentials. Use `pawlocal-dev.<domain>` for development and `pawlocal.<domain>` for production. Keep Vite public configuration environment-safe and never place secrets in browser assets.
- Serialize production deployment (`cancel-in-progress: false`), use least-privilege short-lived credentials/OIDC where supported, record commit/image/frontend/migration identifiers and results, run health/smoke checks, and ensure migrations remain compatible with the currently deployed application. Recovery/rollback procedures are deferred to Issue #44.
- Issue #43's approved MVP budget and selected Lightsail + DSQL direction are recorded in DRAFT-002; deployment remains gated on live DSQL validation, target/secret configuration, and review of the specific Terraform plan before provisioning. The existing mock-backed static production deployment is separate and does not demonstrate the full-stack policy.
- Document budget alerts and teardown procedures. Do not add backup/restore or recovery guarantees to the MVP; review them under Issue #44 after cloud deployment.
- Keep hosted telemetry and user-impact alerts disabled for the MVP; evaluate them under Issue #59 after the full-stack deployment. Existing local observability requirements and completed Stage 2/3.1 gates remain unchanged.
- Any billable provisioning has explicit human approval before execution.

### P5 — Prepare and verify final submission

**Acceptance criteria:**
- Compare implementation evidence against the current official scoring rubric.
- README, setup, architecture, tests, deployment and AI workflow/review docs are reproducible and current.
- Demo evidence and required peer reviews are complete.

