import { HttpPlaceService } from '../src/services/HttpPlaceService'
import type { PlaceService } from '../src/services/PlaceService'
import { observePlaceService } from '../src/services/observedPlaceService'

declare global {
  interface Window {
    __PAWLOCAL_E2E_ACCESS_TOKEN__?: string
  }
}

// This module is aliased only by vite.e2e.config.ts. The test helper supplies
// an isolated issuer token and keeps the real API calls under frontend spans.
const httpPlaceService: PlaceService = new HttpPlaceService(
  '/api/v1',
  () => window.__PAWLOCAL_E2E_ACCESS_TOKEN__ ?? null,
)
export const placeService: PlaceService = observePlaceService(httpPlaceService)
export const isMockBackend = false
