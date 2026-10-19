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

## GitHub descriptions and merge history

Before creating or editing a GitHub issue or pull request, the orchestrator reviews the rendered description for heading/list formatting, concise and non-duplicated text, accurate scope and status, and evidence that supports each claim. Remove unused template prompts so small issues and PRs stay concise. Use the reusable structures and review checklist in [`issue-pr-descriptions.md`](issue-pr-descriptions.md).

Merge every pull request using **Squash and merge**. This keeps each PR's change as one commit on `main`; do not use merge commits or rebase-and-merge. Enforce this under GitHub repository settings by enabling squash merging and disabling merge commits and rebase merging. Do not rewrite existing commit history.

## Gates

- Stage 0 docs and plan require human review before Stage 1.
- Stage 2 and Stage 3 specifications require human approval before either implementation workstream begins. Each workstream also needs an open GitHub issue with scope and acceptance criteria.
- Stage 2 and Stage 3 may run in parallel in separate branches and worktrees. Keep their working directories isolated even though both may edit root Compose configuration.
- Stage 2 dashboards, privacy checks, and synthetic failure demonstrations require review before Stage 2 completes and before Stage 3.1 starts. Stage 3 implementation may continue during this gate.
- Stage 3.1 starts only after Stage 2 is complete and reviewed. It uses its own worktree coordinated with Stage 3, can proceed while Stage 3 continues, and reconciles/verifies the combined Compose stack.
- Stage 3 cannot be marked complete until Stage 2's gate passes and Stage 3.1 integration evidence has been completed and independently reviewed.
- Full frontend/API/database persistence is required before Stage 4.
- Billable cloud resources require explicit human cost approval before provisioning.
- Terraform configuration and the existing shared Terraform state are the only mechanism for AWS infrastructure lifecycle changes. CLI, SDK, console, shell, and bootstrap code may not mutate AWS infrastructure or Terraform state; AWS application deployments must also be represented by a stateful Terraform resource.

