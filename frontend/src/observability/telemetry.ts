import { cloudExporter, cloudOutcome, cloudSampler, stopCloudTelemetry } from './cloudTelemetry'
import {
  context as otelContext,
  metrics,
  SpanStatusCode,
  trace,
  type Attributes,
  type Context,
} from '@opentelemetry/api'
import { W3CTraceContextPropagator } from '@opentelemetry/core'
import { OTLPMetricExporter } from '@opentelemetry/exporter-metrics-otlp-http'
import { OTLPTraceExporter } from '@opentelemetry/exporter-trace-otlp-http'
import { resourceFromAttributes } from '@opentelemetry/resources'
import { MeterProvider, PeriodicExportingMetricReader } from '@opentelemetry/sdk-metrics'
import { BatchSpanProcessor } from '@opentelemetry/sdk-trace-base'
import { WebTracerProvider } from '@opentelemetry/sdk-trace-web'
import type { Span } from '@opentelemetry/api'

const endpoint = import.meta.env.VITE_OTEL_EXPORTER_OTLP_ENDPOINT ?? 'http://localhost:4318'
const isEnabled = () => import.meta.env.VITE_TELEMETRY_ENABLED === 'true'

let initialized = false
let traceProvider: WebTracerProvider | undefined
let meterProvider: MeterProvider | undefined
let discoveryContext: Context | undefined
let outcomeCounter: ReturnType<ReturnType<typeof metrics.getMeter>['createCounter']> | undefined
let actionCounter: ReturnType<ReturnType<typeof metrics.getMeter>['createCounter']> | undefined
let searchDuration: ReturnType<ReturnType<typeof metrics.getMeter>['createHistogram']> | undefined
let detailDuration: ReturnType<ReturnType<typeof metrics.getMeter>['createHistogram']> | undefined

export function initializeTelemetry() {
  if (!isEnabled() || initialized) return
  initialized = true

  try {
    const hosted = Boolean(import.meta.env.VITE_RELEASE_ENV)
    const resource = resourceFromAttributes({ 'service.name': 'pawlocal-frontend' })
    const provider = new WebTracerProvider({
      resource,
      ...(hosted ? { sampler: cloudSampler() } : {}),
      spanProcessors: [
        new BatchSpanProcessor(
          hosted
            ? cloudExporter()
            : new OTLPTraceExporter({ url: `${endpoint}/v1/traces`, headers: {} }),
          {
            maxQueueSize: 100,
            maxExportBatchSize: 20,
            scheduledDelayMillis: 1000,
            exportTimeoutMillis: 2500,
          },
        ),
      ],
    })
    traceProvider = provider
    trace.setGlobalTracerProvider(provider)
    if (hosted) return
    meterProvider = new MeterProvider({
      resource,
      readers: [
        new PeriodicExportingMetricReader({
          exporter: new OTLPMetricExporter({ url: `${endpoint}/v1/metrics`, headers: {} }),
          exportIntervalMillis: 5000,
        }),
      ],
    })
    metrics.setGlobalMeterProvider(meterProvider)

    const meter = metrics.getMeter('pawlocal.frontend')
    outcomeCounter = meter.createCounter('pawlocal.operations', {
      description: 'Frontend journey outcomes, with bounded operation and outcome values.',
    })
    actionCounter = meter.createCounter('pawlocal.demo_actions', {
      description: 'Demo contribution and report outcomes.',
    })
    searchDuration = meter.createHistogram('pawlocal.search.duration', {
      unit: 'ms',
      description: 'Mock-backed search duration.',
    })
    detailDuration = meter.createHistogram('pawlocal.detail.duration', {
      unit: 'ms',
      description: 'Mock-backed place detail duration.',
    })
  } catch {
    // Initialization runs before React mounts; even partial SDK setup must fail open.
    const partialTrace = traceProvider
    const partialMeter = meterProvider
    traceProvider = undefined
    meterProvider = undefined
    outcomeCounter = actionCounter = undefined
    searchDuration = detailDuration = undefined
    safelyRecord(() => {
      if (partialTrace) {
        trace.disable()
        void partialTrace.shutdown().catch(() => undefined)
      }
    })
    safelyRecord(() => {
      if (partialMeter) {
        metrics.disable()
        void partialMeter.shutdown().catch(() => undefined)
      }
    })
    safelyRecord(stopCloudTelemetry)
    initialized = false
  }
}

export async function flushTelemetry() {
  await Promise.all([traceProvider?.forceFlush(), meterProvider?.forceFlush()])
}

export async function shutdownTelemetry() {
  await Promise.all([traceProvider?.shutdown(), meterProvider?.shutdown()])
  stopCloudTelemetry()
}

export type Operation = 'search' | 'detail' | 'share' | 'favourite' | 'contribution' | 'report'
export type Outcome = 'success' | 'empty' | 'not_found' | 'error' | 'cancelled'

function boundedAttributes(attributes: Attributes = {}): Attributes {
  const allowed: Record<string, Set<string>> = {
    category: new Set(['dog_park', 'beach', 'walk', 'hiking_area', 'cafe']),
    kind: new Set(['review', 'location_suggestion', 'tip', 'correction']),
    target_type: new Set(['place', 'contribution']),
  }
  return Object.fromEntries(
    Object.entries(attributes).filter(
      ([key, value]) => typeof value === 'string' && allowed[key]?.has(value),
    ),
  )
}

export async function recordOperation<T>(
  operation: Operation,
  run: (span: Span | undefined) => Promise<T>,
  getOutcome: (value: T) => Outcome = () => 'success',
  attributes: Attributes = {},
): Promise<T> {
  if (!isEnabled()) return run(undefined)
  try {
    initializeTelemetry()
  } catch {
    return run(undefined)
  }
  const safeAttributes = boundedAttributes(attributes)
  let span: Span
  try {
    span = trace.getTracer('pawlocal.frontend').startSpan(
      `pawlocal.${operation}`,
      {
        attributes: { 'pawlocal.operation': operation, ...safeAttributes },
      },
      operation === 'detail' ||
        operation === 'share' ||
        operation === 'favourite' ||
        operation === 'contribution' ||
        operation === 'report'
        ? (discoveryContext ?? otelContext.active())
        : otelContext.active(),
    )
    if (operation === 'search') discoveryContext = trace.setSpan(otelContext.active(), span)
  } catch {
    return run(undefined)
  }
  const started = performance.now()
  try {
    const value = await run(span)
    const outcome = getOutcome(value)
    safelyRecord(() => {
      span.setAttribute('pawlocal.outcome', outcome)
      outcomeCounter?.add(1, { operation, outcome, ...safeAttributes })
      if (operation === 'search')
        searchDuration?.record(performance.now() - started, safeAttributes)
      if (operation === 'detail')
        detailDuration?.record(performance.now() - started, safeAttributes)
      writeSafeLog(span, operation, outcome, undefined, performance.now() - started)
    })
    return value
  } catch (error) {
    if (isAbortError(error)) {
      safelyRecord(() => {
        span.setAttribute('pawlocal.outcome', 'cancelled')
        writeSafeLog(span, operation, 'cancelled', undefined, performance.now() - started)
      })
      throw error
    }
    safelyRecord(() => {
      span.setStatus({ code: SpanStatusCode.ERROR, message: 'operation_failed' })
      span.setAttribute('pawlocal.outcome', 'error')
      outcomeCounter?.add(1, { operation, outcome: 'error', ...safeAttributes })
      if (operation === 'search')
        searchDuration?.record(performance.now() - started, safeAttributes)
      if (operation === 'detail')
        detailDuration?.record(performance.now() - started, safeAttributes)
      writeSafeLog(
        span,
        operation,
        'error',
        'PAWLOCAL_OPERATION_FAILED',
        performance.now() - started,
      )
    })
    throw error
  } finally {
    safelyRecord(() => span.end())
  }
}

function safelyRecord(record: () => void) {
  try {
    record()
  } catch {
    /* SDK failures cannot change the visitor operation. */
  }
}

function isAbortError(error: unknown): boolean {
  return error instanceof Error && error.name === 'AbortError'
}

export function recordDemoAction(
  action: 'contribution' | 'report',
  outcome: Outcome,
  kind?: string,
) {
  if (!isEnabled()) return
  safelyRecord(() => {
    initializeTelemetry()
    const attrs = boundedAttributes({ kind })
    actionCounter?.add(1, { operation: action, outcome, ...attrs })
  })
}

export function traceContextForSpan(span: Span | undefined) {
  if (!isEnabled() || !span) return undefined
  try {
    const headers: Record<string, string> = {}
    new W3CTraceContextPropagator().inject(trace.setSpan(otelContext.active(), span), headers, {
      set: (carrier, key, value) => {
        carrier[key] = String(value)
      },
    })
    return {
      traceparent: headers.traceparent,
      ...(headers.tracestate ? { tracestate: headers.tracestate } : {}),
    }
  } catch {
    return undefined
  }
}

function writeSafeLog(
  span: Span,
  operation: Operation,
  outcome: Outcome,
  errorCode?: string,
  durationMs?: number,
) {
  if (import.meta.env.VITE_RELEASE_ENV) {
    try {
      cloudOutcome(span, operation, outcome, durationMs)
    } catch {
      /* Export cannot change the visitor operation. */
    }
    return
  }
  const context = span.spanContext()
  const body = {
    resourceLogs: [
      {
        resource: {
          attributes: [{ key: 'service.name', value: { stringValue: 'pawlocal-frontend' } }],
        },
        scopeLogs: [
          {
            scope: { name: 'pawlocal.frontend' },
            logRecords: [
              {
                timeUnixNano: String(Date.now() * 1_000_000),
                severityNumber: errorCode ? 17 : 9,
                severityText: errorCode ? 'ERROR' : 'INFO',
                body: {
                  stringValue: JSON.stringify({
                    event: errorCode ?? `${operation}_${outcome}`,
                    traceId: context.traceId,
                    spanId: context.spanId,
                    operation,
                    outcome,
                    ...(errorCode ? { errorCode } : {}),
                  }),
                },
                traceId: context.traceId,
                spanId: context.spanId,
                attributes: [
                  { key: 'pawlocal.operation', value: { stringValue: operation } },
                  { key: 'pawlocal.outcome', value: { stringValue: outcome } },
                  ...(errorCode ? [{ key: 'error.code', value: { stringValue: errorCode } }] : []),
                ],
              },
            ],
          },
        ],
      },
    ],
  }
  void fetch(`${endpoint}/v1/logs`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    keepalive: true,
  }).catch(() => undefined)
}
