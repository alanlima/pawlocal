import { MockPlaceService } from './MockPlaceService'
import type { PlaceService } from './PlaceService'
import { observePlaceService } from './observedPlaceService'

// Stage 1 uses seeded mock data. Swap this factory to HttpPlaceService in Stage 3.
const mockService: PlaceService = new MockPlaceService()
export const placeService: PlaceService = observePlaceService(mockService)
