# Stage 0 implementation plan and issue proposals

Repository: [alanlima/pawlocal](https://github.com/alanlima/pawlocal). The initial repository commit is pushed. Stage 0 was approved for Stage 1 on 2026-10-17; the implementation issues are tracked in GitHub. Do not commit implementation to `main`.

## Staged plan

| Stage | Scope | Gate |
|---|---|---|
| 0 Foundations | Review product requirements, API, architecture, agent workflow and backlog; resolve open decisions; establish repository conventions. | Human review of Stage 0 docs and plan. |
| 1 Frontend with mock API | Responsive accessible React app, typed services, realistic mock data and MVP journeys/tests. | Stop for human review before Stage 2. |
| 2 Observability | OpenTelemetry, Grafana, Prometheus, Loki, Tempo, user-journey instrumentation and synthetic failures. | Monitoring and dashboards reviewed before backend work. |
| 3 Backend and persistence | FastAPI, modular domain/use cases, PostgreSQL, SQLAlchemy/Alembic, auth/contributions and HTTP adapter. | Demonstrate frontend-to-backend-to-database persistence. |
| 4 Production readiness | Compose startup, CI/CD, costed hosting evaluation, approved deployment, user-impact alerts and controlled incident response. | Explicit approval before billable infrastructure. |
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

### P2 — Add observability before backend implementation

**Context:** Monitoring is a required architectural stage and must precede Stage 3.  
**Acceptance criteria:**
- Instrument search-to-place-details behavior with structured logs, correlated traces and latency/error/user-impact metrics.
- Provide inspectable Grafana dashboards backed by approved telemetry components.
- Demonstrate synthetic failure scenarios and recovery evidence.
- Exclude personal information and document retention/configuration.
- Obtain human review before backend implementation begins.

### P3 — Implement backend and persistence against the approved contract

**Acceptance criteria:**
- FastAPI route handlers remain thin; use cases, domain rules and persistence are separated.
- PostgreSQL models, SQLAlchemy repositories and Alembic migrations support approved MVP data.
- Public browse and authenticated contribution/favourite/report operations match `openapi.yaml`.
- Validation, authorization, rate limits and duplicate review protection are enforced server-side.
- HTTP frontend adapter replaces mock adapter behind the same interface; tests cover unit/integration/E2E behavior.
- Demonstrate full frontend-to-API-to-database persistence and update contract/docs.

### P4 — Prepare production readiness with cost and safety review

**Acceptance criteria:**
- Docker Compose starts the approved local stack reproducibly; CI runs relevant checks.
- Compare hosting alternatives and estimate idle/low-traffic monthly costs, including database, network, telemetry and backups.
- Document budget alerts, teardown and recovery procedures.
- Instrument and alert on user-impact failures; incident remediation is bounded, logged and recovery-verified.
- Any billable provisioning has explicit human approval before execution.

### P5 — Prepare and verify final submission

**Acceptance criteria:**
- Compare implementation evidence against the current official scoring rubric.
- README, setup, architecture, tests, deployment and AI workflow/review docs are reproducible and current.
- Demo evidence and required peer reviews are complete.

