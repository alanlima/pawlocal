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

The approved OpenAPI contract includes the public, paginated `GET /contributions/reportable` operation. `HttpPlaceService` maps only the public response fields to the frontend contribution type; contributor and reporter identities are never returned. The Stage 3 service factory remains on the mock adapter until the complete API and authentication flows are ready. HTTP writes use the backend's configured identity provider and are not authenticated by the frontend demo mode.
