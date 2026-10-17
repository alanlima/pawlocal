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
    const {
      flushTelemetry,
      injectCurrentTraceContext,
      recordDemoAction,
      recordOperation,
      shutdownTelemetry,
    } = await import('./telemetry')
    const results = await recordOperation(
      'search',
      async () => [{ id: 'private-place-name', query: 'private search text' }],
      (items) => (items.length ? 'success' : 'empty'),
    )
    await recordOperation('detail', async () => ({ id: 'private-place-name' }))
    await recordOperation('contribution', async () => ({ id: 'private-contribution' }), undefined, {
      kind: 'review',
    })
    recordDemoAction('contribution', 'success', 'review')
    await recordOperation('report', async () => undefined, undefined, { target_type: 'place' })
    recordDemoAction('report', 'success', 'place')
    await expect(
      recordOperation('search', async () => {
        throw new DOMException('Aborted', 'AbortError')
      }),
    ).rejects.toMatchObject({ name: 'AbortError' })
    const traceHeaders = injectCurrentTraceContext({})
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
      (resourceSpan: {
        scopeSpans: {
          spans: { name: string; traceId: string; spanId: string; parentSpanId?: string }[]
        }[]
      }) => resourceSpan.scopeSpans.flatMap((scopeSpan) => scopeSpan.spans),
    )
    const searchSpan = spans.find((span: { name: string }) => span.name === 'pawlocal.search')
    const detailSpan = spans.find((span: { name: string }) => span.name === 'pawlocal.detail')
    const contributionSpan = spans.find(
      (span: { name: string }) => span.name === 'pawlocal.contribution',
    )
    const reportSpan = spans.find((span: { name: string }) => span.name === 'pawlocal.report')
    expect(
      spans.filter((span: { name: string }) => span.name === 'pawlocal.contribution'),
    ).toHaveLength(1)
    expect(spans.filter((span: { name: string }) => span.name === 'pawlocal.report')).toHaveLength(
      1,
    )
    const cancelledSpan = spans.find(
      (span: { attributes: { key: string; value: { stringValue: string } }[] }) =>
        span.attributes.some(
          (attribute) =>
            attribute.key === 'pawlocal.outcome' && attribute.value.stringValue === 'cancelled',
        ),
    )
    expect(searchSpan.traceId).toBe(detailSpan.traceId)
    expect(contributionSpan.traceId).toBe(searchSpan.traceId)
    expect(contributionSpan.parentSpanId).toBe(searchSpan.spanId)
    expect(reportSpan.traceId).toBe(searchSpan.traceId)
    expect(reportSpan.parentSpanId).toBe(searchSpan.spanId)
    expect(cancelledSpan.status.code).not.toBe(2)
    expect(posts.join('\n')).toContain('search_cancelled')
    expect(posts.join('\n')).not.toContain('search_error')
    expect(posts.join('\n')).not.toContain('PAWLOCAL_OPERATION_FAILED')
    let allLogBodies = requests
      .filter((request) => request.path.includes('/v1/logs'))
      .map((request) => request.body)
      .join('\n')
    for (let attempt = 0; attempt < 40; attempt += 1) {
      if (
        allLogBodies.includes('contribution_success') &&
        allLogBodies.includes('report_success')
      ) {
        break
      }
      await new Promise((resolve) => setTimeout(resolve, 25))
      allLogBodies = requests
        .filter((request) => request.path.includes('/v1/logs'))
        .map((request) => request.body)
        .join('\n')
    }
    expect(allLogBodies.match(/contribution_success/g)).toHaveLength(1)
    expect(allLogBodies.match(/report_success/g)).toHaveLength(1)
    const metricBody = JSON.parse(
      requests.find((request) => request.path.includes('/v1/metrics'))!.body,
    )
    const metrics = metricBody.resourceMetrics.flatMap(
      (resourceMetric: { scopeMetrics: { metrics: unknown[] }[] }) =>
        resourceMetric.scopeMetrics.flatMap((scopeMetric) => scopeMetric.metrics),
    ) as {
      name: string
      sum?: {
        dataPoints: {
          asDouble?: number
          attributes: { key: string; value: { stringValue: string } }[]
        }[]
      }
    }[]
    const demoActions = metrics.find((metric) => metric.name === 'pawlocal.demo_actions')
    expect(demoActions?.sum?.dataPoints).toHaveLength(2)
    expect(demoActions?.sum?.dataPoints.map((point) => point.asDouble)).toEqual([1, 1])
    expect(
      demoActions?.sum?.dataPoints.map(
        (point) =>
          point.attributes.find((attribute) => attribute.key === 'operation')?.value.stringValue,
      ),
    ).toEqual(['contribution', 'report'])
    expect(traceHeaders.traceparent).toMatch(/^00-[a-f0-9]{32}-[a-f0-9]{16}-01$/)
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
