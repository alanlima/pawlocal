# Stage 3 — Backend API and persistence

**Status:** Approved for implementation on 2026-10-18. Issue #12 is open with scope and acceptance criteria; Stage 3 may start in parallel with Stage 2 in a separate branch and worktree.

## Workstream relationship

Stage 3 is owned by the Backend Engineer and may run in parallel with Stage 2 after both specifications are approved and the Stage 3 issue is open. Use a dedicated branch and Git worktree, separate from Stage 2; do not share a working directory. Stage 2 and Stage 3 may both change root `docker-compose.yml`. Keep those changes isolated for later integration.

Stage 2's monitoring review gate must pass before Stage 3 is considered complete. Stage 3 implementation does not need to wait for Stage 2 completion. Stage 3.1 begins only after Stage 2 is complete and reviewed, and may proceed while Stage 3 continues. Stage 3.1 gets its own branch/worktree coordinated with the Stage 3 branch and owns end-to-end tracing/logging plus reconciliation and verification of the combined Compose stack. Stage 3 cannot be marked complete until Stage 3.1 integration work and its independent review are complete.

## Goal and scope

Replace the Stage 1 mock adapter with an HTTP adapter backed by FastAPI and PostgreSQL while preserving the existing frontend `PlaceService` contract and React flows. Implement public place discovery/details and authenticated favourites, contributions, and reports. Complete a working frontend → API → PostgreSQL journey with reproducible migrations and tests.

AI-assisted listing generation, source ingestion, and draft approval are excluded. These are not approved MVP workflows, and the current OpenAPI contract has no AI-draft operations.

## Architecture and repository boundaries

Keep backend code under `backend/` with explicit modules for HTTP/API, application use cases, domain rules, and infrastructure/persistence. FastAPI routes handle HTTP parsing, auth context, and response mapping only. Use cases coordinate behavior; domain rules do not import FastAPI or SQLAlchemy. SQLAlchemy 2 repositories and database models belong in infrastructure; Alembic migrations are versioned and reproducible. Inject repository and identity dependencies at the application boundary.

Use PostgreSQL for runtime persistence. Keep the backend runnable locally through root `docker-compose.yml`. Keep configuration in environment variables and document safe local `.env` setup; never commit credentials. No AWS provisioning or production deployment is part of Stage 3.

## API and frontend integration

Use the approved MVP discovery taxonomy in `product-spec.md` (DEC-003): categories are `dog_park`, `beach`, `walk`, `hiking_area`, and `cafe`; facilities are `Fenced`, `Off-leash area`, `Drinking water`, `Shade`, `Picnic tables`, and `Accessible paths`; area filters match curated human-readable labels exactly. Current UI area examples are `Brisbane City`, `Brisbane North`, `Gold Coast`, `Moreton Bay`, and `Sunshine Coast`; the list is not exhaustive, and area labels do not define geospatial boundaries. Keep unverified access/facility facts unknown; the broader freshness and verification policy remains open.

Implement the approved OpenAPI operations: `GET /places` with q, area, category, repeated facilities, and pagination; `GET /places/{place_id}`; `GET/PUT/DELETE /me/favourites`; `POST /contributions`; and `POST /reports`. Preserve response/error semantics and snake_case wire fields expected by `frontend/src/services/HttpPlaceService.ts`. Preserve the existing `PlaceService` boundary: UI components must not construct requests. Select the adapter through the explicit `VITE_USE_MOCK_BACKEND` feature flag: only the literal value `true` selects the mock adapter; false or unset selects the real HTTP adapter. HTTP failures must not silently fall back to mock data.

The human-approved contract adds unauthenticated, paginated `GET /contributions/reportable` for already-published contributions. Return only the public fields needed by the report dialog (`id`, `kind`, `body`, `place_id`, `rating`, `created_at`); never return reporter or contributor identity. Implement the HTTP adapter and contract tests against `openapi.yaml`.

## Data, behavior, and security

Persist places, contributions, favourites, and reports with stable IDs, created/updated timestamps where appropriate, foreign keys, and indexes for discovery filters and lookup paths. A place's unverified access/facility facts remain unknown (nullable/explicitly unknown); never infer or fabricate them. Load only approved/verified listing data or clearly synthetic fixtures confined to development/tests.

Enforce a unique favourite per user/place and prevent duplicate ratings/reviews by the same user for the same place. Validate contribution kinds and field lengths against approved schemas. Accept reports for places or contributions, return contract-defined accepted status, and keep reporter identity private from public responses. Apply authorization, input validation, and rate limiting server-side; report submissions must not reveal whether a private moderation record contains reporter details.

Use Amazon Cognito User Pool as the OIDC identity provider for protected API operations. Accept user-pool access tokens only; validate the configured exact issuer, signature against the pool JWKS key, `token_use=access`, expiry, and `client_id` against the configured app-client ID. Externalize issuer and app-client configuration. Cognito access-token `aud` is present only with resource binding: require and validate the configured API audience when resource binding is enabled, and validate it against configuration if present otherwise. Derive identity from the verified subject claim. The frontend demo-member toggle is not authentication. Do not trust client-supplied user IDs or provision Cognito/AWS resources in this stage. See DEC-002 and the OpenAPI security description.

Community contributions follow the approved immediate-publication policy after validation, with reports supporting moderation. Do not add moderator UI or unapproved moderation roles/endpoints in this stage.

## Verification and acceptance criteria

- [ ] Every implemented endpoint matches the approved OpenAPI schema, auth requirement, status code, and error response; contract changes are reviewed and documented first.
- [ ] Public search supports area, category, facility filters, pagination, and detail lookup; empty and unknown records are handled without invented facts.
- [ ] Authenticated users can add/remove favourites and submit reviews, suggestions, tips/corrections, and reports; anonymous write attempts fail with 401.
- [ ] Database constraints prevent duplicate user/place favourites and duplicate reviews; validation, authorization, and rate-limit behavior have tests.
- [ ] Alembic upgrades a fresh database and records survive service/database restart.
- [ ] Approved reportable-contribution listing behavior works end to end, including real HTTP adapter integration.
- [ ] Unit tests cover domain/use cases; API tests cover schemas/auth/errors; PostgreSQL integration tests cover repositories, constraints, and migrations.
- [ ] End-to-end tests demonstrate browser discovery → detail/share and authenticated contribution/report/favourite journeys against API and database.
- [ ] README/setup docs describe local startup, migration, test, reset, and teardown commands. The PR links this issue and reports verification evidence and checks actually run.
- [ ] Stage 2 review gate has passed, and Stage 3.1 cross-layer tracing/logging plus combined Compose integration have been completed and reviewed before Stage 3 is marked complete.

## Out of scope and gate

No production hosting, paid infrastructure, AI draft generation, source-ingestion workflow, or moderation dashboard. Stop after the persistence walkthrough and independent review. Stage 4 requires its own cost and deployment approval. Do not claim correlated browser/API/database traces until Stage 3.1 is complete.
