# PawLocal frontend

Responsive React + TypeScript + Vite + Tailwind CSS discovery experience for Stage 1. The app currently uses demo seed records and a mock service; dog access and facility facts remain unknown until verified.

## Run locally

```powershell
cd frontend
npm install
npm run dev
```

Open the local URL printed by Vite. The header's **Demo mode** control switches between visitor and demo-member states so contribution and favourite flows can be exercised without a real identity provider. Mock favourites persist in this browser's local storage; submitted contributions and reports are simulated only.

## Checks

```powershell
npm test
npm run build
npx playwright install chromium
npm run test:e2e
```

## Replace the mock API later

Feature components import the shared `placeService` instance from `src/services`. The `PlaceService` contract is in `src/services/PlaceService.ts`. `MockPlaceService` provides current Stage 1 behavior; `HttpPlaceService` is the adapter seam for the `/api/v1` endpoints in the root `openapi.yaml` and maps API snake_case fields to the frontend's camelCase domain type.

When the Stage 3 API is ready, change the factory in `src/services/index.ts` to instantiate `HttpPlaceService` (and provide its base URL/token supplier). Components and feature flows should not need to change. Review and update the adapter mapping if the approved OpenAPI contract changes. HTTP writes require the actual backend identity provider; no credentials or real authentication are included in this frontend stage.
