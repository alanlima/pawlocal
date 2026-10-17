# Stage 3 — Backend API and persistence

**Status:** Proposed for human approval before implementation starts. Open a GitHub issue with scope and acceptance criteria before assigning the Backend Engineer.

## Workstream relationship

Stage 3 is owned by the Backend Engineer and may run in parallel with Stage 2 after both specifications are approved and the Stage 3 issue is open. Use a dedicated branch and Git worktree, separate from Stage 2; do not share a working directory. Stage 2 and Stage 3 may both change root `docker-compose.yml`. Keep those changes isolated for later integration.

Stage 2's monitoring review gate must pass before Stage 3 is considered complete. Stage 3 implementation does not need to wait for Stage 2 completion. Stage 3.1 begins only after Stage 2 is complete and reviewed, and may proceed while Stage 3 continues. Stage 3.1 gets its own branch/worktree coordinated with the Stage 3 branch and owns end-to-end tracing/logging plus reconciliation and verification of the combined Compose stack. Stage 3 must preserve the frontend service boundary and provide the API/database behavior Stage 3.1 instruments.

## Goal and scope

Replace the Stage 1 mock adapter with an HTTP adapter backed by FastAPI and PostgreSQL while preserving the existing frontend `PlaceService` contract and React flows. Implement public place discovery/details and authenticated favourites, contributions, and reports. Complete a working frontend → API → PostgreSQL journey with reproducible migrations and tests.

AI-assisted listing generation, source ingestion, and draft approval are excluded. These are not approved MVP workflows, and the current OpenAPI contract has no AI-draft operations.

## Architecture and repository boundaries

Keep backend code under `backend/` with explicit modules for HTTP/API, application use cases, domain rules, and infrastructure/persistence. FastAPI routes handle HTTP parsing, auth context, and response mapping only. Use cases coordinate behavior; domain rules do not import FastAPI or SQLAlchemy. SQLAlchemy 2 repositories and database models belong in infrastructure; Alembic migrations are versioned and reproducible. Inject repository and identity dependencies at the application boundary.

Use PostgreSQL for runtime persistence. Keep the backend runnable locally through root `docker-compose.yml`. Keep configuration in environment variables and document safe local `.env` setup; never commit credentials. No AWS provisioning or production deployment is part of Stage 3.

## API and frontend integration

Implement the approved OpenAPI operations: `GET /places` with q, area, category, repeated facilities, and pagination; `GET /places/{place_id}`; `GET/PUT/DELETE /me/favourites`; `POST /contributions`; and `POST /reports`. Preserve response/error semantics and snake_case wire fields expected by `frontend/src/services/HttpPlaceService.ts`. Preserve the existing `PlaceService` boundary: UI components must not construct requests. Replace the mock adapter with the HTTP adapter through the service factory only when the backend is ready.

**Contract gap requiring human decision before implementation:** the frontend `PlaceService` includes `listReportableContributions()`, but `openapi.yaml` has no read operation for contributions. Approve and add a paginated public read operation for reportable, published contributions with only public fields, or explicitly revise the frontend report flow and service contract. Update OpenAPI, the HTTP adapter, and contract tests together. Do not silently ship a placeholder that leaves the report flow incomplete.

## Data, behavior, and security

Persist places, contributions, favourites, and reports with stable IDs, created/updated timestamps where appropriate, foreign keys, and indexes for discovery filters and lookup paths. A place's unverified access/facility facts remain unknown (nullable/explicitly unknown); never infer or fabricate them. Load only approved/verified listing data or clearly synthetic fixtures confined to development/tests.

Enforce a unique favourite per user/place and prevent duplicate ratings/reviews by the same user for the same place. Validate contribution kinds and field lengths against approved schemas. Accept reports for places or contributions, return contract-defined accepted status, and keep reporter identity private from public responses. Apply authorization, input validation, and rate limiting server-side; report submissions must not reveal whether a private moderation record contains reporter details.

**Authentication is a precondition:** select and record the identity provider and token issuer/audience requirements before implementing protected endpoints. Validate signature, issuer, audience, and expiry; derive user identity from verified subject claim. The frontend demo-member toggle is not authentication. Do not create a production auth substitute or trust client-supplied user IDs. Record the selected provider and contract impact in a decision and update relevant OpenAPI security details before implementation.

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
- [ ] Stage 2 review gate is satisfied before Stage 3 is marked complete; Stage 3.1 owns cross-layer tracing/logging and combined Compose verification.

## Out of scope and gate

No production hosting, paid infrastructure, AI draft generation, source-ingestion workflow, or moderation dashboard. Stop after the persistence walkthrough and independent review. Stage 4 requires its own cost and deployment approval. Do not claim correlated browser/API/database traces until Stage 3.1 is complete.
