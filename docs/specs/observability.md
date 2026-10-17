# Stage 2 and Stage 3.1 — Local observability

**Status:** Approved for implementation on 2026-10-18. Stage 2 must pass its review gate before Stage 3.1 starts and before Stage 3 is complete.

## Workstream relationship

Stage 2 is an independent local frontend and observability workstream owned by the Platform Engineer. Stage 3 backend and persistence work may run in parallel after both specifications are approved and its issue is open. Each workstream uses its own branch and Git worktree; do not share a working directory. Both may edit the root `docker-compose.yml` in their isolated branches.

Stage 3.1 adds browser-to-API-to-database tracing, structured backend logs, and integration of the two Compose stacks. It may start only after Stage 2 is complete and has passed review. Stage 3.1 uses another isolated branch/worktree coordinated with the Stage 3 branch. Its PR must reconcile the Stage 2 and Stage 3 Compose changes and demonstrate the combined stack. Stage 3.1 may proceed while Stage 3 implementation continues; use a stacked PR/branch based on the Stage 3 work and rebase or retarget it as that work is integrated. Do not merge a Stage 3.1 change until its dependencies are present and verified together.

Stage 2's human review gate remains mandatory before Stage 3.1 and before Stage 3 may be considered complete. Stage 3 can implement independently during this review, but cannot claim end-to-end telemetry integration until Stage 3.1.

## Stage 2 goal and scope

Make the existing mock-backed PawLocal discovery journey observable. Demonstrate that normal results, empty results, and controlled failures can be distinguished in traces, metrics, logs, and Grafana dashboards.

Instrument browser journeys and the mock-service boundary for browse/search, filters/results, public place details, sharing, favourites, contributions, and reports when exercised in demo mode. Manually instrument browser journeys with OpenTelemetry spans and metrics, exporting OTLP/HTTP to a local Collector. Route traces to Tempo, metrics to Prometheus, and logs to Loki; Grafana must allow inspection of signals and trace IDs. Pin supported package versions, avoid broad experimental auto-instrumentation dependencies, and verify export with a smoke test. Keep application error logging behind a small replaceable logger adapter.

Add a development frontend container to the root Compose stack alongside the Collector, Prometheus, Loki, Tempo, and Grafana. Serve the frontend to the host browser and use lockfile-based dependency installation. Expose browser OTLP/HTTP on localhost and restrict Collector CORS to the local frontend origin. Keep all telemetry local; do not add hosted telemetry or billable cloud resources.

Gate telemetry behind an environment-controlled toggle. Local Compose enables it by default. When disabled, initialization and exports are no-ops and all PawLocal journeys continue to work. Keep configuration external so future deployment defaults can change without product code changes. Do not add cloud deployment configuration in this stage.

Provide a development/test-only fault control at the mock service boundary for deterministic search failure or delay. Production builds must exclude it; normal mock behavior must remain unchanged.

## Stage 2 signals and privacy

Create spans around journeys and asynchronous service operations. Preserve trace context across application/service boundaries and document a propagation contract that the Stage 3 HTTP adapter can continue. Record operation, outcome, duration, and bounded categories only. Provide search, detail, and demo-action outcome counters and search/detail duration histograms. Error logs include trace/span correlation IDs and stable error codes; distinguish valid empty results from failed requests.

Never emit raw search text, place or contribution payloads, names, email addresses, user IDs, tokens, or other personal data. Do not use place IDs or arbitrary query/filter values as metric labels. Browser telemetry must not send credentials; Collector CORS is limited to the local frontend origin.

## Stage 2 acceptance criteria

- [ ] One documented root Compose command builds and starts the frontend and local observability stack; the frontend is host-reachable, services report health, and shutdown is clean.
- [ ] Documented startup, health/status, shutdown, privacy, and synthetic-failure checks all pass locally and evidence is recorded in the PR.
- [ ] A browser search-to-detail journey appears as a correlated trace in Grafana/Tempo.
- [ ] Search result, empty, and injected failure outcomes are distinguishable in Prometheus panels and Loki logs, and logs link to the relevant trace.
- [ ] Dashboards show search/detail volume, success/empty/error outcomes and latency percentiles, with trace drill-down for failures.
- [ ] Share, favourite, contribution, and report actions produce bounded outcome telemetry when exercised.
- [ ] Tests cover telemetry emission, the development-only fault control, and the disabled-toggle no-op; production build excludes the fault control and works with telemetry disabled.
- [ ] Privacy review confirms that user-entered text, contribution content, credentials, and personal identifiers are not emitted.
- [ ] The monitoring walkthrough and evidence are recorded; human review approves dashboards and synthetic-failure demonstration before Stage 2 is complete.

## Stage 3.1 scope

Extend the Stage 2 propagation contract across browser → FastAPI → database. Add concise, useful spans for incoming API requests, application/use-case operations, and database operations; preserve correlation context without recording sensitive values. Add structured backend logs at appropriate DEBUG, INFO, WARNING, and ERROR levels. Include trace/span IDs, stable event/error codes, operation, and safe outcome context. Keep DEBUG detail useful but bounded; use WARNING for expected/recoverable problems and ERROR for failed operations. Do not log secrets, tokens, personal information, or contribution contents.

Reconcile root Compose changes from Stage 2 and Stage 3, preserving the frontend, telemetry stack, API, and database services, health checks, networks, volumes, and required configuration. Resolve service/port/environment conflicts explicitly. Verify the combined stack end to end.

## Stage 3.1 acceptance criteria

- [ ] A browser search-to-detail trace is correlated across browser, API, and database in the local trace backend.
- [ ] Structured API logs use appropriate DEBUG/INFO/WARNING/ERROR levels, include safe correlation context, and avoid excessive volume.
- [ ] Privacy checks confirm telemetry and logs exclude secrets, tokens, personal data, and contribution contents.
- [ ] Synthetic API/database failure scenarios produce useful correlated logs and traces without exposing sensitive values.
- [ ] Combined root Compose stack includes all Stage 2 frontend/observability and Stage 3 API/database services, with health/readiness and clean shutdown verified.
- [ ] Combined-stack verification evidence and any remaining limitations are reported in the Stage 3.1 PR; issue checkboxes are updated as criteria are completed.

## Out of scope

No production alerting, hosted telemetry, deployment, incident automation, or user-facing behavior changes. Stage 2 remains local and mock-backed; Stage 3.1 is local integration only.
