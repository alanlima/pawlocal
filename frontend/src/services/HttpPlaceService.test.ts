import { afterEach, describe, expect, it, vi } from 'vitest'
import { HttpPlaceService } from './HttpPlaceService'

afterEach(() => vi.unstubAllGlobals())

describe('HttpPlaceService', () => {
  it('follows the OpenAPI pagination until all results are loaded and ignores undefined review counts', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            items: [
              {
                id: '00000000-0000-4000-8000-000000000001',
                name: 'First',
                category: 'walk',
                area: 'Brisbane City',
                average_rating: 4.1,
              },
            ],
            page: 1,
            page_size: 100,
            total: 2,
          }),
          { status: 200 },
        ),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            items: [
              {
                id: '00000000-0000-4000-8000-000000000002',
                name: 'Second',
                category: 'beach',
                area: 'Gold Coast',
                average_rating: null,
              },
            ],
            page: 2,
            page_size: 100,
            total: 2,
          }),
          { status: 200 },
        ),
      )
    vi.stubGlobal('fetch', fetchMock)

    const places = await new HttpPlaceService().listPlaces({
      q: 'coast',
      area: 'Gold Coast',
      category: '',
      facilities: ['Shade'],
    })

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
      return new Response(
        JSON.stringify({
          items: [
            {
              id: '00000000-0000-4000-8000-000000000001',
              name: 'First',
              category: 'walk',
              area: 'Brisbane City',
            },
          ],
          page: 1,
          page_size: 100,
          total: 250,
        }),
        { status: 200 },
      )
    })
    vi.stubGlobal('fetch', fetchMock)

    await expect(new HttpPlaceService().listPlaces({}, controller.signal)).rejects.toMatchObject({
      name: 'AbortError',
    })
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('loads reportable contributions across pages and maps only public fields', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            items: [
              {
                id: 'contribution-1',
                kind: 'review',
                body: 'A useful public review',
                place_id: 'place-1',
                rating: 4,
                created_at: '2026-10-18T00:00:00Z',
                contributor_id: 'private-user-id',
              },
            ],
            page: 1,
            page_size: 100,
            total: 2,
          }),
          { status: 200 },
        ),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            items: [
              {
                id: 'contribution-2',
                kind: 'tip',
                body: 'Bring water',
                place_id: null,
                rating: null,
                created_at: '2026-10-18T00:01:00Z',
              },
            ],
            page: 2,
            page_size: 100,
            total: 2,
          }),
          { status: 200 },
        ),
      )
    vi.stubGlobal('fetch', fetchMock)

    const contributions = await new HttpPlaceService().listReportableContributions()

    expect(contributions).toEqual([
      {
        id: 'contribution-1',
        kind: 'review',
        body: 'A useful public review',
        placeId: 'place-1',
        rating: 4,
        createdAt: '2026-10-18T00:00:00Z',
      },
      {
        id: 'contribution-2',
        kind: 'tip',
        body: 'Bring water',
        placeId: undefined,
        rating: undefined,
        createdAt: '2026-10-18T00:01:00Z',
      },
    ])
    expect(fetchMock).toHaveBeenCalledTimes(2)
    expect(String(fetchMock.mock.calls[0][0])).toContain('/contributions/reportable?page=1')
    expect(String(fetchMock.mock.calls[1][0])).toContain('/contributions/reportable?page=2')
  })

  it('returns an empty list when no contributions are reportable', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ items: [], page: 1, page_size: 100, total: 0 }), {
        status: 200,
      }),
    )
    vi.stubGlobal('fetch', fetchMock)

    await expect(new HttpPlaceService().listReportableContributions()).resolves.toEqual([])
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('propagates reportable-contribution HTTP errors', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('unavailable', { status: 503 })))

    await expect(new HttpPlaceService().listReportableContributions()).rejects.toThrow(
      'PawLocal API error (503)',
    )
  })
})
