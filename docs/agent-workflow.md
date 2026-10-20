# Agent workflow and handoffs

## Responsibilities

- **Orchestrator:** Owns scope, issue readiness, assignments, coordination, integration checks, and project gates. It delegates implementation to the specialist who owns the changed boundary and does not silently bypass review or expand scope.
- **Frontend engineer:** Owns React/TypeScript UI, typed service contracts, mock/HTTP adapters, client behavior, and frontend tests.
- **Backend engineer:** Owns FastAPI, OpenAPI alignment, use cases, domain rules, SQLAlchemy/Alembic, auth, and backend tests.
- **Platform engineer:** Owns Compose, telemetry, CI/CD, hosting evaluation, and Terraform. No paid provisioning without explicit human approval.
- **Reviewer:** Independently checks requirements, architecture, tests, security, telemetry, and acceptance evidence. Review does not authorize merge.

Agent profiles in `agents/profiles/` define each role's focus. They do not grant permissions beyond the current task, repository, and explicit user authorization.

## Orchestrator lifecycle

1. **Frame:** Convert the request into a user outcome, target environment, scope, exclusions, observable acceptance criteria, and approval boundaries. Use project documents to resolve ordinary implementation choices; raise material scope, cost, risk, or product decisions to the owner.
2. **Inspect:** Read `AGENTS.md`, the relevant specifications and decisions, agent profiles, linked issues/PRs, current branch and worktree state, and available runtime evidence. Reuse an existing issue when it covers an implementation request. Create a new issue and issue-linked branch for implementation work, or when the user explicitly asks for those artifacts. Review, status, advisory, and local-only requests do not create GitHub artifacts just to formalize the work; record findings in the requested existing location when appropriate.
3. **Prepare:** For implementation work, check the rendered issue description against [`issue-pr-descriptions.md`](issue-pr-descriptions.md), apply a project-stage and work-type label, and confirm dependencies and gates. Assign the issue-linked branch/worktree to one accountable specialist owner. The implementation owner opens the PR. The orchestrator reviews its rendered description and may edit the description or add/update issue and PR comments to coordinate and record decisions.
4. **Delegate:** Send the owner the handoff packet below. Split work across agents only when ownership boundaries, dependencies, and merge order are clear. The orchestrator remains responsible for cross-agent coordination and the final acceptance decision.
5. **Coordinate:** Maintain a concise user-visible task tracker with an action item, owner, status, notes, and estimated completion percentage for each work item. Use clear statuses such as not started, active, blocked, review, and complete. Base percentages on acceptance criteria and evidence; reserve 100% for verified completion. Refresh the tracker when work is assigned, handed off, reaches a material milestone, becomes blocked, or the user requests progress. Request agent updates at meaningful milestones and when an external dependency may change the plan. Agents report promptly when blocked. Record material decisions and evidence in the issue/PR and keep unrelated work moving where possible.
6. **Integrate:** Check the returned change against the issue, inspect the diff and applicable docs/contracts, verify reported checks and runtime evidence, and confirm security/privacy and stage-gate implications. Do not claim a check or live state that was not observed.
7. **Review:** Assign an independent reviewer who did not implement the change. Require findings tied to acceptance criteria and precise locations, or an explicit no-findings report. The implementation owner addresses findings; the orchestrator verifies each resolution and checks new PR comments before completion.
8. **Complete:** Ensure the PR links the issue, the rendered description is accurate, required checks/reviews pass, and acceptance evidence is recorded. Obtain explicit human approval for approval-gated work. Merge only when authorized and required gates pass, using squash merge. Close the issue only after its acceptance criteria are verified.

## Handoff packet and return

Each assignment includes:

- Issue URL, desired outcome, acceptance criteria, status, and dependencies.
- Relevant repository documents, prior decisions, logs or runtime evidence, including uncertainty.
- In-scope systems/files, target environment, and explicit exclusions.
- Required branch/worktree and any file or agent coordination constraints.
- Expected checks/evidence and actions that require owner approval.
- Return format: summary, changed files, decisions, exact commands/check results, PR link, unresolved findings/comments, live status, and blockers.

The specialist reports blockers with the concrete evidence, decision needed, candidate paths, and whether independent tasks can continue. The orchestrator records the decision in the linked issue, assigns follow-up work, or asks the owner when the choice changes scope or crosses an approval boundary.

## Review and issue/PR descriptions

The orchestrator checks the rendered Markdown before creating or editing an issue or PR. Confirm readable headings/lists, concise nonduplicated text, accurate scope and status, and evidence that supports each claim. Remove irrelevant template sections. Follow [`issue-pr-descriptions.md`](issue-pr-descriptions.md). The implementation owner creates the PR; the orchestrator can subsequently edit its description and add or update comments.

For user-facing progress, show the task tracker in concise updates and keep its action, owner, status, notes, and estimated completion percentage current. Explain blockers and decisions plainly so the user can redirect the work.

Reviewers assess independently and do not merge. The orchestrator must monitor issue/PR comments at agent handoffs and before closing the work, and ensure each material finding is answered or explicitly left open with a reason. Tests do not replace required browser, deployment, or human review evidence.

## GitHub and merge history

All implementation follows the GitHub workflow in `AGENTS.md`: issue with acceptance criteria and labels, linked branch, relevant checks, PR, review, evidence, and approved merge. Do not commit implementation directly to `main`. Use **Squash and merge** so each PR adds one commit to `main`; repository settings should allow squash and disable merge commits and rebase merging. Do not rewrite existing history.

## Gates and approvals

- Stage 0 docs and plan require human review before Stage 1.
- Stage 2 and Stage 3 specifications require human approval before either implementation workstream begins. Each workstream also needs an open GitHub issue with scope and acceptance criteria.
- Stage 2 and Stage 3 may run in parallel in separate branches and worktrees. Keep their working directories isolated even though both may edit root Compose configuration.
- Stage 2 dashboards, privacy checks, and synthetic failure demonstrations require review before Stage 2 completes and before Stage 3.1 starts. Stage 3 implementation may continue during this gate.
- Stage 3.1 starts only after Stage 2 is complete and reviewed. It uses its own worktree coordinated with Stage 3, can proceed while Stage 3 continues, and reconciles/verifies the combined Compose stack.
- Stage 3 cannot be marked complete until Stage 2's gate passes and Stage 3.1 integration evidence has been completed and independently reviewed.
- Full frontend/API/database persistence is required before Stage 4.
- Billable cloud resources require explicit human cost approval before provisioning. No issue, plan, successful test, or prior approval for a different change supplies that approval.
- Issue #135 replaces the former shared application-state layout with three clean ownership boundaries: a standalone IAM bootstrap state plus separate development and production application states. Do not migrate or import former application resources into those states.
- Issue #135's first implementation gate is to disable or make fail-closed the legacy automatic development-deploy path before merging any Terraform, deployment-workflow, or deployment-helper change. Verify that the merge cannot invoke the former combined-state deployment, and keep the path disabled until the new environment roots, targets, credentials, and release path are configured and independently reviewed.
- The only existing AWS resources Issue #135 may carry forward are the exact GitHub deployment IAM identity and related trust/baseline controls confirmed by read-only AWS and Terraform ownership inspection. Adopt them only through a reviewed Terraform import into the bootstrap state. The saved plan must show the import, no duplicate ownership, and no unintended replacement or deletion. Ad hoc `terraform import`, state editing, `state mv`, and `state rm` are not approved.
- If read-only inspection finds surviving application resources or legacy state bindings, block the affected greenfield environment. Record their exact identity, ownership, cost exposure, and collision risk, then obtain an owner decision for a separately scoped, independently reviewed, Terraform-only cleanup change. Do not adopt survivors into the new application states. If cleanup requires temporary Terraform adoption of an orphan, amend Issue #135 and DEC-008 before planning it. Resume only after cleanup verification proves the new state has no duplicate ownership or resource-name collision.
- Bootstrap Terraform may be applied locally only with the owner's explicitly authorized higher-permission credentials and only from an independently reviewed saved plan. This exception does not authorize application infrastructure changes. Development and production plans/applies run through their matching protected GitHub Environments and must apply the exact reviewed saved plan.
- Terraform configuration and the approved bootstrap/development/production states are the only mechanism for AWS infrastructure lifecycle changes. CLI, SDK, console, shell, and bootstrap code may not mutate AWS infrastructure or Terraform state; AWS application deployments must also be represented by a Terraform resource in the matching environment state.
- Issue #135 preserves the Issue #75 Lightsail Container Services and Aurora DSQL service architecture, telemetry-disabled release, cost/provisioning gates, and development-before-production promotion policy. It does not authorize a hosting change, telemetry, recovery work, or application provisioning before the required review and approval gates.

## Agent completion record

Before marking assigned work complete, the orchestrator records in GitHub:

- What was changed and how each acceptance criterion was verified.
- Commands/checks actually run and their results; link CI or runtime evidence where available.
- Independent review outcome and disposition of all comments.
- Current deployment/runtime state, separately from code and CI status.
- Remaining blockers, approval needs, and explicit follow-up issue links.
