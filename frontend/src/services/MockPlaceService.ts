import { demoPlaces } from '../data/demo-places'
import { demoContributions } from '../data/demo-contributions'
import type { Contribution, ContributionInput, Place, PlaceQuery, ReportInput } from '../types/place'
import type { PlaceService } from './PlaceService'

const wait = (ms = 180, signal?: AbortSignal) => new Promise<void>((resolve, reject) => {
  if (signal?.aborted) { reject(signal.reason ?? new DOMException('The operation was aborted.', 'AbortError')); return }
  const timer = window.setTimeout(() => { signal?.removeEventListener('abort', onAbort); resolve() }, ms)
  const onAbort = () => { window.clearTimeout(timer); reject(signal?.reason ?? new DOMException('The operation was aborted.', 'AbortError')) }
  signal?.addEventListener('abort', onAbort, { once: true })
})
const readIds = (key: string): string[] => { try { return JSON.parse(localStorage.getItem(key) ?? '[]') as string[] } catch { return [] } }

export class MockPlaceService implements PlaceService {
  private contributions: Contribution[] = [...demoContributions]
  async listPlaces(query: PlaceQuery, signal?: AbortSignal): Promise<Place[]> {
    await wait(180, signal)
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
    const contribution = { ...input, id: crypto.randomUUID(), createdAt: new Date().toISOString(), demoOnly: true }
    this.contributions = [contribution, ...this.contributions]
    return contribution
  }
  async listReportableContributions() { await wait(80); return this.contributions.map((contribution) => ({ ...contribution })) }
  async submitReport(input: ReportInput) { await wait(180); void input }
}
