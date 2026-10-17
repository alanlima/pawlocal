# PawLocal workstream status

> Temporary orchestration log for Stage 2, Stage 3, and Stage 3.1. Keep this page current until all three workstreams pass their acceptance and review gates; then archive or remove it.

**Updated:** 2026-10-18  
**Canonical baseline:** `main` at `68c0dac` (merged PR #15)  
**Status:** Active; no workstream is complete.

## Current workstreams

| Workstream | GitHub tracking | Worktree / branch | Current state | Next action |
|---|---|---|---|---|
| Stage 2 — local frontend and observability | Issue [#11](https://github.com/alanlima/pawlocal/issues/11), draft PR [#16](https://github.com/alanlima/pawlocal/pull/16) | `D:\source\pawlocal-stage2`, `11-stage-2-observability` at `148d4f3` | Codex fixes are pushed: removed duplicate metric namespace, records AbortError as cancellation, added root/frontend `.dockerignore` (including `.env*` exclusion), parameterized frontend/Grafana ports and Collector origin, and corrected URLs. `npm run check`, 21/21 tests, build, fault-string production scan, 5/5 Playwright E2E, Compose config and diff check pass; manual Chrome at Vite 5174 found Nudgee and opened its detail. Codex review of 148d4f3 is running. Image/container runtime still blocked by Buildx `DeadlineExceeded`, stalled `npm ci` and BusyBox pull. | Obtain fresh independent browser/code review; finish runtime traces/metrics/logs/privacy/disabled-toggle/shutdown checks when image pulls work. Keep runtime/dashboard approval criteria open until verified. |
| Stage 3 — backend and persistence | Issue [#12](https://github.com/alanlima/pawlocal/issues/12), draft PR [#18](https://github.com/alanlima/pawlocal/pull/18) | `D:\source\pawlocal-stage3`, `12-stage-3-backend` at `805c331` | The three reviewer findings are fixed and pushed: mandatory JWT expiry, facility vocabulary validation plus PostgreSQL CHECK, and report-target foreign keys with data-preserving migration 0005. Agent reports 25 passed / 1 PostgreSQL test skipped, Ruff and offline Alembic checks pass. Migrations 0001–0005 were applied to a fresh live Postgres database; facility and report-target invalid SQL probes fail as intended. Independent Reviewer and latest Codex report no remaining major/code findings. A temporary container/network workaround is being attempted for repository integration and authenticated browser E2E, which remain outstanding. | Complete repository integration/restart persistence and authenticated browser journeys; record evidence. Root Compose remains deferred to Stage 3.1. |
| Stage 3.1 — tracing, logs, Compose integration | Issue [#13](https://github.com/alanlima/pawlocal/issues/13); PR not opened | No implementation worktree yet | Gated on Stage 2 being complete and reviewed. Must integrate the Stage 2 frontend/observability Compose services with Stage 3 API/database services without overwriting either branch's changes. | Start only after the Stage 2 gate passes; coordinate its worktree with the Stage 3 branch and produce a separate PR. |

## Approved contract and integration decisions

- PR #15 merged at `68c0dac`; it aligned the canonical docs with parallel Stage 2/3 work, DEC-002 Cognito access-token validation, the public paginated `GET /contributions/reportable` endpoint, and DEC-003 discovery taxonomy.
- Stage 2 and Stage 3 remain separate branches/worktrees. Stage 3 may proceed while Stage 2 runs. Stage 3.1 waits for completed, reviewed Stage 2 and may then proceed while Stage 3 continues.
- Stage 2 owns `frontend/src/services/index.ts` and wraps the selected adapter with `observePlaceService`. When Stage 3 switches the factory from mock to HTTP, preserve that telemetry wrapper: `observePlaceService(new HttpPlaceService(...))`. The Stage 2 branch currently adds the wrapper; the Stage 3 branch currently adds HTTP adapter behavior. Coordinate the factory integration so neither set of changes is overwritten.
- `openapi.yaml` is the contract authority. Categories are `dog_park`, `beach`, `walk`, `hiking_area`, and `cafe`; facilities are `Fenced`, `Off-leash area`, `Drinking water`, `Shade`, `Picnic tables`, and `Accessible paths`. Areas are extensible curated human-readable labels with exact-match filtering, not geospatial boundaries. Do not infer unverified facts.
- The approved reportable-contribution response includes only `id`, `kind`, `body`, `place_id`, `rating`, and `created_at`; never expose contributor/reporter identity. The Stage 3 HTTP adapter is being updated to page through this endpoint.
- Stage 2 and Stage 3 can both affect root `docker-compose.yml`. Keep their implementation isolated; Stage 3.1 must explicitly reconcile the two Compose configurations, preserve all six app/telemetry/backend/database services, then verify the combined stack. Do not copy one branch's Compose file over the other.
- Root Compose wiring is a deferred integration criterion: Stage 3 may retain its isolated backend setup in PR #18, while Stage 3.1 owns the combined root Compose change and verification. Keep the Stage 3 issue criterion unchecked until Stage 3.1 passes; do not duplicate or overwrite Stage 2's Compose stack to make the Stage 3 draft appear complete.
- Stage 3 cannot be marked complete until Stage 2 review and Stage 3.1 integration plus its independent review are complete.

## Findings and decisions log

| Date | Finding / decision | Action / outcome | Status |
|---|---|---|---|
| 2026-10-18 | PR #14 review found stale sequential-stage wording in canonical docs. | Docs agent aligned architecture, plan, decisions, workflow, specs, and API; PR #15 passed independent review and Codex review, then merged as `68c0dac`. | Done |
| 2026-10-18 | PR #15 exposed missing approval of area/category/facility filter semantics and a malformed flow-style OpenAPI description. | Added DEC-003 and matching product/spec/OpenAPI taxonomy; quoted the OpenAPI description; YAML parsing and full-contract checks passed; independent and Codex review satisfactory. | Done |
| 2026-10-18 | PR #15 Codex found the new public reportable-contribution endpoint was not implemented by the HTTP adapter. | Assigned to Stage 3; adapter maps paginated public fields with tests; full Stage 3 verification remains outstanding. | In progress |
| 2026-10-18 | Stage 2 reviewer found healthchecks did not probe live readiness. | Replaced collector/Tempo checks with HTTP probes in commit `fa85132`; independent re-review found the finding fixed. | Done |
| 2026-10-18 | Codex review of Stage 2 head `fa85132` found duplicate Prometheus namespace, aborted-search false failures, and frontend Docker build-context contamination risk. | Fixes pushed at `1522d47`; a follow-up `148d4f3` excludes `.env*` from the root image context. Static/browser checks pass. Fresh Codex and independent Reviewer checks requested for latest head. Compose builds still stall on BuildKit/image/npm operations. | Review/runtime in progress |
| 2026-10-18 | Focused Stage 3 contract audit compared backend work to the merged OpenAPI contract. | Added reachable 400/429/503 responses, `/places` area `maxLength: 160`, `additionalProperties: false` for three request schemas, and the shared Error schema for contribution 409. Regression assertions were added; independent reviewer confirms no remaining contract mismatch. Included in draft PR #18. | Contract done; runtime verification/review remain |
| 2026-10-18 | Full Stage 3 PR review checked authentication and persistence invariants. | Backend agent fixed required `exp`, facility vocabulary validation and PostgreSQL constraint, and report target foreign keys through data-preserving migration 0005, pushed as `805c331`. Independent Reviewer confirmed all three fixes; Codex reported no major issues. Root Compose remains deferred to Stage 3.1. | Code review satisfactory; runtime acceptance in progress |
| 2026-10-18 | Docker had previously been unavailable, blocking live acceptance checks. | Current Docker Desktop engine responds and `pawlocal-stage3-postgres` is running. Stage 2 found host ports 5173 (local node process) and 3000 (other project Grafana) occupied; keep defaults configurable and use free temporary overrides without stopping unrelated containers. Retry Stage 2 Compose and Stage 3 DB checks using isolated project/service names. | In progress |

## Verification evidence and remaining gates

### Stage 2 evidence already reported

- `npm run check`, 21 Vitest tests, production build, 5 Playwright tests, `npm audit --omit=dev`, Compose config parsing, YAML/JSON parsing, and `git diff --check` passed on the reported revisions.
- Frontend browser tests ran against the dev server. They do not yet verify collector-backed trace export or Grafana/Tempo dashboards.
- The reviewer found no remaining code-review issues for the healthcheck fix, but Codex findings at `fa85132` must be fixed and re-reviewed.
- The Codex review of `fa85132` completed with three findings (two P1, one P2); fixes are pushed at `1522d47` plus the `.env*` build-context hardening at `148d4f3`. Codex and independent Reviewer are reviewing the latest head and the Reviewer has been asked to check the browser/UI.
- Still required: successful image builds and Compose startup, live healthy service responses, search-to-detail trace visible in Tempo, metrics/logs/dashboard verification including synthetic failure, telemetry-disabled mode, privacy inspection, and clean shutdown.

### Stage 3 evidence already reported

- Agent reports 25 backend tests passed and one PostgreSQL integration test skipped; Ruff and formatting pass. The PostgreSQL integration test is currently skipped without a working test DB connection.
- Stage 3 worktree includes API routes/schemas, Cognito token validation, persistence models and Alembic migrations, HTTP reportable-contribution pagination, and adapter tests.
- Migrations 0001–0005 were applied to a fresh live PostgreSQL database and version plus facility/report constraints verified; direct SQL probes reject unsupported facilities and orphan report targets. Still required: repository tests through the application DB driver, persistence across restart, authenticated browser-to-API flows, endpoint/OpenAPI conformance and auth/error matrix. Independent Reviewer and Codex reviews are satisfactory. Host published-port access is failing; an isolated bridge-network helper approach is being attempted.

### Stage 3.1 evidence required

- Correlated browser → API → database trace in local trace backend.
- Structured privacy-safe logs with useful levels, stable event/error codes, trace/span identifiers, and demonstrated synthetic failures.
- Combined Stage 2 + Stage 3 Compose health, telemetry, persistence, and clean shutdown checks.
- Separate Reviewer report and updated issue #13 acceptance evidence.

## Follow-up protocol

1. Update the relevant issue acceptance checkboxes only after evidence exists, and copy exact commands/results into its PR.
2. Check issues #11–13 for audit-agent comments at every handoff and before closing any issue.
3. Rebase/merge only after required review; keep each stage PR and worktree distinct. The orchestrator resolves cross-stage conflicts, especially Compose integration and contract drift.
4. Do not report this orchestration complete until all criteria for Stages 2, 3, and 3.1 are checked, all reviewers are satisfactory, Codex findings are resolved, and the required human gates are recorded.
