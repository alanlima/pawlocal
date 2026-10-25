import { afterEach, describe, expect, it, vi } from 'vitest'
import { HttpPlaceService } from './HttpPlaceService'

afterEach(() => {
  vi.unstubAllGlobals()
  vi.unstubAllEnvs()
  sessionStorage.clear()
})

describe('HttpPlaceService', () => {
  it('propagates hosted traceparent only to the configured API origin and omits tracestate', async () => {
    vi.stubEnv('VITE_RELEASE_ENV', 'development')
    vi.stubEnv('VITE_API_BASE_URL', 'https://pawlocal-dev.example.test/api/v1')
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockImplementation(
        async () => new Response(JSON.stringify({ items: [], page: 1, page_size: 100, total: 0 })),
      )
    vi.stubGlobal('fetch', fetchMock)
    const context = {
      traceparent: '00-' + 'a'.repeat(32) + '-' + 'b'.repeat(16) + '-01',
      tracestate: 'private=sentinel',
    }
    await new HttpPlaceService('https://pawlocal-dev.example.test/api/v1').listPlaces(
      {},
      undefined,
      context,
    )
    await new HttpPlaceService('https://foreign.example.test/api/v1').listPlaces(
      {},
      undefined,
      context,
    )
    const approved = new Headers(fetchMock.mock.calls[0][1]?.headers)
    const foreign = new Headers(fetchMock.mock.calls[1][1]?.headers)
    expect(approved.get('traceparent')).toBe(context.traceparent)
    expect(approved.has('tracestate')).toBe(false)
    expect(foreign.has('traceparent')).toBe(false)
    expect(foreign.has('tracestate')).toBe(false)
  })

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

  it('sends ratings only for review contributions', async () => {
    const response = () =>
      new Response(JSON.stringify({ id: 'contribution-id', created_at: '2026-10-18T00:00:00Z' }), {
        status: 201,
      })
    const fetchMock = vi.fn().mockResolvedValueOnce(response()).mockResolvedValueOnce(response())
    vi.stubGlobal('fetch', fetchMock)
    const service = new HttpPlaceService()

    await service.submitContribution({ kind: 'tip', body: 'Bring water' })
    await service.submitContribution({
      kind: 'review',
      placeId: 'place-id',
      rating: 4,
      body: 'A helpful review',
    })

    const tipPayload = JSON.parse(fetchMock.mock.calls[0][1]?.body as string)
    const reviewPayload = JSON.parse(fetchMock.mock.calls[1][1]?.body as string)
    expect(tipPayload).not.toHaveProperty('rating')
    expect(reviewPayload.rating).toBe(4)
  })

  it('attaches the Cognito access token to protected API requests', async () => {
    const fetchMock = vi.fn((_input: RequestInfo | URL, _init?: RequestInit) => {
      void _input
      void _init
      return Promise.resolve(new Response(JSON.stringify([]), { status: 200 }))
    })
    vi.stubGlobal('fetch', fetchMock)
    vi.stubEnv('VITE_COGNITO_DOMAIN', 'https://pawlocal-test.auth.ap-southeast-2.amazoncognito.com')
    vi.stubEnv('VITE_COGNITO_CLIENT_ID', 'public-app-client')
    vi.stubEnv('VITE_COGNITO_REDIRECT_URI', 'https://pawlocal.example.test/')
    vi.stubEnv('VITE_COGNITO_LOGOUT_URI', 'https://pawlocal.example.test/')
    const tokenPayload = btoa(
      JSON.stringify({
        token_use: 'access',
        client_id: 'public-app-client',
        exp: Math.floor(Date.now() / 1000) + 600,
      }),
    )
    sessionStorage.setItem(
      'pawlocal.cognito.session',
      JSON.stringify({
        accessToken: `header.${tokenPayload}.signature`,
        expiresAt: Date.now() + 600_000,
        refreshToken: 'refresh-token',
      }),
    )

    await new HttpPlaceService().listFavourites()

    expect(new Headers(fetchMock.mock.calls[0][1]?.headers).get('Authorization')).toBe(
      `Bearer header.${tokenPayload}.signature`,
    )
  })

  it('attaches a fresh token to favourites and contribution/report writes', async () => {
    const fetchMock = vi
      .fn<(input: RequestInfo | URL, init?: RequestInit) => Promise<Response>>()
      .mockImplementation((input, _init) => {
        void _init
        const path = String(input)
        return Promise.resolve(
          path.endsWith('/me/favourites')
            ? new Response(JSON.stringify([]), { status: 200 })
            : path.endsWith('/contributions')
              ? new Response(JSON.stringify({ id: 'contribution-1', created_at: 'now' }), {
                  status: 201,
                })
              : new Response(null, { status: 202 }),
        )
      })
    const tokenProvider = vi.fn().mockResolvedValue('protected-token')
    vi.stubGlobal('fetch', fetchMock)
    const service = new HttpPlaceService('/api/v1', tokenProvider)

    await service.listFavourites()
    await service.submitContribution({ kind: 'tip', body: 'Bring water' })
    await service.submitReport({ targetType: 'place', targetId: 'place-1', reason: 'Incorrect' })

    expect(tokenProvider).toHaveBeenCalledTimes(3)
    expect(fetchMock).toHaveBeenCalledTimes(3)
    for (const [, init] of fetchMock.mock.calls) {
      expect(new Headers(init?.headers).get('Authorization')).toBe('Bearer protected-token')
    }
  })

  it('requests a fresh synchronous host token for each protected request', async () => {
    const fetchMock = vi.fn((_input: RequestInfo | URL, _init?: RequestInit) => {
      void _input
      void _init
      return Promise.resolve(new Response(JSON.stringify([]), { status: 200 }))
    })
    const tokenProvider = vi
      .fn()
      .mockReturnValueOnce('first-token')
      .mockReturnValueOnce('next-token')
    vi.stubGlobal('fetch', fetchMock)
    const service = new HttpPlaceService('/api/v1', tokenProvider)

    await service.listFavourites()
    await service.listFavourites()

    expect(tokenProvider).toHaveBeenCalledTimes(2)
    expect(new Headers(fetchMock.mock.calls[0][1]?.headers).get('Authorization')).toBe(
      'Bearer first-token',
    )
    expect(new Headers(fetchMock.mock.calls[1][1]?.headers).get('Authorization')).toBe(
      'Bearer next-token',
    )
  })

  it('sends protected requests without Authorization when the Cognito session is absent', async () => {
    const fetchMock = vi.fn((_input: RequestInfo | URL, _init?: RequestInit) => {
      void _input
      void _init
      return Promise.resolve(new Response(JSON.stringify([]), { status: 200 }))
    })
    vi.stubGlobal('fetch', fetchMock)

    await new HttpPlaceService().listFavourites()

    expect(new Headers(fetchMock.mock.calls[0][1]?.headers).has('Authorization')).toBe(false)
  })

  it('does not await a failing token refresh for public reads', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, _init?: RequestInit) => {
      void _init
      const url = String(input)
      if (url.includes('/places?')) {
        return new Response(JSON.stringify({ items: [], total: 0 }), { status: 200 })
      }
      if (url.includes('/contributions/reportable')) {
        return new Response(JSON.stringify({ items: [], total: 0 }), { status: 200 })
      }
      return new Response(
        JSON.stringify({
          id: 'place-1',
          name: 'Test Place',
          category: 'walk',
          area: 'Brisbane City',
        }),
        { status: 200 },
      )
    })
    const tokenProvider = vi.fn().mockRejectedValue(new Error('refresh unavailable'))
    vi.stubGlobal('fetch', fetchMock)
    const service = new HttpPlaceService('/api/v1', tokenProvider)

    await expect(service.listPlaces({})).resolves.toEqual([])
    await expect(service.getPlace('place-1')).resolves.toMatchObject({ id: 'place-1' })
    await expect(service.listReportableContributions()).resolves.toEqual([])

    expect(tokenProvider).not.toHaveBeenCalled()
    expect(fetchMock).toHaveBeenCalledTimes(3)
    expect(
      fetchMock.mock.calls.every(([, init]) => !new Headers(init?.headers).has('Authorization')),
    ).toBe(true)
  })

  it('fails closed when token refresh fails for protected writes', async () => {
    const fetchMock = vi.fn()
    const tokenProvider = vi.fn().mockRejectedValue(new Error('refresh unavailable'))
    vi.stubGlobal('fetch', fetchMock)
    const service = new HttpPlaceService('/api/v1', tokenProvider)

    await expect(service.listFavourites()).rejects.toThrow('refresh unavailable')
    await expect(service.submitContribution({ kind: 'tip', body: 'Bring water' })).rejects.toThrow(
      'refresh unavailable',
    )
    await expect(
      service.submitReport({ targetType: 'place', targetId: 'place-1', reason: 'Incorrect' }),
    ).rejects.toThrow('refresh unavailable')

    expect(tokenProvider).toHaveBeenCalledTimes(3)
    expect(fetchMock).not.toHaveBeenCalled()
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
