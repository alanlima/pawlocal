import { afterEach, describe, expect, it, vi } from 'vitest'

describe('development search fault controls', () => {
  afterEach(() => {
    window.history.replaceState({}, '', '/')
    vi.unstubAllEnvs()
  })

  it('injects a deterministic failure only when dev faults are enabled', async () => {
    vi.stubEnv('VITE_DEMO_FAULTS', 'true')
    vi.resetModules()
    window.history.replaceState({}, '', '/?demoFault=search-error')
    const { MockPlaceService } = await import('./MockPlaceService')
    await expect(new MockPlaceService().listPlaces({ q: '' })).rejects.toThrow(
      'synthetic_search_failure',
    )
  })

  it('uses normal mock behavior when dev faults are disabled', async () => {
    vi.stubEnv('VITE_DEMO_FAULTS', 'false')
    vi.resetModules()
    window.history.replaceState({}, '', '/?demoFault=search-error')
    const { MockPlaceService } = await import('./MockPlaceService')
    await expect(new MockPlaceService().listPlaces({ q: '' })).resolves.toBeInstanceOf(Array)
  })
})
