/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_TELEMETRY_ENABLED?: string
  readonly VITE_FARO_COLLECTOR_URL?: string
  readonly VITE_OTEL_EXPORTER_OTLP_ENDPOINT?: string
  readonly VITE_DEMO_FAULTS?: string
  readonly VITE_USE_MOCK_BACKEND?: string
  readonly VITE_API_BASE_URL?: string
  readonly VITE_API_PROXY_TARGET?: string
  readonly VITE_RELEASE_ENV?: 'development' | 'production'
  readonly VITE_COGNITO_DOMAIN?: string
  readonly VITE_COGNITO_CLIENT_ID?: string
  readonly VITE_COGNITO_REDIRECT_URI?: string
  readonly VITE_COGNITO_LOGOUT_URI?: string
  readonly VITE_COGNITO_SCOPES?: string
  readonly VITE_APP_COMMIT?: string
  readonly VITE_APP_BUILD_TIME?: string
}
