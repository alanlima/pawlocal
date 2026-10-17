import { HttpPlaceService } from '../src/services/HttpPlaceService'
import type { PlaceService } from '../src/services/PlaceService'

declare global {
  interface Window {
    __PAWLOCAL_E2E_ACCESS_TOKEN__?: string
  }
}

// This module is aliased only by vite.e2e.config.ts. Production keeps its
// Stage 2-wrapped mock factory and never reads a browser-injected token.
export const placeService: PlaceService = new HttpPlaceService(
  '/api/v1',
  () => window.__PAWLOCAL_E2E_ACCESS_TOKEN__ ?? null,
)
