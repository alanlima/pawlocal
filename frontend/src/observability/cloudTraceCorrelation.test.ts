// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest'
import { trace, type Span } from '@opentelemetry/api'
import { VERSION } from '@grafana/faro-web-sdk'

afterEach(() => {
  vi.unstubAllEnvs()
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe('hosted trace correlation', () => {
  it('exports hosted journey parents matching API traceparent without private request data', async () => {
    trace.disable()
    vi.resetModules()
    vi.spyOn(Math, 'random').mockReturnValue(0.01)
    vi.stubEnv('VITE_RELEASE_ENV', 'development')
    vi.stubEnv('VITE_TELEMETRY_ENABLED', 'true')
    vi.stubEnv('VITE_API_BASE_URL', 'https://pawlocal-dev.example.test/api/v1')
    vi.stubGlobal('location', new URL('https://pawlocal-dev.example.test/'))
    vi.stubEnv('VITE_FARO_COLLECTOR_URL', 'https://faro-collector.grafana.net/collect/public-key')
    vi.stubEnv('VITE_APP_COMMIT', 'a'.repeat(40))
    const apiHeaders: Headers[] = []
    const collectorBodies: string[] = []
    const collectorHeaders: Headers[] = []
    const localWrites = vi.spyOn(localStorage, 'setItem')
    const sessionWrites = vi.spyOn(sessionStorage, 'setItem')
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init: RequestInit) => {
        if (url.startsWith('https://pawlocal-dev.example.test/')) {
          apiHeaders.push(new Headers(init.headers))
          return new Response(
            JSON.stringify(
              url.includes('?')
                ? { items: [], total: 0 }
                : { id: 'private-place-id', name: 'private-place-name', category: 'dog_park' },
            ),
            { status: 200 },
          )
        }
        collectorHeaders.push(new Headers(init.headers))
        expect(init.credentials).toBe('omit')
        collectorBodies.push(String(init.body))
        return new Response('{}', { status: 200 })
      }),
    )
    const telemetry = await import('./telemetry')
    const { HttpPlaceService } = await import('../services/HttpPlaceService')
    const { observePlaceService } = await import('../services/observedPlaceService')
    const service = observePlaceService(
      new HttpPlaceService('https://pawlocal-dev.example.test/api/v1'),
    )
    try {
      await service.listPlaces({ q: 'private-search-sentinel' })
      await service.getPlace('private-place-id')
      await telemetry.flushTelemetry()
      await new Promise((resolve) => setTimeout(resolve, 1200))
      type WireSpan = { name: string; traceId: string; spanId: string; parentSpanId?: string }
      const resources = collectorBodies.flatMap(
        (body) => JSON.parse(body).traces?.resourceSpans ?? [],
      )
      const spans: WireSpan[] = resources.flatMap((resource) =>
        resource.scopeSpans.flatMap((scope: { spans: WireSpan[] }) => scope.spans),
      )
      const search = spans.find((span) => span.name === 'pawlocal.search')!
      const detail = spans.find((span) => span.name === 'pawlocal.detail')!
      expect(search).toBeDefined()
      expect(detail).toBeDefined()
      expect(search.traceId).toMatch(/^[a-f0-9]{32}$/)
      expect(search.spanId).toMatch(/^[a-f0-9]{16}$/)
      expect(detail.traceId).toBe(search.traceId)
      expect(detail.parentSpanId).toBe(search.spanId)
      expect(apiHeaders).toHaveLength(2)
      expect(apiHeaders[0].get('traceparent')).toBe(`00-${search.traceId}-${search.spanId}-01`)
      expect(apiHeaders[1].get('traceparent')).toBe(`00-${detail.traceId}-${detail.spanId}-01`)
      expect(apiHeaders.every((headers) => !headers.has('tracestate'))).toBe(true)
      for (const resource of resources) {
        expect(resource.resource.attributes).toEqual(
          expect.arrayContaining([
            { key: 'service.name', value: { stringValue: 'pawlocal-frontend' } },
            { key: 'deployment.environment.name', value: { stringValue: 'development' } },
            { key: 'service.version', value: { stringValue: 'a'.repeat(40) } },
          ]),
        )
      }
      for (const privateValue of [
        'private-search-sentinel',
        'private-place-id',
        'private-place-name',
        'https://pawlocal-dev.example.test',
      ])
        expect(collectorBodies.join('')).not.toContain(privateValue)
      for (const body of collectorBodies) {
        const meta = JSON.parse(body).meta
        expect(Object.keys(meta).sort()).toEqual(['app', 'sdk'])
        expect(meta.sdk).toEqual({ name: '@grafana/faro-web-sdk', version: VERSION })
      }
      const firstTransportId = collectorHeaders[0].get('x-faro-session-id')
      expect(firstTransportId).toMatch(
        /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i,
      )
      const { cloudOutcome } = await import('./cloudTelemetry')
      const unsampled = {
        spanContext: () => ({ traceId: 'b'.repeat(32), spanId: 'c'.repeat(16), traceFlags: 0 }),
      } as Span
      // Logs from unsampled journeys must satisfy the collector protocol too.
      cloudOutcome(unsampled, 'share', 'success')
      await new Promise((resolve) => setTimeout(resolve, 1200))
      expect(collectorHeaders.at(-1)?.get('x-faro-session-id')).toBe(firstTransportId)
      const afterExpiry = Date.now() + 15 * 60 * 1000
      vi.spyOn(Date, 'now').mockReturnValue(afterExpiry)
      cloudOutcome(unsampled, 'share', 'empty')
      await new Promise((resolve) => setTimeout(resolve, 1200))
      expect(collectorHeaders.at(-1)?.get('x-faro-session-id')).not.toBe(firstTransportId)
      expect(collectorBodies.at(-1)).not.toContain('"traces"')
      expect(localWrites).not.toHaveBeenCalled()
      expect(sessionWrites).not.toHaveBeenCalled()
    } finally {
      await telemetry.shutdownTelemetry()
      trace.disable()
    }
  }, 10000)
})
