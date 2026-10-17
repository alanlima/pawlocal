import type { Contribution, ContributionInput, Place, PlaceQuery, ReportInput } from '../types/place'

export interface PlaceService {
  listPlaces(query: PlaceQuery): Promise<Place[]>
  getPlace(id: string): Promise<Place | null>
  listFavourites(): Promise<string[]>
  toggleFavourite(placeId: string): Promise<void>
  submitContribution(input: ContributionInput): Promise<Contribution>
  submitReport(input: ReportInput): Promise<void>
}
