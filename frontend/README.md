# PawLocal frontend

Responsive React + TypeScript + Vite + Tailwind CSS discovery experience for Stage 1. The app currently uses demo seed records and a mock service; dog access and facility facts remain unknown until verified.

No fixture currently has verified access or facility facts, so facility filters intentionally return no matches until verified details are available. Sample ratings and counts are marked as demo data.

## Local frontend and observability stack

From the repository root, start the frontend, OpenTelemetry Collector, Prometheus, Loki, Tempo and Grafana with:

```powershell
docker compose up --build -d
docker compose ps
```

The app is at <http://localhost:5173>. Grafana is at <http://localhost:3000> and loads the **PawLocal local observability** dashboard. Prometheus, Loki, Tempo and the Collector health endpoint are also host-reachable on localhost ports 9090, 3100, 3200 and 13133. Compose binds every published port to loopback.

| Service | Host address | Purpose |
|---|---|---|
| Frontend | `localhost:5173` | Vite development UI |
| Collector OTLP/HTTP | `localhost:4318` | Browser traces, metrics and logs |
| Collector health | `localhost:13133` | Collector readiness |
| Grafana | `localhost:3000` | Dashboards, logs and Tempo traces |
| Prometheus | `localhost:9090` | Scraped frontend metrics |
| Loki | `localhost:3100` | Structured frontend logs |
| Tempo | `localhost:3200` | Frontend traces |

### Health and status checks

`docker compose ps` reports container health. From PowerShell, also check the service endpoints:

```powershell
Invoke-WebRequest http://localhost:5173 -UseBasicParsing
Invoke-WebRequest http://localhost:13133/ -UseBasicParsing
Invoke-WebRequest http://localhost:9090/-/ready -UseBasicParsing
Invoke-WebRequest http://localhost:3100/ready -UseBasicParsing
Invoke-WebRequest http://localhost:3200/ready -UseBasicParsing
Invoke-WebRequest http://localhost:3000/api/health -UseBasicParsing
```

The Collector accepts browser OTLP/HTTP only from `http://localhost:5173` and `http://127.0.0.1:5173`; its published receiver port is bound to loopback. Browser exports use the local endpoint `http://localhost:4318`. There are no credentials in browser requests.

### Walkthrough and synthetic failures

1. Open PawLocal, search for a matching area or place, then open a result.
2. In Grafana's PawLocal dashboard, inspect search/detail outcomes, latency and frontend logs. Open a log's trace ID to view its trace in Tempo. A successful search, a search with no results, and a failed search have distinct bounded outcomes.
3. Exercise **Share this place**, save a favourite in demo-member mode, submit a demo contribution and send a report to emit bounded action outcome counters/logs.
4. To inject a deterministic search error, open <http://localhost:5173/?demoFault=search-error>, then search or change a filter. The UI shows its existing error state; Grafana records `search/error` and `PAWLOCAL_OPERATION_FAILED`. For a bounded delay instead, use `?demoFault=search-delay`. Reload without the query parameter to restore normal mock behavior.

Fault controls are available only in the Vite development server when `VITE_DEMO_FAULTS=true`; the production build removes their code. Do not put search text or personal data in issue/PR telemetry screenshots. Telemetry records operation, outcome, duration and small fixed categories only; it excludes query text, place IDs, contribution/report payloads, names, email addresses and credentials. Error text from exceptions is not exported.

### Telemetry toggle and shutdown

Local Compose enables telemetry by default. To run the UI with telemetry disabled, set the Compose variable and recreate the frontend:

```powershell
$env:PAWLOCAL_TELEMETRY_ENABLED = 'false'
docker compose up --build -d frontend
```

The app remains usable and makes no telemetry export calls. Restore the default with `$env:PAWLOCAL_TELEMETRY_ENABLED = 'true'` and `docker compose up --build -d frontend` (or remove the variable). Stop the stack cleanly with:

```powershell
docker compose down
```

Local signal data is stored in Docker volumes. `docker compose down -v` also deletes those local telemetry volumes if you want to reset the demo data.

### Trace propagation contract

The frontend creates spans for bounded operations and uses W3C Trace Context. A place detail or demo action is a child of the latest search span when available. The Stage 3 HTTP adapter can call `injectCurrentTraceContext(headers)` from `src/observability/telemetry.ts` to add `traceparent` and `tracestate` to a request. Do not add query values, IDs, credentials or contribution fields to span attributes or metric labels.

## Run locally

```powershell
cd frontend
npm install
npm run dev
```

Open the local URL printed by Vite. The header's **Demo mode** control switches between visitor and demo-member states so contribution and favourite flows can be exercised without a real identity provider. Mock favourites persist in this browser's local storage; submitted contributions and reports are simulated only. Mock contributions remain available during the session as report targets. The initial report-target example is explicitly synthetic and is not community data or verified place information.

## Checks

```powershell
npm test
npm run build
npx playwright install chromium
npm run test:e2e
```

## Format and lint frontend TypeScript

From the `frontend` directory, run `npm run format` to format the React/TypeScript source under `src` and the TypeScript end-to-end tests under `e2e`. Prettier wraps code at 100 characters. To check formatting without changing files, run `npm run format:check`. Run `npm run lint` for TypeScript and React Hooks lint rules, or `npm run check` to run both checks together.

## Replace the mock API later

Feature components import the shared `placeService` instance from `src/services`. The `PlaceService` contract is in `src/services/PlaceService.ts`. `MockPlaceService` provides current Stage 1 behavior; `HttpPlaceService` is the adapter seam for the `/api/v1` endpoints in the root `openapi.yaml` and maps API snake_case fields to the frontend's camelCase domain type.

When the Stage 3 API is ready, change the factory in `src/services/index.ts` to instantiate `HttpPlaceService` (and provide its base URL/token supplier). Components and feature flows should not need to change. Review and update the adapter mapping if the approved OpenAPI contract changes. The current OpenAPI contract has `POST /contributions` but no contribution-list operation, so the HTTP adapter returns no contribution report targets; add an approved listing endpoint before enabling that flow against the real API. HTTP writes require the actual backend identity provider; no credentials or real authentication are included in this frontend stage.
