# Decision log

Record accepted decisions with date, status, context, decision and consequences. Drafts are not approvals.

## DEC-001 — Stage delivery sequence

- **Status:** Approved for Stage 1 on 2026-10-17; later gates remain in force.
- **Decision:** Foundations → frontend with mock API → observability → backend/persistence → production readiness → submission.
- **Context:** Human review approved the current product, API, architecture and delivery plan for Stage 1. Product decisions that do not block the mock-backed frontend remain open for review before the stages where they apply.
- **Consequence:** Stage 1 may proceed. Stop for human approval before Stage 2; all later review and cost gates remain in force.

## DRAFT-002 — No hosting selection yet

- **Status:** Open.
- **Context:** Cloud resources and cost approval are not finalized.
- **Decision needed:** Compare appropriate hosting choices and low-traffic costs during Stage 4 planning.
- **Consequence:** Do not provision billable resources or imply a chosen production host.

## Open product decisions

See “Decisions still needed before implementation” in `product-spec.md`. Replace draft entries with approved records as the team resolves them.

