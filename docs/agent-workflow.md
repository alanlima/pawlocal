# Agent workflow and handoffs

## Responsibilities

- **Orchestrator:** Plans stages, confirms issue/branch linkage, coordinates handoffs, integrates changes and enforces approval gates. It does not expand scope or silently bypass review.
- **Frontend engineer:** Owns React/TypeScript UI, typed service contracts, mock/HTTP adapters, client behavior and frontend tests.
- **Backend engineer:** Owns FastAPI, OpenAPI alignment, use cases, domain rules, SQLAlchemy/Alembic, auth and backend tests.
- **Platform engineer:** Owns Compose, telemetry, CI/CD, hosting evaluation and Terraform. No paid provisioning without explicit human approval.
- **Reviewer:** Independently checks requirements, architecture, tests, security, telemetry and acceptance evidence. Review does not authorize merge.

## Handoff protocol

1. Read `AGENTS.md`, `product-spec.md`, `openapi.yaml`, the architecture decision log and the relevant agent profile.
2. Link work to an issue with context and acceptance criteria; branch from the repository's agreed base.
3. State scope, touched boundaries, assumptions, checks and evidence in the handoff/PR.
4. Review contract and documentation impacts alongside code. Keep changes within the approved stage.
5. Report checks actually run; do not claim unrun checks. Do not merge without required approval.

## Gates

- Stage 0 docs and plan require human review before Stage 1.
- Stage 1 requires human approval before observability work.
- Stage 2 dashboards and failure demonstrations require review before Stage 3.
- Full frontend/API/database persistence is required before Stage 4.
- Billable cloud resources require explicit human cost approval before provisioning.

