import { MockPlaceService } from './MockPlaceService'
import { HttpPlaceService } from './HttpPlaceService'
import type { PlaceService } from './PlaceService'
import { observePlaceService } from './observedPlaceService'
import { validateReleaseConfig } from '../config/releaseConfig'

validateReleaseConfig()

const apiBaseUrl = import.meta.env.VITE_API_BASE_URL?.trim()
const configuredMockToggle = import.meta.env.VITE_USE_MOCK_BACKEND?.trim().toLowerCase()

if (configuredMockToggle && configuredMockToggle !== 'true' && configuredMockToggle !== 'false') {
  throw new Error('VITE_USE_MOCK_BACKEND must be either "true" or "false"')
}

const service: PlaceService =
  configuredMockToggle === 'true'
    ? new MockPlaceService()
    : new HttpPlaceService(apiBaseUrl || '/api/v1')

export const isMockBackend = configuredMockToggle === 'true'
export const placeService: PlaceService = observePlaceService(service)
