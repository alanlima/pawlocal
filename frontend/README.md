# PawLocal frontend

Responsive React + TypeScript + Vite + Tailwind CSS discovery experience. The app uses `MockPlaceService` only when `VITE_USE_MOCK_BACKEND=true`; otherwise it uses the typed HTTP adapter at `VITE_API_BASE_URL` (default `/api/v1`). Vite proxies `/api/v1` to `VITE_API_PROXY_TARGET` (default `http://127.0.0.1:8000`) during local development. Dog access and facility facts remain unknown until verified.

No fixture currently has verified access or facility facts, so facility filters intentionally return no matches until verified details are available. Sample ratings and counts are marked as demo data.

## Local frontend and observability stack

From the repository root, start the frontend, FastAPI backend, PostgreSQL, OpenTelemetry Collector, Prometheus, Loki, Tempo and Grafana with:

```powershell
docker compose up --build -d
docker compose ps
```

If a host port is already in use, override the frontend and Grafana published ports and the Collector's allowed browser origin before startup. Example for PowerShell:

```powershell
$env:PAWLOCAL_FRONTEND_PORT = '5174'
$env:PAWLOCAL_GRAFANA_PORT = '3001'
$env:PAWLOCAL_FRONTEND_ORIGIN = 'http://localhost:5174'
docker compose up --build -d
```

These override values make PawLocal available at <http://localhost:5174> and Grafana at <http://localhost:3001>. The Collector permits OTLP browser requests from `http://localhost:5174` for this run.

With default ports, the app is at <http://localhost:5173>, Grafana is at <http://localhost:3000>, and the API health check is at <http://localhost:8000/health>; Grafana loads the **PawLocal local observability** dashboard. Prometheus, Loki, Tempo, the Collector health endpoint and PostgreSQL are also host-reachable on localhost ports 9090, 3100, 3200, 13133 and 55432. Compose binds every published port to loopback. The frontend uses the HTTP adapter with the Vite proxy to `backend:8000`; set `VITE_USE_MOCK_BACKEND=true` only when running the mock-only frontend without the backend service.

| Service | Host address | Purpose |
|---|---|---|
| Frontend (default) | `localhost:5173` | Vite development UI |
| FastAPI backend | `localhost:8000` | API health and local synthetic-failure requests |
| PostgreSQL | `localhost:55432` | Local persistence |
| Collector OTLP/HTTP | `localhost:4318` | Browser traces, metrics and logs |
| Collector health | `localhost:13133` | Collector readiness |
| Grafana (default) | `localhost:3000` | Dashboards, logs and Tempo traces |
| Prometheus | `localhost:9090` | Scraped frontend metrics |
| Loki | `localhost:3100` | Structured frontend and backend logs |
| Tempo | `localhost:3200` | Correlated browser, API and database traces |

### Health and status checks

`docker compose ps` reports container health. From PowerShell, also check the service endpoints:

```powershell
Invoke-WebRequest http://localhost:5173 -UseBasicParsing # use 5174 for the port-conflict example above
Invoke-WebRequest http://localhost:13133/ -UseBasicParsing
Invoke-WebRequest http://localhost:9090/-/ready -UseBasicParsing
Invoke-WebRequest http://localhost:3100/ready -UseBasicParsing
Invoke-WebRequest http://localhost:3200/ready -UseBasicParsing
Invoke-WebRequest http://localhost:3000/api/health -UseBasicParsing # use 3001 for the port-conflict example above
```

Compose checks Collector readiness at `http://127.0.0.1:13133/` and Tempo readiness at `http://127.0.0.1:3200/ready`. Their upstream images do not include HTTP client tools, so the local images add a static BusyBox probe for these healthchecks.

The Collector accepts browser OTLP/HTTP only from the origin in `PAWLOCAL_FRONTEND_ORIGIN` (default `http://localhost:5173`); set it to match the overridden frontend origin, as in the example above. Its published receiver port is bound to loopback. Browser exports use the local endpoint `http://localhost:4318`. There are no credentials in browser requests.

### Walkthrough and synthetic failures

1. Open PawLocal, search for a matching area or place, then open a result.
2. In Grafana's PawLocal dashboard, inspect search/detail outcomes, latency and frontend logs. Open a log's trace ID to view its trace in Tempo. A successful search, a search with no results, and a failed search have distinct bounded outcomes.
3. Exercise **Share this place**, save a favourite in demo-member mode, submit a demo contribution and send a report to emit bounded action outcome counters/logs.
4. To inject a deterministic search error, open `http://localhost:<frontend-port>/?demoFault=search-error` (default port `5173`; `5174` in the example above), then search or change a filter. The UI shows its existing error state; Grafana records `search/error` and `PAWLOCAL_OPERATION_FAILED`. For a bounded delay instead, use `?demoFault=search-delay`. Reload without the query parameter to restore normal mock behavior.

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

The frontend creates spans for bounded operations and uses W3C Trace Context. A place detail or demo action is a child of the latest search span when available. `HttpPlaceService` injects `traceparent` and `tracestate` into API requests, so the backend server span and SQLAlchemy database spans join the browser trace. Do not add query values, IDs, credentials or contribution fields to span attributes or metric labels.

## Run locally

```powershell
cd frontend
npm install
npm run dev
```

Open the local URL printed by Vite. The header's **Demo mode** control switches between visitor and demo-member states only when `VITE_USE_MOCK_BACKEND=true`. Mock favourites persist in this browser's local storage; submitted contributions and reports are simulated only. Mock contributions remain available during the session as report targets. The initial report-target example is explicitly synthetic and is not community data or verified place information.

## Checks

```powershell
npm test
npm run build
npx playwright install chromium
npm run test:e2e
npm run test:e2e:backend
```

`test:e2e:backend` expects the isolated PostgreSQL-backed API and ephemeral JWKS issuer from `backend/README.md` to be running on ports 18001 and 18002. It uses a separate Vite config and HTTP-service alias.

## Format and lint frontend TypeScript

From the `frontend` directory, run `npm run format` to format the React/TypeScript source under `src` and the TypeScript end-to-end tests under `e2e`. Prettier wraps code at 100 characters. To check formatting without changing files, run `npm run format:check`. Run `npm run lint` for TypeScript and React Hooks lint rules, or `npm run check` to run both checks together.

## Frontend service mode

Feature components import the shared `placeService` instance from `src/services`. The `PlaceService` contract is in `src/services/PlaceService.ts`. `HttpPlaceService` calls the `/api/v1` endpoints in the root `openapi.yaml` and maps API snake_case fields to the frontend's camelCase domain type. `MockPlaceService` remains available for the mock demonstration.

The approved OpenAPI contract includes the public, paginated `GET /contributions/reportable` operation. `HttpPlaceService` maps only the public response fields to the frontend contribution type; contributor and reporter identities are never returned. The service factory selects `MockPlaceService` only when `VITE_USE_MOCK_BACKEND=true`; false or unset selects `HttpPlaceService`, using `VITE_API_BASE_URL` or the same-origin `/api/v1` default. Root Compose sets mock mode to false and proxies `/api/v1` to the `backend` service. HTTP failures stay visible and never fall back to mock data.

### Host authentication integration

The frontend does not implement sign-in screens or provision an identity provider. A host application may inject the current Cognito session before the PawLocal app loads using this browser contract:

```ts
window.pawLocalAuth = {
  getAccessToken: () => cognitoSession.getAccessToken(), // sync or Promise<string | null>
  signIn: () => startHostSignIn(), // optional
  signOut: () => endHostSession(), // optional
}
```

`getAccessToken()` is called for every HTTP request; return the current short-lived Cognito **access token**, or `null` when signed out. The adapter adds it as a Bearer token for protected API calls and does not persist or display it. The host owns the sign-in/sign-out UX and token refresh. If no provider or sign-in action is configured, the HTTP-mode UI reports that authentication is unavailable and does not simulate a signed-in user. Mock demo-member mode is only a local mock behavior and does not authenticate HTTP requests. Authenticated browser flows remain unverified until a host supplies a configured Cognito session.
