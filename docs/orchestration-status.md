# PawLocal workstream status

> Temporary orchestration log for Stage 2, Stage 3, and Stage 3.1. Keep this page current until all three workstreams pass their acceptance and review gates; then archive or remove it.

**Updated:** 2026-10-18  
**Canonical baseline:** `main` at `68c0dac` (merged PR #15)  
**Status:** Active; no workstream is complete.

## Current workstreams

| Workstream | GitHub tracking | Worktree / branch | Current state | Next action |
|---|---|---|---|---|
| Stage 2 — local frontend and observability | Issue [#11](https://github.com/alanlima/pawlocal/issues/11), draft PR [#16](https://github.com/alanlima/pawlocal/pull/16) | `D:\source\pawlocal-stage2`, `11-stage-2-observability` at `fa85132` | Static code checks pass; reviewer resolved the healthcheck finding. Codex review raised two P1 and one P2 findings at this head. Docker is responding again, but runtime acceptance is not yet verified. Host ports 5173 and 3000 are occupied; the agent is adding configurable port mappings and will verify with temporary overrides. | Fix all Codex findings, then run and record the full Compose/browser/telemetry/privacy/shutdown acceptance flow. Keep PR draft until reviewed and verified. |
| Stage 3 — backend and persistence | Issue [#12](https://github.com/alanlima/pawlocal/issues/12); implementation PR not opened | `D:\source\pawlocal-stage3`, `12-stage-3-backend` based on `68c0dac`; implementation files currently uncommitted | Layered FastAPI, SQLAlchemy models/migrations, auth, public reportable listing, tests, and HTTP adapter work are present in the worktree. Agent reports 20 tests pass and one PostgreSQL integration test is skipped without a database. It is attempting container-to-container migration/integration verification. | Complete OpenAPI conformance audit, PostgreSQL migration/repository/security/E2E verification, README evidence, and open a PR. Resolve all review findings. |
| Stage 3.1 — tracing, logs, Compose integration | Issue [#13](https://github.com/alanlima/pawlocal/issues/13); PR not opened | No implementation worktree yet | Gated on Stage 2 being complete and reviewed. Must integrate the Stage 2 frontend/observability Compose services with Stage 3 API/database services without overwriting either branch's changes. | Start only after the Stage 2 gate passes; coordinate its worktree with the Stage 3 branch and produce a separate PR. |

## Approved contract and integration decisions

- PR #15 merged at `68c0dac`; it aligned the canonical docs with parallel Stage 2/3 work, DEC-002 Cognito access-token validation, the public paginated `GET /contributions/reportable` endpoint, and DEC-003 discovery taxonomy.
- Stage 2 and Stage 3 remain separate branches/worktrees. Stage 3 may proceed while Stage 2 runs. Stage 3.1 waits for completed, reviewed Stage 2 and may then proceed while Stage 3 continues.
- `openapi.yaml` is the contract authority. Categories are `dog_park`, `beach`, `walk`, `hiking_area`, and `cafe`; facilities are `Fenced`, `Off-leash area`, `Drinking water`, `Shade`, `Picnic tables`, and `Accessible paths`. Areas are extensible curated human-readable labels with exact-match filtering, not geospatial boundaries. Do not infer unverified facts.
- The approved reportable-contribution response includes only `id`, `kind`, `body`, `place_id`, `rating`, and `created_at`; never expose contributor/reporter identity. The Stage 3 HTTP adapter is being updated to page through this endpoint.
- Stage 2 and Stage 3 can both affect root `docker-compose.yml`. Keep their implementation isolated; Stage 3.1 must explicitly reconcile the two Compose configurations, preserve all six app/telemetry/backend/database services, then verify the combined stack. Do not copy one branch's Compose file over the other.
- Stage 3 cannot be marked complete until Stage 2 review and Stage 3.1 integration plus its independent review are complete.

## Findings and decisions log

| Date | Finding / decision | Action / outcome | Status |
|---|---|---|---|
| 2026-10-18 | PR #14 review found stale sequential-stage wording in canonical docs. | Docs agent aligned architecture, plan, decisions, workflow, specs, and API; PR #15 passed independent review and Codex review, then merged as `68c0dac`. | Done |
| 2026-10-18 | PR #15 exposed missing approval of area/category/facility filter semantics and a malformed flow-style OpenAPI description. | Added DEC-003 and matching product/spec/OpenAPI taxonomy; quoted the OpenAPI description; YAML parsing and full-contract checks passed; independent and Codex review satisfactory. | Done |
| 2026-10-18 | PR #15 Codex found the new public reportable-contribution endpoint was not implemented by the HTTP adapter. | Assigned to Stage 3; adapter maps paginated public fields with tests; full Stage 3 verification remains outstanding. | In progress |
| 2026-10-18 | Stage 2 reviewer found healthchecks did not probe live readiness. | Replaced collector/Tempo checks with HTTP probes in commit `fa85132`; independent re-review found the finding fixed. | Done |
| 2026-10-18 | Codex review of Stage 2 head `fa85132` found duplicate Prometheus namespace, aborted-search false failures, and frontend Docker build-context contamination risk. | Stage 2 agent assigned to fix all three, then repeat checks. | In progress |
| 2026-10-18 | Docker had previously been unavailable, blocking live acceptance checks. | Current Docker Desktop engine responds and `pawlocal-stage3-postgres` is running. Stage 2 found host ports 5173 (local node process) and 3000 (other project Grafana) occupied; keep defaults configurable and use free temporary overrides without stopping unrelated containers. Retry Stage 2 Compose and Stage 3 DB checks using isolated project/service names. | In progress |

## Verification evidence and remaining gates

### Stage 2 evidence already reported

- `npm run check`, 21 Vitest tests, production build, 5 Playwright tests, `npm audit --omit=dev`, Compose config parsing, YAML/JSON parsing, and `git diff --check` passed on the reported revisions.
- Frontend browser tests ran against the dev server. They do not yet verify collector-backed trace export or Grafana/Tempo dashboards.
- The reviewer found no remaining code-review issues for the healthcheck fix, but Codex findings at `fa85132` must be fixed and re-reviewed.
- Still required: successful image builds and Compose startup, live healthy service responses, search-to-detail trace visible in Tempo, metrics/logs/dashboard verification including synthetic failure, telemetry-disabled mode, privacy inspection, and clean shutdown.

### Stage 3 evidence already reported

- Agent reports 20 unit/API/auth tests passed; a PostgreSQL integration test is currently skipped when no test database is provided.
- Stage 3 worktree includes API routes/schemas, Cognito token validation, persistence models and Alembic migrations, HTTP reportable-contribution pagination, and adapter tests.
- Still required: run Alembic and PostgreSQL repository/constraints tests against a live PostgreSQL database, endpoint/OpenAPI conformance and auth/error matrix, persistence across restart, and end-to-end browser flows. Record exact commands/results in the PR.

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
