// @vitest-environment node
import { afterEach, describe, expect, it, vi } from 'vitest'
import { createServer, type Server } from 'node:http'

let server: Server | undefined
let requests: { path: string; body: string }[] = []

afterEach(() => {
  server?.close()
  server = undefined
  requests = []
  vi.restoreAllMocks()
  vi.unstubAllEnvs()
})

describe('frontend telemetry', () => {
  it('exports spans, metrics, and safe outcome logs without user input', async () => {
    vi.stubEnv('VITE_TELEMETRY_ENABLED', 'true')
    requests = []
    server = createServer((request, response) => {
      let body = ''
      request.on('data', (chunk: Buffer) => (body += chunk.toString()))
      request.on('end', () => {
        requests.push({ path: request.url ?? '', body })
        response.writeHead(200, { 'content-type': 'application/json' })
        response.end('{"partialSuccess":{}}')
      })
    })
    await new Promise<void>((resolve) => server?.listen(0, '127.0.0.1', resolve))
    const address = server.address()
    if (!address || typeof address === 'string') throw new Error('test server failed to start')
    vi.stubEnv('VITE_OTEL_EXPORTER_OTLP_ENDPOINT', `http://127.0.0.1:${address.port}`)
    vi.resetModules()
    const { flushTelemetry, recordOperation, shutdownTelemetry } = await import('./telemetry')
    const results = await recordOperation(
      'search',
      async () => [{ id: 'private-place-name', query: 'private search text' }],
      (items) => (items.length ? 'success' : 'empty'),
    )
    await recordOperation('detail', async () => ({ id: 'private-place-name' }))
    await flushTelemetry()
    await new Promise((resolve) => setTimeout(resolve, 30))
    await shutdownTelemetry()

    expect(results).toHaveLength(1)
    const posts = requests.map((request) => request.body)
    expect(requests.some((request) => request.path.includes('/v1/traces'))).toBe(true)
    expect(requests.some((request) => request.path.includes('/v1/metrics'))).toBe(true)
    expect(posts.some((body) => body.includes('search_success'))).toBe(true)
    expect(posts.join('\n')).not.toContain('private search text')
    expect(posts.join('\n')).not.toContain('private-place-name')
    const traceBody = JSON.parse(
      requests.find((request) => request.path.includes('/v1/traces'))!.body,
    )
    const spans = traceBody.resourceSpans.flatMap(
      (resourceSpan: { scopeSpans: { spans: { name: string; traceId: string }[] }[] }) =>
        resourceSpan.scopeSpans.flatMap((scopeSpan) => scopeSpan.spans),
    )
    const searchSpan = spans.find((span: { name: string }) => span.name === 'pawlocal.search')
    const detailSpan = spans.find((span: { name: string }) => span.name === 'pawlocal.detail')
    expect(searchSpan.traceId).toBe(detailSpan.traceId)
  }, 15000)

  it('keeps the journey usable and sends nothing when telemetry is disabled', async () => {
    vi.stubEnv('VITE_TELEMETRY_ENABLED', 'false')
    vi.resetModules()
    const { recordOperation } = await import('./telemetry')
    const fetchMock = vi.spyOn(globalThis, 'fetch')
    await expect(recordOperation('search', async () => ['place'])).resolves.toEqual(['place'])
    expect(fetchMock).not.toHaveBeenCalled()
  })
})
