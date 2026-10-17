/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_TELEMETRY_ENABLED?: string
  readonly VITE_OTEL_EXPORTER_OTLP_ENDPOINT?: string
  readonly VITE_DEMO_FAULTS?: string
}
