# PawLocal - Agent Instructions

## 1. Project overview

**PawLocal** is a free, community-powered web application for discovering dog-friendly places across South East Queensland, from the Gold Coast through Brisbane and Moreton Bay to the Sunshine Coast.

### Problem
Information about dog-friendly locations is scattered, incomplete or outdated. Dog owners struggle to find reliable details about fencing, off-leash rules, shade, drinking water, access restrictions and nearby cafes.

### Solution
Build a searchable, community-maintained directory where visitors discover places and registered users contribute information.

### Core MVP capabilities
- Browse dog parks, beaches, walks, hiking areas and pet-friendly cafes.
- Search and filter by location, category and facilities.
- View detailed place information.
- Share individual places through permanent public URLs.
- Registered users can save favourites, submit ratings and reviews, suggest locations, and publish tips or corrections.
- Users can report inaccurate or inappropriate content.
- AI can generate listing drafts from permitted public sources, but these require human approval before publishing.

Community contributions publish immediately, subject to validation, abuse protection and reporting.

### Future scope

**Do not implement future features without explicit approval.**

---

## 2. Technical stack

| Component | Technology |
|---|---|
| Frontend | React, TypeScript, Vite |
| Styling | Tailwind CSS |
| Backend | Python, FastAPI, Pydantic |
| Database | PostgreSQL, SQLAlchemy 2, Alembic |
| API contract | OpenAPI |
| Tests | Vitest, React Testing Library, Playwright, pytest |
| Containerisation | Docker Compose |
| Observability | OpenTelemetry, Grafana, Prometheus, Loki, Tempo |
| Infrastructure | AWS, Terraform |
| CI/CD | GitHub Actions |
| Agent orchestration | AWS Labs CLI Agent Orchestrator (CAO) |

The accepted Issue #75 hosting design uses Lightsail Container Services and Aurora DSQL; cost approval is still mandatory before provisioning or applying billable AWS changes.

---

## 3. Repository structure

Follow the DataTalksClub AI Dev Tools Zoomcamp conventions.

```text
pawlocal/
├── README.md
├── AGENTS.md
├── product-spec.md
├── openapi.yaml
├── docker-compose.yml
├── .env.example
├── frontend/
├── backend/
├── tests/
├── docs/
│   ├── architecture.md
│   ├── agent-workflow.md
│   ├── model-policy.md
│   ├── decisions.md
│   ├── testing.md
│   └── ai-usage-report.md
├── agents/
│   ├── profiles/
│   │   ├── orchestrator.md
│   │   ├── frontend-engineer.md
│   │   ├── backend-engineer.md
│   │   ├── platform-engineer.md
│   │   └── reviewer.md
│   └── README.md
├── observability/
│   ├── grafana/
│   ├── prometheus/
│   ├── loki/
│   └── tempo/
├── infra/
│   └── terraform/
├── security/
├── ops/
└── .github/
    └── workflows/
```

Maintain the agreed structure. Propose architectural changes through a documented decision before implementation.

---

## 4. Development stages

Implementation must happen in the following order.

### Stage 0 — Foundations
- Finalise product specifications and acceptance criteria.
- Configure CAO agents and their responsibilities.
- Establish repository conventions.
- Create GitHub Issues covering implementation tasks.
- Prepare the OpenAPI contract and architectural documentation.

### Stage 1 — Frontend with mock API
- Build a responsive React application.
- Centralise backend calls behind typed service interfaces.
- Implement mock services and realistic sample data.
- Implement all approved MVP user journeys.
- Write frontend and component tests.

**Gate:** Stop for human review and approval before continuing.

### Stage 2 — Local frontend and observability
- Configure OpenTelemetry, Grafana, Loki, Tempo and Prometheus.
- Add the frontend and local observability stack to the root Docker Compose setup.
- Keep the local telemetry toggle enabled by default; verify the app works with telemetry disabled.
- Demonstrate synthetic failure scenarios.
- Run in a dedicated branch and worktree.

**Gate:** Monitoring infrastructure, dashboards, privacy, and synthetic-failure checks must be reviewed before Stage 2 is complete and before Stage 3.1 begins. Stage 3 backend implementation may proceed in parallel after both workstream specs are approved and its issue is open.

### Stage 3 — Backend and persistence
- Implement FastAPI using clean modular architecture.
- Create PostgreSQL models and Alembic migrations.
- Integrate authentication and contribution workflows.
- Implement APIs against the approved OpenAPI contract.
- Replace frontend mock adapters with HTTP adapters.
- Add unit, integration and end-to-end tests.
- Work in its own branch and worktree, separate from Stage 2.

**Gate:** Confirm working frontend-to-backend-to-database persistence. Stage 2's review gate must pass, and Stage 3.1 cross-layer tracing/logging plus combined Compose integration must be completed and reviewed before Stage 3 is complete.

### Stage 3.1 — Cross-layer instrumentation and Compose integration
- Begin only after Stage 2 is complete and reviewed; may proceed while Stage 3 continues.
- Extend trace context across browser, API and database; add concise structured backend logs.
- Reconcile Stage 2 and Stage 3 root Compose changes and verify all services together.
- Use a dedicated branch and worktree coordinated with Stage 3.

**Gate:** Review cross-layer trace/log privacy, synthetic failure evidence, and the combined Compose stack before completing Stage 3.1.

### Stage 4 — Production readiness
- Validate complete Docker Compose startup.
- Implement CI/CD.
- Desired release model: pull requests run applicable CI; successful merges to `main` publish and automatically deploy a verified release to development; production promotion is a separate `workflow_dispatch` action selecting a release already verified in development. Ordinary feature merges must not deploy automatically to production. The owner-approved Issue #239 incident MVP is the scoped exception: after machine checks and verified development release, a separate trusted promoter automatically dispatches that exact release to production without a runtime human approval.
- Keep any historical mock-backed static frontend release evidence distinct from the full-stack release model. Issue #135 rebuilds the approved Issue #75 architecture from clean application states: one standalone IAM bootstrap state and separate development and production application states. Do not migrate or preserve the former application state, and do not point a workflow at unconfigured targets or credentials.
- Before merging any Issue #135 Terraform, deployment-workflow, or deployment-helper implementation, disable or make fail-closed the legacy automatic development-deploy path and verify that a `main` merge cannot invoke the former combined-state deployment. Keep that path disabled until the new environment roots, targets, credentials, and release path are configured and independently reviewed.
- Use `pawlocal-dev.<domain>` for the development site and `pawlocal.<domain>` for production. No domain, DNS, certificate, target, or secret is authorized by this naming convention alone.
- Evaluate AWS hosting alternatives and running costs.
- Obtain human approval before provisioning billable resources.
- Deploy development and production environments.
- Implement user-impact alerts and an automated incident responder.
- Demonstrate rollback and controlled recovery.

### Stage 5 — Submission
- Verify each Zoomcamp scoring criterion.
- Prepare README, architecture diagrams and demonstration evidence.
- Ensure the application is reproducible.
- Complete the required peer reviews.

---

## 5. Agent team

CAO is responsible for orchestrating specialised agents.

### Orchestrator
Owns planning, task coordination, delegation, integration review and acceptance gates.

The orchestrator must not silently bypass review or expand the project scope.
Before creating or editing a GitHub issue or PR, the orchestrator must review the rendered description for readability, formatting, accurate scope/status/evidence, and irrelevant template sections. Follow `docs/issue-pr-descriptions.md`.

Merge pull requests with GitHub's squash method so each PR adds one commit to `main`. The repository should allow squash merging and disable merge commits and rebase merging to enforce this history policy. Do not rewrite existing history as part of this policy.

### Frontend Engineer
Owns React, TypeScript, UI components, mock services, client-side behaviour and frontend tests.

### Backend Engineer
Owns FastAPI, database integration, application services, API contracts, authentication and backend tests.

### Platform Engineer
Owns Docker, observability, CI/CD, AWS and Terraform.

Infrastructure provisioning requires explicit human approval.

### Reviewer
Independently evaluates implementation against requirements, code quality, tests, security and acceptance criteria.

Review does not automatically authorise merging.

Each agent should read its relevant profile under `agents/profiles/` and the appropriate project documentation.

---

## 6. GitHub workflow — mandatory

All implementation work must be traceable.

1. Create or reference an existing GitHub Issue.
2. Confirm the issue includes context and acceptance criteria.
3. Apply labels so issues are easy to identify and triage: at least one project-stage label (for example, `stage-0` or `stage-1`) and one work-type label (such as `bug`, `enhancement`, `documentation`, or `review`). Add a priority label when one is established. Use `deferred` for work intentionally postponed to a later stage; remove it when that work is resumed.
4. Create a branch linked to the issue.
5. Implement only the approved scope.
6. Add or update relevant tests.
7. Run applicable checks.
8. Open a Pull Request linking the issue.
9. Record implementation details, decisions and verification evidence.
10. Review and address Pull Request comments.
11. Merge only after required approvals. For the activated Issue #239 incident MVP, the required approvals are the trusted fresh-review verdict and real required CI; a separate trusted job squash-merges automatically without human review or a bypass actor.

Labels support triage. They do not represent approval or completion, replace verification of an issue's acceptance criteria, or authorize bypassing a project gate.

Do not commit implementation directly to `main`.

Do not close an issue simply because code has been written. Verify its acceptance criteria first.

---

## 7. Architecture and coding standards

### General
- Prefer simple, maintainable solutions.
- Follow SOLID principles where they improve clarity.
- Use clear naming and explicit dependencies.
- Avoid unnecessary abstraction and premature microservices.
- Keep configuration externalised.
- Configuration consumed by GitHub Actions that requires synchronization into Environment variables or secrets must update `ops/configuration/parameter-mapping.yaml` and `docs/configuration-inventory.md` in the same PR whenever added, changed, removed, or renamed. This rule does not apply to unrelated application/local configuration or operator inputs intentionally outside synchronization. Follow `docs/configuration-management.md`; remove obsolete mappings and preserve original inventory fields, obsolete date, reason and separate deletion status in history. The specification-only #204 establishes this contract; #205 creates the manifest before synchronized configuration implementation begins.
- Never hardcode credentials or secrets.
- Preserve separation between domain logic and infrastructure.

### Frontend
- Use feature-based modules.
- Components must not directly construct backend requests.
- Centralise API access behind typed service interfaces.
- Keep mock and HTTP adapters interchangeable.
- Include loading, error and empty states.
- Ensure responsive and accessible UI.
- Reuse place-card components across discovery, favourites and sharing.

### Backend
Use clear boundaries between:
- API and HTTP concerns.
- Application use cases.
- Domain entities and business rules.
- Infrastructure and persistence implementations.

Keep FastAPI route handlers thin.

Use SQLAlchemy repositories, Alembic migrations and Pydantic schemas.

Avoid business logic directly inside HTTP handlers or database models.

### API
`openapi.yaml` represents the agreed API contract.

Changes to contracts must be reflected in frontend types, backend implementation, tests and documentation.

---

## 8. Security and data integrity

- Anonymous visitors may browse public information.
- Authentication is required for contributions and favourites.
- Enforce authorisation on backend endpoints.
- Validate user submissions and apply rate limiting.
- Prevent duplicate or abusive ratings and reviews.
- Community reports must support moderation.
- AI-generated listing drafts require human verification.
- Never invent locations, facilities or dog-access rules.
- Avoid exposing personal information in logs or traces.
- Use least-privilege access for agents and cloud resources.

---

## 9. Observability requirements

Monitoring is a core architectural requirement, not a final-stage addition.

Instrument the place-discovery journey:

**Search → API → database → place details**

Collect:
- Structured logs.
- Correlated traces.
- Latency and error metrics.
- User-impact indicators.

Telemetry must be inspectable through Grafana or an equivalent supported interface.

Alerting should focus on failures affecting actual user journeys.

The incident responder must demonstrate controlled, auditable remediation, with recovery verification.

Do not give incident agents unrestricted production permissions.

---

### Unattended incident MVP exception — Issue #239

The owner requires the allowlisted application-remediation MVP to run end to end without human approval: alert → triage/fix → fresh independent review → trusted PR → real candidate CI → trusted automatic squash merge → verified development → automatic exact-release production promotion → verified recovery. No runtime human merge, Environment review or production-promotion gate is permitted; an optional human-approval switch is deferred, not part of this implementation.

Initial setup still requires selected model/rates, enforceable budgets, credentials/scoped telemetry access and billable infrastructure authorization. Removing shared CodeOwner or Environment reviewers also affects ordinary changes: do not remove them until Issue #245 implements and independently verifies their enforceable replacement. Main must require the exact `PawLocal change authorization` status from the verified publisher App integration ID, plus actual required candidate CI. Trusted code admits only an authenticated, immutable incident candidate; every other PR requires owner approval in a dedicated protected Environment. Every shared infrastructure or production entrypoint must independently verify incident lineage and release-only authority before any AWS credentials, or require the ordinary protected human approval. An actor, branch/title/label or `incident=true` input is never sufficient. Preserve PR/squash/thread resolution, main-only trust, force-push/deletion protections and no bypass actors. Bootstrap, destroy and unrelated setup retain their existing gates. #245 is an activation blocker; these docs change no live setting.

Models hold no publication, merge, production query or deployment credentials. Trusted broker/publication/merge/promoter jobs validate candidate SHA/tree/patch, current incident, real CI and immutable development release evidence. Only allowlisted application paths may change; workflow/IAM/auth/security/secrets/infrastructure/data repair is excluded. Existing Terraform state ownership and release-only plan guards remain mandatory; no blind in-flight apply cancellation or infrastructure rollback.

One admission-to-PR deadline is 20 minutes across all model/test/review/publication jobs. A separate proposed 60-minute deadline spans CI/merge/dev/prod/recovery without increasing model quota. Exhaustion, failed checks, unsupported repairs or uncertain release outcomes stop new mutations and record escalation; no approval-wait state or new coding attempt is added. See DEC-012 and the incident-responder specification. This amendment authorizes the documented runtime design; it does not itself activate live settings or provision infrastructure.

## 10. Cost management

Issue #191's owner-approved account-bootstrap exception permits the separately operated, documented `ops/iam-bootstrap/` setup tool to manage only the single `pawlocal-terraform-bootstrap-actions` user, its dedicated permission policies/boundary, access-key lifecycle and matching protected GitHub setup. The lifecycle owner is `alanlima`. Independently review its scoped permissions before attachment; never use root credentials or steady-state AdministratorAccess. This external identity is not managed by the IAM Terraform workflow or adopted into application/bootstrap state. Record rotation, audit, revocation and retirement procedures in `docs/iam-bootstrap-actions.md`.

The Issue #191 bootstrap workflow may plan the existing standalone IAM state on trusted `main`. A complete no-op needs no approval; every applicable changed plan requires `alanlima` approval in main-only `iam-bootstrap-apply`, with administrator bypass disabled, before applying that exact saved plan. Failed, stale, cancelled, superseded or partially applied plans require a fresh plan and approval. This exception does not authorize application infrastructure changes, state editing or an agent approving its own apply.

Temporary MVP logging decision (owner `alanlima`, 2026-10-23): **all GitHub Actions jobs** must retain normal raw operational stdout/stderr so failures can be diagnosed. This applies across workflows and their existing helpers, including Terraform, build, test and deployment operations. Do not add custom redaction scripts or suppress useful command errors; use GitHub's existing secret masking. The owner explicitly accepts the temporary operational-log exposure risk and defers comprehensive workflow review, log purging and environment recreation to later work. Programmatic data such as state/plan JSON remains internal to validation and private transfers; credential setup must not deliberately print credentials. This logging exception leaves owner approval gates and infrastructure/state ownership rules in force.

Terraform configuration and the approved Terraform states are the only mechanism for creating, changing, replacing, or deleting AWS infrastructure. Under Issue #135, those ownership boundaries are the standalone IAM bootstrap state and separate development and production application states. AWS console, CLI, SDK, shell, and bootstrap scripts must not mutate infrastructure or Terraform state. CI may publish immutable application artifacts; any AWS-side application deployment must be owned by a Terraform resource in the matching environment state. Runtime secrets must not be stored in Terraform state.

Do not manually edit, move, or remove state bindings. Issue #135 permits only a reviewed Terraform import of the exact existing GitHub deployment IAM identity and related resources that read-only inspection confirms belong in the new bootstrap state. The import must be represented by reviewed Terraform configuration, appear in the saved plan, and show no duplicate ownership or unintended replacement/deletion. Do not import application resources or use imports for any other issue without a new approved decision.

Read-only inventory is a blocking gate for Issue #135. If it finds surviving application resources or legacy state bindings, stop the affected greenfield environment and record the exact resources, ownership, cost exposure, and name collisions. Cleanup requires an explicitly owner-approved, independently reviewed, Terraform-only cleanup plan in a separately scoped change. Do not import survivors into the new bootstrap, development, or production states. If cleanup would require adopting an orphaned application resource into a temporary cleanup state, amend Issue #135 and the decision record before planning it. Do not proceed with the affected environment until cleanup verification shows that its new state can start without duplicate ownership or collision.

PawLocal must remain inexpensive to operate at low traffic.

Before deploying AWS infrastructure:
- Compare suitable hosting alternatives.
- Calculate estimated idle and low-traffic monthly costs.
- Include database, networking, logging, monitoring and backup costs.
- Avoid unnecessary always-on resources.
- Review NAT Gateway, load balancer and other fixed costs.
- Establish AWS budget notifications.
- Document infrastructure teardown procedures.

**Never provision or change billable infrastructure without explicit human approval.** The activated #239 controller may automatically apply only its machine-validated application-release plan within existing authorized resources/state; any non-release infrastructure change fails closed. This limited runtime authorization does not permit new infrastructure, IAM, data repair or arbitrary Terraform changes.

For future AI features, enforce usage quotas, model budgets, request limits and a fallback to conventional search.

---

## 11. Documentation and context management

Use the following hierarchy:

1. **`AGENTS.md`** — global project instructions.
2. **`product-spec.md`** — functional requirements and acceptance criteria.
3. **`openapi.yaml`** — API contract.
4. **`docs/architecture.md`** — technical boundaries and design.
5. **`docs/agent-workflow.md`** — coordination, handoffs and approvals.
6. **`docs/model-policy.md`** — model selection, escalation and cost considerations.
7. **`docs/decisions.md`** — approved architectural and product decisions.
8. **GitHub Issues and PRs** — implementation status and evidence.

CAO persistent memory supplements these documents but does not replace them.

If instructions conflict, do not silently select one. Identify the conflict and request a decision.

---

## 12. Definition of Done

A task is complete only when:

- The approved acceptance criteria are satisfied.
- Relevant tests exist and pass.
- Code follows established architecture.
- API contracts and documentation are updated where applicable.
- Security and telemetry impacts have been considered.
- A GitHub Pull Request provides implementation evidence.
- Required review comments are addressed.
- Appropriate approval has been obtained.

---

## 13. Initial instruction to orchestrator

On first launch:

1. Read this `AGENTS.md`.
2. Inspect the repository and existing documentation.
3. Identify missing foundational files.
4. Review the official Zoomcamp final-project requirements.
5. Prepare a concise implementation plan aligned with the established development stages.
6. Create or propose GitHub Issues with acceptance criteria.
7. Confirm agent responsibilities and handoff conventions.
8. Begin with Stage 0 only.

Do not start frontend implementation until the foundational specifications and implementation plan have been reviewed.

Do not introduce future-scope features or billable infrastructure without approval.
