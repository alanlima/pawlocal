import type {
  Contribution,
  ContributionInput,
  Place,
  PlaceQuery,
  ReportInput,
} from '../types/place'
import type { PlaceService } from './PlaceService'
import { injectCurrentTraceContext } from '../observability/telemetry'

type PlaceWire = {
  id: string
  name: string
  category: Place['category']
  area: string
  address?: string | null
  description?: string | null
  dog_access_rules?: string | null
  facilities?: string[]
  average_rating?: number | null
  source_updated_at?: string | null
}
type ContributionWire = { id: string; created_at: string }
type ReportableContributionWire = Pick<Contribution, 'id' | 'kind' | 'body'> & {
  place_id: string | null
  rating: number | null
  created_at: string
}
const fromWire = (wire: PlaceWire): Place => ({
  id: wire.id,
  name: wire.name,
  category: wire.category,
  area: wire.area,
  address: wire.address ?? null,
  description: wire.description ?? null,
  dogAccessRules: wire.dog_access_rules ?? null,
  facilities: (wire.facilities ?? []) as Place['facilities'],
  averageRating: wire.average_rating ?? null,
  reviewCount: null,
  sourceUpdatedAt: wire.source_updated_at ?? null,
  accent: 'green',
})

/** HTTP adapter seam. Map API wire names here; feature components stay adapter agnostic. */
export class HttpPlaceService implements PlaceService {
  constructor(
    private readonly baseUrl = '/api/v1',
    private readonly token?: () => string | null,
  ) {}
  private async request<T>(path: string, init: RequestInit = {}): Promise<T> {
    const headers = new Headers(init.headers)
    headers.set('Content-Type', 'application/json')
    const token = this.token?.()
    if (token) headers.set('Authorization', `Bearer ${token}`)
    const propagatedHeaders = injectCurrentTraceContext(Object.fromEntries(headers.entries()))
    for (const [name, value] of Object.entries(propagatedHeaders)) headers.set(name, value)
    const response = await fetch(`${this.baseUrl}${path}`, { ...init, headers })
    if (!response.ok) throw new Error(`PawLocal API error (${response.status})`)
    return response.status === 204 || response.status === 202
      ? (undefined as T)
      : (response.json() as Promise<T>)
  }
  async listPlaces(query: PlaceQuery, signal?: AbortSignal): Promise<Place[]> {
    const results: PlaceWire[] = []
    const pageSize = 100
    let pageNumber = 1
    let total = Number.POSITIVE_INFINITY
    while (results.length < total) {
      if (signal?.aborted)
        throw signal.reason ?? new DOMException('The operation was aborted.', 'AbortError')
      const params = new URLSearchParams({ page: String(pageNumber), page_size: String(pageSize) })
      if (query.q) params.set('q', query.q)
      if (query.area) params.set('area', query.area)
      if (query.category) params.set('category', query.category)
      query.facilities?.forEach((facility) => params.append('facilities', facility))
      const page = await this.request<{ items: PlaceWire[]; total: number }>(`/places?${params}`, {
        signal,
      })
      total = page.total
      if (page.items.length === 0) break
      results.push(...page.items)
      pageNumber += 1
    }
    return results.map(fromWire)
  }
  getPlace(id: string) {
    return this.request<PlaceWire>(`/places/${id}`)
      .then(fromWire)
      .catch((error: unknown) => {
        if (error instanceof Error && error.message.includes('(404)')) return null
        throw error
      })
  }
  async listFavourites() {
    const places = await this.request<Array<{ id: string }>>('/me/favourites')
    return places.map((place) => place.id)
  }
  async toggleFavourite(placeId: string) {
    const favourites = await this.listFavourites()
    if (favourites.includes(placeId))
      await this.request<void>(`/me/favourites/${placeId}`, { method: 'DELETE' })
    else
      await this.request<void>('/me/favourites', {
        method: 'PUT',
        body: JSON.stringify({ place_id: placeId }),
      })
  }
  async submitContribution(input: ContributionInput) {
    const wire = await this.request<ContributionWire>('/contributions', {
      method: 'POST',
      body: JSON.stringify({
        kind: input.kind,
        place_id: input.placeId ?? null,
        ...(input.kind === 'review' ? { rating: input.rating } : {}),
        body: input.body,
      }),
    })
    return { ...input, id: wire.id, createdAt: wire.created_at }
  }
  async listReportableContributions(): Promise<Contribution[]> {
    const contributions: Contribution[] = []
    const pageSize = 100
    let pageNumber = 1
    let total = Number.POSITIVE_INFINITY
    while (contributions.length < total) {
      const page = await this.request<{
        items: ReportableContributionWire[]
        total: number
      }>(`/contributions/reportable?page=${pageNumber}&page_size=${pageSize}`)
      total = page.total
      if (page.items.length === 0) break
      contributions.push(
        ...page.items.map((item) => ({
          id: item.id,
          kind: item.kind,
          body: item.body,
          placeId: item.place_id ?? undefined,
          rating: item.rating ?? undefined,
          createdAt: item.created_at,
        })),
      )
      pageNumber += 1
    }
    return contributions
  }
  async submitReport(input: ReportInput) {
    await this.request<void>('/reports', {
      method: 'POST',
      body: JSON.stringify({
        target_type: input.targetType,
        target_id: input.targetId,
        reason: input.reason,
      }),
    })
  }
}
