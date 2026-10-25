import {
  FetchTransport,
  initializeFaro,
  TransportItemType,
  VERSION,
  type Faro,
  type TransportItem,
} from '@grafana/faro-web-sdk'
import { FaroTraceExporter } from '@grafana/faro-web-tracing'
import { resourceFromAttributes } from '@opentelemetry/resources'
import {
  ParentBasedSampler,
  TraceIdRatioBasedSampler,
  type ReadableSpan,
  type SpanExporter,
} from '@opentelemetry/sdk-trace-base'
import type { Span } from '@opentelemetry/api'

let instance: Faro | undefined
const operations = new Set(['search', 'detail', 'share', 'favourite', 'contribution', 'report'])
const outcomes = new Set(['success', 'empty', 'not_found', 'error', 'cancelled'])
const values: Record<string, Set<string>> = {
  'pawlocal.operation': operations,
  'pawlocal.outcome': outcomes,
  category: new Set(['dog_park', 'beach', 'walk', 'hiking_area', 'cafe']),
  kind: new Set(['review', 'location_suggestion', 'tip', 'correction']),
  target_type: new Set(['place', 'contribution']),
}

export function cloudSampler() {
  return new ParentBasedSampler({ root: new TraceIdRatioBasedSampler(0.1) })
}

export function collectorUrl(value: string | undefined) {
  const url = new URL(value ?? '')
  if (
    url.protocol !== 'https:' ||
    !url.hostname.endsWith('.grafana.net') ||
    url.username ||
    url.password ||
    url.search ||
    url.hash ||
    url.port ||
    !/^\/collect\/[A-Za-z0-9_-]+$/.test(url.pathname)
  ) {
    throw new Error('Hosted Faro requires an approved HTTPS public collector URL')
  }
  return url.href
}

export function sanitizeCloudItem(item: TransportItem): TransportItem | null {
  if (
    ![TransportItemType.TRACE, TransportItemType.LOG, TransportItemType.MEASUREMENT].includes(
      item.type,
    )
  )
    return null
  // Only application identity and the static SDK identity required by hosted ingestion.
  return {
    ...item,
    meta: {
      app: {
        name: 'pawlocal-frontend',
        environment: import.meta.env.VITE_RELEASE_ENV,
        version: /^[0-9a-f]{40}$/.test(import.meta.env.VITE_APP_COMMIT ?? '')
          ? import.meta.env.VITE_APP_COMMIT
          : 'unknown',
      },
      sdk: { name: '@grafana/faro-web-sdk', version: VERSION },
    },
  }
}

export function cloudExporter(): SpanExporter {
  const url = collectorUrl(import.meta.env.VITE_FARO_COLLECTOR_URL)
  // The hosted collector requires this protocol header even with session capture disabled.
  // Keep it in memory only and rotate on send; no visitor identity or browser storage.
  let transportId: string | undefined
  let transportIdExpiresAt = 0
  const collectorTransportId = () => {
    const now = Date.now()
    if (!transportId || now >= transportIdExpiresAt) {
      transportId = crypto.randomUUID()
      transportIdExpiresAt = now + 15 * 60 * 1000
    }
    return transportId
  }
  instance = initializeFaro({
    app: { name: 'pawlocal-frontend', environment: import.meta.env.VITE_RELEASE_ENV },
    instrumentations: [],
    metas: [],
    sessionTracking: { enabled: false, persistent: false },
    trackGeolocation: false,
    trackResources: false,
    preventGlobalExposure: true,
    transports: [
      new FetchTransport({
        url,
        bufferSize: 100,
        concurrency: 1,
        requestTimeoutMs: 2000,
        retry: { maxAttempts: 1 },
        requestOptions: {
          credentials: 'omit',
          headers: { 'X-Faro-Session-Id': collectorTransportId },
        },
      }),
    ],
    batching: { enabled: true, itemLimit: 20, sendTimeout: 1000 },
    beforeSend: sanitizeCloudItem,
  })
  if (!instance) throw new Error('Faro initialization unavailable')
  const exporter = new FaroTraceExporter({ api: instance.api })
  const resource = resourceFromAttributes({
    'service.name': 'pawlocal-frontend',
    'deployment.environment.name': import.meta.env.VITE_RELEASE_ENV ?? 'unknown',
    'service.version': /^[0-9a-f]{40}$/.test(import.meta.env.VITE_APP_COMMIT ?? '')
      ? import.meta.env.VITE_APP_COMMIT
      : 'unknown',
  })
  return {
    export(spans, callback) {
      const safe = spans
        .filter((span) => operations.has(span.name.replace(/^pawlocal\./, '')))
        .map(
          (span) =>
            ({
              ...span,
              spanContext: () => span.spanContext(),
              resource,
              events: [],
              links: [],
              attributes: Object.fromEntries(
                Object.entries(span.attributes).filter(
                  ([key, value]) => typeof value === 'string' && values[key]?.has(value),
                ),
              ),
              status: { code: span.status.code },
            }) as ReadableSpan,
        )
      exporter.export(safe, callback)
    },
    shutdown: () => {
      transportId = undefined
      transportIdExpiresAt = 0
      return exporter.shutdown()
    },
  }
}

export function cloudOutcome(span: Span, operation: string, outcome: string, durationMs?: number) {
  if (!instance || !operations.has(operation) || !outcomes.has(outcome)) return
  const context = { operation, outcome }
  const spanContext = span.spanContext()
  instance.api.pushLog(['journey_completed'], { context, spanContext })
  if (durationMs !== undefined)
    instance.api.pushMeasurement(
      { type: 'pawlocal.journey', values: { duration_ms: durationMs } },
      { context, spanContext },
    )
}

export function stopCloudTelemetry() {
  instance?.pause()
  instance = undefined
}
