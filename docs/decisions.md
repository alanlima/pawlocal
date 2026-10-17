# Decision log

Record accepted decisions with date, status, context, decision and consequences. Drafts are not approvals.

## DRAFT-001 — Stage delivery sequence

- **Status:** Proposed by `AGENTS.md`; implementation must follow it.
- **Decision:** Foundations → frontend with mock API → observability → backend/persistence → production readiness → submission.
- **Consequence:** Stage gates are explicit; do not begin later implementation before review approval.

## DRAFT-002 — No hosting selection yet

- **Status:** Open.
- **Context:** Cloud resources and cost approval are not finalized.
- **Decision needed:** Compare appropriate hosting choices and low-traffic costs during Stage 4 planning.
- **Consequence:** Do not provision billable resources or imply a chosen production host.

## Open product decisions

See “Decisions still needed before implementation” in `product-spec.md`. Replace draft entries with approved records as the team resolves them.

