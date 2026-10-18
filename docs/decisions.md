# Decision log

Record accepted decisions with date, status, context, decision and consequences. Drafts are not approvals.

## DEC-001 — Stage delivery sequence and parallel workstreams

- **Status:** Approved 2026-10-18.
- **Context:** The human approved the updated Stage 2 and Stage 3 specifications in PR #14. The Codex review identified conflicts with the architecture, implementation plan, and this decision record; this entry makes the approved sequencing consistent across those canonical documents. See [PR #14 review comment](https://github.com/alanlima/pawlocal/pull/14#discussion_r4304401902).
- **Decision:** Complete Foundations and Stage 1 in order. After human approval of both workstream specifications and with both issues open, Stage 2 local frontend/observability and Stage 3 backend/persistence may proceed in parallel in separate branches and Git worktrees. Stage 2 review is required before Stage 3.1 starts. After that review, Stage 3.1 may proceed in its own coordinated worktree while Stage 3 continues. Stage 3 cannot be marked complete until the Stage 2 review gate passes and Stage 3.1 cross-layer instrumentation, combined Compose integration, and review evidence are complete.
- **Consequence:** Stage 2 and Stage 3 can be implemented concurrently without sharing working directories. Stage 3.1 integrates their Compose changes and verifies the combined stack. No stage gate or required review is waived; Stage 3 completion remains dependent on Stage 3.1 evidence.

## DEC-002 — Stage 3 identity token validation and reportable contributions

- **Status:** Approved 2026-10-18.
- **Context:** Stage 3 requires a simple identity validation approach for protected API operations, and the existing frontend report dialog needs a public list of contributions it can target.
- **Decision:** Use Amazon Cognito User Pool as the OIDC identity provider. The API accepts user-pool **access tokens** only, validates the configured exact issuer (`iss`), signature using the pool's published JWKS signing key, `token_use=access`, expiry, and `client_id` against the configured app-client ID. Keep issuer, app-client ID, and any API resource audience externalized in configuration. Cognito access tokens include `aud` only when resource binding is requested: when resource binding is enabled, require and validate the configured API audience; otherwise validate `aud` if present against the configured resource audience. Do not treat an ID token or client-supplied user ID as API authorization. Add an unauthenticated paginated `GET /contributions/reportable` that returns only already-published public fields needed by the report dialog (`id`, `kind`, `body`, `place_id`, `rating`, `created_at`); do not return reporter or contributor identity. No Cognito pool, AWS resource, or production deployment is provisioned as part of this decision.
- **Consequences:** Protected operations use verified token subject as the user identity. Environment configuration and tests must cover issuer, signing key, token purpose, expiry, app client, and optional/resource-bound audience checks. The public listing exposes only published contribution content already intended for public display. See the [Cognito access token claims](https://docs.aws.amazon.com/cognito/latest/developerguide/amazon-cognito-user-pools-using-the-access-token.html), [JWT verification guidance](https://docs.aws.amazon.com/cognito/latest/developerguide/amazon-cognito-user-pools-using-tokens-verifying-a-jwt.html), and [resource binding documentation](https://docs.aws.amazon.com/cognito/latest/developerguide/cognito-user-pools-define-resource-servers.html).

## DEC-003 — MVP discovery taxonomy

- **Status:** Approved 2026-10-18.
- **Context:** Stage 3 requires stable area, category and facility filters; the existing Stage 1 frontend already defines the MVP values.
- **Decision:** Use place categories `dog_park`, `beach`, `walk`, `hiking_area`, and `cafe`; facilities `Fenced`, `Off-leash area`, `Drinking water`, `Shade`, `Picnic tables`, and `Accessible paths`; and curated, human-readable South East Queensland area labels. Current UI examples are `Brisbane City`, `Brisbane North`, `Gold Coast`, `Moreton Bay`, and `Sunshine Coast`, but the list is not exhaustive. Filter areas by exact label; they are not precise geospatial boundaries. Unknown or unverified access/facility facts remain absent/unknown and must never be inferred.
- **Consequences:** Stage 3 API, persistence and adapters must use the category/facility enums and exact-match area-label semantics. The broader freshness and verification policy remains open. See the approved [product taxonomy](../product-spec.md#approved-mvp-discovery-taxonomy) and `openapi.yaml`.

## DRAFT-002 — No full-application hosting selection yet

- **Status:** Open.
- **Context:** The static frontend hosting choice is recorded in DEC-004; the backend and hosted observability destination and full-system cost estimate remain undecided. A dated comparison is available in the [Stage 4 hosting proposal](stage4-hosting-options.md) and [Issue #41](https://github.com/alanlima/pawlocal/issues/41).
- **Decision needed:** Select a hosting option after reviewing production database availability, recovery objectives, telemetry/data-residency limits, and the monthly cost envelope in the proposal.
- **Consequence:** Do not imply that the API/database/observability production host has been chosen or provision billable resources. Issue #43 remains gated on an approved choice and explicit cost approval.

## DEC-004 — Static frontend AWS delivery

- **Status:** Approved 2026-10-18 for the initial Stage 4 frontend release.
- **Context:** PawLocal can publish a mock-backed React/Vite bundle without deploying the API or database. The public repository must remain reusable and contain no owner-specific DNS name, hosted-zone ID, AWS account ID, or credentials.
- **Decision:** Serve the static frontend from a private S3 bucket through CloudFront with OAC, HTTPS via an existing ACM wildcard certificate supplied as an input, SPA route fallback, and Route 53 alias records for the parameterized `pawlocal.<domain>` hostname. The build sets `VITE_USE_MOCK_BACKEND=true`. Store Terraform state in the pre-existing, versioned and encrypted state bucket under key `pawlocal/terraform.tfstate`; inject the bucket name through local backend configuration. GitHub Actions deploys on `main` pushes that change `frontend/**` and authenticates with a branch-restricted OIDC role.
- **Consequences:** Review CloudFront/data-transfer and S3 costs before apply. This decision covers only the static frontend; it does not select hosting for the backend, database, or observability. See [the deployment runbook](deployment-aws-frontend.md).

## Open product decisions

See “Decisions still needed before implementation” in `product-spec.md`. Replace draft entries with approved records as the team resolves them.

