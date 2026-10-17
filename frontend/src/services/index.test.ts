import { afterEach, describe, expect, it, vi } from 'vitest'

vi.mock('./observedPlaceService', () => ({
  observePlaceService: (service: unknown) => service,
}))

describe('place service factory', () => {
  afterEach(() => {
    vi.unstubAllEnvs()
    vi.resetModules()
  })

  it('uses mock only when the mock toggle is explicitly true', async () => {
    vi.stubEnv('VITE_USE_MOCK_BACKEND', 'true')
    vi.stubEnv('VITE_API_BASE_URL', '/api/v1')
    vi.resetModules()

    const { placeService } = await import('./index')

    expect(placeService.constructor.name).toBe('MockPlaceService')
  })

  it.each(['false', undefined])('uses HTTP when mock toggle is %s', async (value) => {
    vi.stubEnv('VITE_USE_MOCK_BACKEND', value)
    vi.stubEnv('VITE_API_BASE_URL', '/api/v1')
    vi.resetModules()

    const { placeService } = await import('./index')

    expect(placeService.constructor.name).toBe('HttpPlaceService')
  })

  it('defaults the HTTP adapter to the same-origin API route', async () => {
    vi.stubEnv('VITE_USE_MOCK_BACKEND', undefined)
    vi.stubEnv('VITE_API_BASE_URL', undefined)
    vi.resetModules()

    const { placeService } = await import('./index')

    expect(placeService.constructor.name).toBe('HttpPlaceService')
  })

  it('rejects an invalid mock toggle instead of silently choosing a service', async () => {
    vi.stubEnv('VITE_USE_MOCK_BACKEND', 'yes')
    vi.resetModules()

    await expect(import('./index')).rejects.toThrow(
      'VITE_USE_MOCK_BACKEND must be either "true" or "false"',
    )
  })
})
