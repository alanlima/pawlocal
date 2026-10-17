import { MockPlaceService } from './MockPlaceService'
import type { PlaceService } from './PlaceService'

// Stage 1 uses seeded mock data. Swap this factory to HttpPlaceService in Stage 3.
export const placeService: PlaceService = new MockPlaceService()
