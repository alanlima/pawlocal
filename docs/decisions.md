# Decision log

Record accepted decisions with date, status, context, decision and consequences. Drafts are not approvals.

## DEC-001 — Stage delivery sequence and parallel workstreams

- **Status:** Approved 2026-10-18.
- **Context:** The human approved the updated Stage 2 and Stage 3 specifications in PR #14. The Codex review identified conflicts with the architecture, implementation plan, and this decision record; this entry makes the approved sequencing consistent across those canonical documents. See [PR #14 review comment](https://github.com/alanlima/pawlocal/pull/14#discussion_r4304401902).
- **Decision:** Complete Foundations and Stage 1 in order. After human approval of both workstream specifications and with both issues open, Stage 2 local frontend/observability and Stage 3 backend/persistence may proceed in parallel in separate branches and Git worktrees. Stage 2 review remains a prerequisite to Stage 3 completion and Stage 3.1 start. After Stage 2 review, Stage 3.1 may proceed in its own coordinated worktree while Stage 3 continues.
- **Consequence:** Stage 2 and Stage 3 can be implemented concurrently without sharing working directories. Stage 3.1 integrates their Compose changes and verifies the combined stack. No stage gate or required review is waived.

## DEC-002 — Stage 3 identity token validation and reportable contributions

- **Status:** Approved 2026-10-18.
- **Context:** Stage 3 requires a simple identity validation approach for protected API operations, and the existing frontend report dialog needs a public list of contributions it can target.
- **Decision:** Use Amazon Cognito User Pool as the OIDC identity provider. The API accepts user-pool **access tokens** only, validates the configured exact issuer (`iss`), signature using the pool's published JWKS signing key, `token_use=access`, expiry, and `client_id` against the configured app-client ID. Keep issuer, app-client ID, and any API resource audience externalized in configuration. Cognito access tokens include `aud` only when resource binding is requested: when resource binding is enabled, require and validate the configured API audience; otherwise validate `aud` if present against the configured resource audience. Do not treat an ID token or client-supplied user ID as API authorization. Add an unauthenticated paginated `GET /contributions/reportable` that returns only already-published public fields needed by the report dialog (`id`, `kind`, `body`, `place_id`, `rating`, `created_at`); do not return reporter or contributor identity. No Cognito pool, AWS resource, or production deployment is provisioned as part of this decision.
- **Consequences:** Protected operations use verified token subject as the user identity. Environment configuration and tests must cover issuer, signing key, token purpose, expiry, app client, and optional/resource-bound audience checks. The public listing exposes only published contribution content already intended for public display. See the [Cognito access token claims](https://docs.aws.amazon.com/cognito/latest/developerguide/amazon-cognito-user-pools-using-the-access-token.html), [JWT verification guidance](https://docs.aws.amazon.com/cognito/latest/developerguide/amazon-cognito-user-pools-using-tokens-verifying-a-jwt.html), and [resource binding documentation](https://docs.aws.amazon.com/cognito/latest/developerguide/cognito-user-pools-define-resource-servers.html).

## DRAFT-002 — No hosting selection yet

- **Status:** Open.
- **Context:** Cloud resources and cost approval are not finalized.
- **Decision needed:** Compare appropriate hosting choices and low-traffic costs during Stage 4 planning.
- **Consequence:** Do not provision billable resources or imply a chosen production host.

## Open product decisions

See “Decisions still needed before implementation” in `product-spec.md`. Replace draft entries with approved records as the team resolves them.

