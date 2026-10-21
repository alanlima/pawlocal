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
| 4 Production readiness | Accepted Issue #75 service architecture: separate Lightsail Container Services for dev/prod with Terraform-managed deployment versions, managed HTTPS/custom domains, public digest-pinned images, and Aurora DSQL. Issue #135 rebuilds it with an isolated IAM bootstrap state and clean development and production application states; the former shared-state ownership layout is superseded. Local Compose keeps PostgreSQL by default. The initial release keeps hosted telemetry disabled; Stage 5 owns Grafana Cloud and on-call support. Backup/HA/recovery remain deferred to Issue #44. Release policy remains PR CI, automatic development deployment after successful main CI, and separate manually dispatched production promotion of the same development-verified backend digest. | First disable or fail-close the legacy automatic development deploy and verify it cannot run from an Issue #135 implementation merge. Before implementation, verify the partial teardown's live AWS/state result using read-only inspection. Independently review any bootstrap adoption plan, permit no former application-resource import, and require strict environment isolation. Cost/provisioning approval, live DSQL runtime credential/connectivity validation, exact-plan approvals, configured targets, and successful development verification remain gates. Do not claim an apply, deployment, or runtime result without evidence. |
| 5 Hosted observability and on-call support | After Stage 4 completes, Issue #59 enables Grafana Cloud and source-controlled support dashboards against the verified development deployment. Issue #42 adds the signed alert webhook, durable incident handoff and constrained support agent that can open a tested fix PR. | Development-first Grafana, privacy, cost and dashboard review; synthetic alert-to-agent-to-PR demonstration; human review and development verification. Production telemetry and promotion retain separate manual approvals. |
| 6 Submission | Rubric evidence, reproducibility, docs, demo and peer reviews. | Verify against the current course rubric. |

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
- Define dev-to-prod promotion of the same tested image and separate credentials/data. Keep hosted telemetry disabled for the initial release; Stage 5 owns the hosted telemetry provider, data residency, dashboards and alerts under Issue #59. Backup, HA, RPO/RTO, restore, and recovery/rollback planning are excluded from the MVP and deferred to Issue #44 after both environments are deployed. Preserve migration compatibility with the currently deployed application during each rollout.
- For Issue #135, implement a standalone bootstrap state plus clean development and production states. Bootstrap owns shared OIDC trust, deployment-role identity, baseline permissions, and permissions boundaries; each application state owns only its environment's application resources, managed policy, and matching attachment. Do not retain the prior accepted cross-environment CloudFront retag/update exception.
- Before any Issue #135 Terraform, workflow, or deployment-helper implementation merges, disable or make fail-closed the legacy automatic development-deploy path and verify a `main` merge cannot invoke the former combined-state deployment. Keep it disabled until the new environment roots, targets, credentials, and release path are configured and independently reviewed.
- Treat the Issue #135 purge and retained-role assumptions as pending read-only verification because the legacy destroy run was partial and PR #134 remains open. Import no application resources. Adopt only verified deployment-identity resources through reviewed Terraform configuration and a saved plan showing no duplicate ownership, replacement, or deletion.
- If inspection finds surviving application resources or bindings, block the affected environment and escalate the exact inventory, cost, and collision risk for a separately scoped, owner-approved, independently reviewed Terraform cleanup change. Do not adopt survivors into the new states; amend Issue #135 and DEC-008 first if cleanup-only orphan adoption is required.
- For Issue #43, implement PR checks followed by automatic dev deployment after successful main CI, then a separate `workflow_dispatch` production promotion of a validated release verified in dev. Validate main ancestry, required CI and successful dev verification; promote the same backend image by immutable digest. Do not automatically deploy production on main merges.
- Separate GitHub `development` and `production` environments and frontend/API/database endpoints, secrets and deployment credentials. Use `pawlocal-dev.<domain>` for development and `pawlocal.<domain>` for production. Keep Vite public configuration environment-safe and never place secrets in browser assets.
- Serialize production deployment (`cancel-in-progress: false`), use least-privilege short-lived credentials/OIDC where supported, record commit/image/frontend/migration identifiers and results, run health/smoke checks, and ensure migrations remain compatible with the currently deployed application. Recovery/rollback procedures are deferred to Issue #44.
- Issue #43's approved MVP budget and selected Lightsail + DSQL direction do not authorize a new Issue #135 application apply. Deployment remains gated on refreshed cost/provisioning approval, live DSQL validation, target/secret configuration, and review of the specific Terraform plan before provisioning. Historical mock-backed static deployment evidence does not demonstrate the new full-stack policy.
- Document budget alerts and teardown procedures. Do not add backup/restore or recovery guarantees to the MVP; review them under Issue #44 after cloud deployment.
- Keep hosted telemetry and user-impact alerts disabled throughout Stage 4; enable and evaluate them in Stage 5 under Issue #59 after the Stage 4 gate is complete. Existing local observability requirements and completed Stage 2/3.1 gates remain unchanged.
- Any billable provisioning has explicit human approval before execution.

### P5 — Enable hosted observability and on-call support

**Acceptance criteria:**
- Under Issue #59, enable privacy-safe Grafana Cloud telemetry in development and make correlated search-to-place-details metrics, traces and structured logs viewable through source-controlled support dashboards.
- Provision reusable dashboards for user journeys, API/application health, database/dependencies, releases, telemetry delivery and incident triage, with consistent environment/service/release variables and bounded cardinality.
- Demonstrate at least one development user-impact alert with documented threshold, no-data behavior, dashboard link, runbook, firing and resolution evidence.
- Under Issue #42, receive signed Grafana alerts through `POST /api/v1/webhooks/grafana/alerts`, validate and deduplicate them, and durably queue an asynchronous support-agent run.
- Demonstrate a safe synthetic incident that automatically wakes the constrained agent, produces a regression test and fix PR, passes independent review, deploys after human merge to development, and resolves the alert.
- Prove the agent cannot approve or merge, mutate AWS infrastructure, apply Terraform, access unrestricted production credentials or deploy production.
- Enable production telemetry only after development evidence, privacy review, cost approval and production approval. Keep production deployment as a manual promotion of the exact development-verified release.

### P6 — Prepare and verify final submission

**Acceptance criteria:**
- Compare implementation evidence against the current official scoring rubric.
- README, setup, architecture, tests, deployment and AI workflow/review docs are reproducible and current.
- Demo evidence and required peer reviews are complete.

