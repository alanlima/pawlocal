import { afterEach, describe, expect, it, vi } from 'vitest'
import { HttpPlaceService } from './services/HttpPlaceService'

afterEach(() => {
  vi.unstubAllGlobals()
  vi.unstubAllEnvs()
})

describe('incident regression', () => {
  it('keeps discovery and detail GET requests free of an unnecessary JSON content type header', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ items: [], page: 1, page_size: 100, total: 0 }), {
          status: 200,
        }),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            id: '00000000-0000-4000-8000-000000000001',
            name: 'Demo Place',
            category: 'walk',
            area: 'Brisbane City',
            average_rating: null,
          }),
          { status: 200 },
        ),
      )
    vi.stubGlobal('fetch', fetchMock)

    const service = new HttpPlaceService('/api/v1', async () => null)
    await service.listPlaces({})
    await service.getPlace('00000000-0000-4000-8000-000000000001')

    expect(new Headers(fetchMock.mock.calls[0][1]?.headers).has('Content-Type')).toBe(false)
    expect(new Headers(fetchMock.mock.calls[1][1]?.headers).has('Content-Type')).toBe(false)
  })
})
