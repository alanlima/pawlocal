import type {
  Contribution,
  ContributionInput,
  Place,
  PlaceQuery,
  ReportInput,
} from '../types/place'

export interface PlaceServiceRequestContext {
  traceparent?: string
  tracestate?: string
}

export interface PlaceService {
  listPlaces(
    query: PlaceQuery,
    signal?: AbortSignal,
    context?: PlaceServiceRequestContext,
  ): Promise<Place[]>
  listReportableContributions(): Promise<Contribution[]>
  getPlace(id: string, context?: PlaceServiceRequestContext): Promise<Place | null>
  listFavourites(context?: PlaceServiceRequestContext): Promise<string[]>
  toggleFavourite(placeId: string, context?: PlaceServiceRequestContext): Promise<void>
  submitContribution(
    input: ContributionInput,
    context?: PlaceServiceRequestContext,
  ): Promise<Contribution>
  submitReport(input: ReportInput, context?: PlaceServiceRequestContext): Promise<void>
}
