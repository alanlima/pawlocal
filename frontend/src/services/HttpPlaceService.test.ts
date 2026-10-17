import { afterEach, describe, expect, it, vi } from 'vitest'
import { HttpPlaceService } from './HttpPlaceService'

afterEach(() => vi.unstubAllGlobals())

describe('HttpPlaceService', () => {
  it('follows the OpenAPI pagination until all results are loaded and ignores undefined review counts', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ items: [{ id: '00000000-0000-4000-8000-000000000001', name: 'First', category: 'walk', area: 'Brisbane City', average_rating: 4.1 }], page: 1, page_size: 100, total: 2 }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ items: [{ id: '00000000-0000-4000-8000-000000000002', name: 'Second', category: 'beach', area: 'Gold Coast', average_rating: null }], page: 2, page_size: 100, total: 2 }), { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)

    const places = await new HttpPlaceService().listPlaces({ q: 'coast', area: 'Gold Coast', category: '', facilities: ['Shade'] })

    expect(places.map((place) => place.name)).toEqual(['First', 'Second'])
    expect(places[0].averageRating).toBe(4.1)
    expect(places[0].reviewCount).toBeNull()
    expect(fetchMock).toHaveBeenCalledTimes(2)
    expect(String(fetchMock.mock.calls[0][0])).toContain('page=1')
    expect(String(fetchMock.mock.calls[1][0])).toContain('page=2')
    expect(String(fetchMock.mock.calls[0][0])).toContain('page_size=100')
  })

  it('passes the abort signal through pagination and stops before requesting later pages', async () => {
    const controller = new AbortController()
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      expect(init?.signal).toBe(controller.signal)
      controller.abort()
      return new Response(JSON.stringify({ items: [{ id: '00000000-0000-4000-8000-000000000001', name: 'First', category: 'walk', area: 'Brisbane City' }], page: 1, page_size: 100, total: 250 }), { status: 200 })
    })
    vi.stubGlobal('fetch', fetchMock)

    await expect(new HttpPlaceService().listPlaces({}, controller.signal)).rejects.toMatchObject({ name: 'AbortError' })
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })
})
