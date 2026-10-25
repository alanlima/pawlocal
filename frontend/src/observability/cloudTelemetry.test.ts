// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest'
import { SpanStatusCode, trace, type Tracer } from '@opentelemetry/api'

afterEach(() => {
  vi.unstubAllEnvs()
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe('hosted Faro privacy and fail-open behavior', () => {
  it('exports only safe manual signals, without browser/session/user metadata', async () => {
    vi.resetModules()
    vi.spyOn(Math, 'random').mockReturnValue(0.01)
    vi.stubEnv('VITE_RELEASE_ENV', 'development')
    vi.stubEnv('VITE_TELEMETRY_ENABLED', 'true')
    vi.stubEnv('VITE_FARO_COLLECTOR_URL', 'https://faro-collector.grafana.net/collect/public-key')
    vi.stubEnv('VITE_APP_COMMIT', 'a'.repeat(40))
    window.history.replaceState({}, '', '/?q=private-search-sentinel')
    localStorage.setItem('auth-token', 'private-auth-sentinel')
    const bodies: string[] = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (_url, init: RequestInit) => {
        bodies.push(String(init.body))
        return new Response('{}', { status: 200 })
      }),
    )
    const telemetry = await import('./telemetry')
    expect(
      await telemetry.recordOperation('search', async (span) => {
        span?.setAttribute('db.query.text', 'private-sql-sentinel')
        span?.setAttribute('category', 'private-category-sentinel')
        span?.addEvent('private-event-sentinel')
        span?.setStatus({ code: SpanStatusCode.ERROR, message: 'private-error-sentinel' })
        return 'visitor-data-remains-in-app'
      }),
    ).toBe('visitor-data-remains-in-app')
    await telemetry.flushTelemetry()
    await new Promise((resolve) => setTimeout(resolve, 1200))
    await telemetry.shutdownTelemetry()
    expect(bodies.length).toBeGreaterThan(0)
    const exported = bodies.join('')
    for (const secret of [
      'private-search-sentinel',
      'private-auth-sentinel',
      'private-sql-sentinel',
      'private-event-sentinel',
      'private-error-sentinel',
      'private-category-sentinel',
      'visitor-data-remains-in-app',
    ])
      expect(exported).not.toContain(secret)
    expect(exported).toContain('pawlocal.search')
    expect(exported).toContain('journey_completed')
    expect(exported).toContain('duration_ms')
    expect(
      bodies
        .map((body) => JSON.parse(body).meta)
        .every((meta) => Object.keys(meta).every((key) => key === 'app' || key === 'sdk')),
    ).toBe(true)
  })

  it('keeps disabled and invalid telemetry operations usable', async () => {
    vi.resetModules()
    vi.stubEnv('VITE_RELEASE_ENV', 'development')
    vi.stubEnv('VITE_TELEMETRY_ENABLED', 'false')
    const fetch = vi.fn()
    vi.stubGlobal('fetch', fetch)
    const telemetry = await import('./telemetry')
    expect(await telemetry.recordOperation('search', async () => 42)).toBe(42)
    expect(fetch).not.toHaveBeenCalled()
    vi.stubEnv('VITE_TELEMETRY_ENABLED', 'true')
    vi.stubEnv('VITE_FARO_COLLECTOR_URL', 'https://user:private@gateway.grafana.net/collect/public')
    expect(await telemetry.recordOperation('search', async () => 43)).toBe(43)
    expect(fetch).not.toHaveBeenCalled()
  })

  it('does not reject the user operation when the collector is unavailable', async () => {
    vi.resetModules()
    vi.stubEnv('VITE_RELEASE_ENV', 'development')
    vi.stubEnv('VITE_TELEMETRY_ENABLED', 'true')
    vi.stubEnv('VITE_FARO_COLLECTOR_URL', 'https://faro-collector.grafana.net/collect/public-key')
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => {
        throw new Error('collector unavailable')
      }),
    )
    const telemetry = await import('./telemetry')
    expect(await telemetry.recordOperation('detail', async () => 'usable')).toBe('usable')
    await telemetry.flushTelemetry()
    await new Promise((resolve) => setTimeout(resolve, 1200))
    await telemetry.shutdownTelemetry()
  })
  it('keeps the business result and original failure when instrumentation throws', async () => {
    vi.resetModules()
    vi.stubEnv('VITE_RELEASE_ENV', 'development')
    vi.stubEnv('VITE_TELEMETRY_ENABLED', 'true')
    vi.stubEnv('VITE_FARO_COLLECTOR_URL', 'https://faro-collector.grafana.net/collect/public-key')
    const fail = () => {
      throw new Error('synthetic SDK failure')
    }
    vi.spyOn(trace, 'getTracer').mockReturnValue({
      startSpan: () => ({ setAttribute: fail, setStatus: fail, spanContext: fail, end: fail }),
    } as unknown as Tracer)
    const telemetry = await import('./telemetry')
    expect(await telemetry.recordOperation('search', async () => 42)).toBe(42)
    const original = new Error('business failure')
    await expect(
      telemetry.recordOperation('detail', async () => {
        throw original
      }),
    ).rejects.toBe(original)
    await telemetry.shutdownTelemetry()
  })
})
