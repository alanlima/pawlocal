# PawLocal frontend

Responsive React + TypeScript + Vite + Tailwind CSS discovery experience for Stage 1. The app currently uses demo seed records and a mock service; dog access and facility facts remain unknown until verified.

No fixture currently has verified access or facility facts, so facility filters intentionally return no matches until verified details are available. Sample ratings and counts are marked as demo data.

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
