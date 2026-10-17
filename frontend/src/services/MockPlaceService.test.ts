import { beforeEach, describe, expect, it } from 'vitest'
import { MockPlaceService } from './MockPlaceService'

describe('MockPlaceService', () => {
  const service = new MockPlaceService()
  beforeEach(() => localStorage.clear())

  it('filters records by text, category and area', async () => {
    const places = await service.listPlaces({
      q: 'foreshore',
      category: 'walk',
      area: 'Moreton Bay',
    })
    expect(places.map((place) => place.name)).toEqual(['Redcliffe Foreshore'])
  })

  it('returns explicit unknowns for unverified details', async () => {
    const place = await service.getPlace('0d8a22c2-4316-4dd3-b25b-0baa110a1ae1')
    expect(place?.dogAccessRules).toBeNull()
    expect(place?.facilities).toEqual([])
  })

  it('adds and removes a favourite', async () => {
    await service.toggleFavourite('place-1')
    expect(await service.listFavourites()).toEqual(['place-1'])
    await service.toggleFavourite('place-1')
    expect(await service.listFavourites()).toEqual([])
  })

  it('lists explicit demo-only report targets and keeps submitted contributions reportable', async () => {
    const service = new MockPlaceService()
    const initial = await service.listReportableContributions()
    expect(initial[0].demoOnly).toBe(true)
    expect(initial[0].body).toContain('not community data')
    const submitted = await service.submitContribution({
      kind: 'tip',
      body: 'A user-entered demo note.',
    })
    expect((await service.listReportableContributions()).map((item) => item.id)).toContain(
      submitted.id,
    )
  })
})
