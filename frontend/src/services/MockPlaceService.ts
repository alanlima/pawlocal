import { demoPlaces } from '../data/demo-places'
import type { Contribution, ContributionInput, Place, PlaceQuery, ReportInput } from '../types/place'
import type { PlaceService } from './PlaceService'

const wait = (ms = 180) => new Promise<void>((resolve) => window.setTimeout(resolve, ms))
const readIds = (key: string): string[] => { try { return JSON.parse(localStorage.getItem(key) ?? '[]') as string[] } catch { return [] } }

export class MockPlaceService implements PlaceService {
  async listPlaces(query: PlaceQuery): Promise<Place[]> {
    await wait()
    const needle = query.q?.trim().toLocaleLowerCase()
    return demoPlaces.filter((place) => (!needle || `${place.name} ${place.area} ${place.category}`.toLocaleLowerCase().includes(needle))
      && (!query.area || place.area === query.area)
      && (!query.category || place.category === query.category)
      && (query.facilities?.every((facility) => place.facilities.includes(facility)) ?? true))
  }
  async getPlace(id: string) { await wait(100); return demoPlaces.find((place) => place.id === id) ?? null }
  async listFavourites() { await wait(80); return readIds('pawlocal-favourites') }
  async toggleFavourite(placeId: string) {
    await wait(80)
    const ids = readIds('pawlocal-favourites')
    localStorage.setItem('pawlocal-favourites', JSON.stringify(ids.includes(placeId) ? ids.filter((id) => id !== placeId) : [...ids, placeId]))
  }
  async submitContribution(input: ContributionInput): Promise<Contribution> {
    await wait(180)
    return { ...input, id: crypto.randomUUID(), createdAt: new Date().toISOString() }
  }
  async submitReport(input: ReportInput) { await wait(180); void input }
}
