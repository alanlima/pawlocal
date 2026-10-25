import { afterEach, describe, expect, it, vi } from 'vitest'
import { validateReleaseConfig } from './releaseConfig'

function setReleaseConfig(overrides: Record<string, string> = {}) {
  vi.stubEnv('VITE_RELEASE_ENV', 'development')
  vi.stubEnv('VITE_TELEMETRY_ENABLED', 'false')
  vi.stubEnv('VITE_USE_MOCK_BACKEND', 'false')
  vi.stubEnv('VITE_API_BASE_URL', 'https://pawlocal-dev.example.test/api/v1')
  vi.stubEnv('VITE_COGNITO_DOMAIN', 'https://pawlocal-test.auth.ap-southeast-2.amazoncognito.com')
  vi.stubEnv('VITE_COGNITO_CLIENT_ID', 'public-app-client')
  vi.stubEnv('VITE_COGNITO_REDIRECT_URI', 'https://pawlocal-dev.example.test/')
  vi.stubEnv('VITE_COGNITO_LOGOUT_URI', 'https://pawlocal-dev.example.test/')
  for (const [name, value] of Object.entries(overrides)) vi.stubEnv(name, value)
  vi.stubGlobal('location', {
    origin:
      overrides.VITE_RELEASE_ENV === 'production'
        ? 'https://pawlocal.example.test'
        : 'https://pawlocal-dev.example.test',
  })
}

afterEach(() => {
  vi.unstubAllEnvs()
  vi.unstubAllGlobals()
})

describe('cloud release configuration', () => {
  it('allows complete dev or prod configs only with HTTP mode and telemetry off', () => {
    setReleaseConfig()
    expect(() => validateReleaseConfig()).not.toThrow()
    setReleaseConfig({
      VITE_RELEASE_ENV: 'production',
      VITE_API_BASE_URL: 'https://pawlocal.example.test/api/v1',
      VITE_COGNITO_REDIRECT_URI: 'https://pawlocal.example.test/auth/callback',
      VITE_COGNITO_LOGOUT_URI: 'https://pawlocal.example.test/',
    })
    expect(() => validateReleaseConfig()).not.toThrow()
  })

  it('requires a verified collector for enabled telemetry', () => {
    setReleaseConfig({ VITE_TELEMETRY_ENABLED: 'true' })
    expect(() => validateReleaseConfig()).toThrow(
      'Enabled cloud telemetry requires a verified public Faro collector URL',
    )
  })

  it('accepts enabled telemetry only with a public collector binding', () => {
    setReleaseConfig({
      VITE_TELEMETRY_ENABLED: 'true',
      VITE_FARO_COLLECTOR_URL: 'https://faro.grafana.net/collect/public-key',
    })
    expect(() => validateReleaseConfig()).not.toThrow()
    for (const value of [
      'https://user:private@faro.grafana.net/collect/public-key',
      'https://faro.grafana.net/collect/key?token=private',
      'https://foreign.example.test/collect/key',
    ]) {
      setReleaseConfig({ VITE_TELEMETRY_ENABLED: 'true', VITE_FARO_COLLECTOR_URL: value })
      expect(() => validateReleaseConfig()).toThrow()
    }
  })

  it('does not allow the mock service in a cloud build', () => {
    setReleaseConfig({ VITE_USE_MOCK_BACKEND: 'true' })
    expect(() => validateReleaseConfig()).toThrow(
      'Cloud release builds require VITE_USE_MOCK_BACKEND=false',
    )
  })

  it('requires an explicit API endpoint and complete public Cognito settings', () => {
    setReleaseConfig({ VITE_API_BASE_URL: '' })
    expect(() => validateReleaseConfig()).toThrow('require an explicit VITE_API_BASE_URL')

    setReleaseConfig({ VITE_COGNITO_CLIENT_ID: '' })
    expect(() => validateReleaseConfig()).toThrow(
      'require complete public Cognito client configuration',
    )
  })

  it('requires secure API URLs', () => {
    setReleaseConfig({ VITE_API_BASE_URL: 'http://api.example.test/api/v1' })
    expect(() => validateReleaseConfig()).toThrow('Cloud release API endpoints must use HTTPS')
  })

  it('requires the matching absolute frontend-origin API URL in cloud builds', () => {
    setReleaseConfig({ VITE_API_BASE_URL: '/api/v1' })
    expect(() => validateReleaseConfig()).toThrow(
      'Cloud release VITE_API_BASE_URL must be an absolute HTTPS URL',
    )

    setReleaseConfig({
      VITE_RELEASE_ENV: 'production',
      VITE_API_BASE_URL: 'https://pawlocal.example.test/api/v1',
      VITE_COGNITO_REDIRECT_URI: 'https://pawlocal.example.test/auth/callback',
      VITE_COGNITO_LOGOUT_URI: 'https://pawlocal.example.test/',
    })
    expect(() => validateReleaseConfig()).not.toThrow()

    setReleaseConfig({ VITE_API_BASE_URL: 'https://pawlocal.example.test/api/v1' })
    expect(() => validateReleaseConfig()).toThrow(
      'must use the pawlocal-dev.<domain> frontend origin',
    )
  })
  it('rejects foreign or decorated API URLs and legacy API hosts', () => {
    for (const value of [
      'https://pawlocal-dev.foreign.test/api/v1',
      'https://pawlocal-dev.example.test:8443/api/v1',
      'https://user:password@pawlocal-dev.example.test/api/v1',
      'https://pawlocal-dev.example.test/api/v1?query=value',
      'https://pawlocal-dev.example.test/api/v1#fragment',
      'https://pawlocal-dev.example.test/api/v2',
      'https://api-dev.example.test/api/v1',
    ]) {
      setReleaseConfig({ VITE_API_BASE_URL: value })
      expect(() => validateReleaseConfig()).toThrow()
    }
  })

  it('requires auth callback and logout URLs to match the API frontend origin', () => {
    for (const setting of ['VITE_COGNITO_REDIRECT_URI', 'VITE_COGNITO_LOGOUT_URI']) {
      for (const origin of ['https://pawlocal.example.test', 'https://pawlocal-dev.foreign.test']) {
        setReleaseConfig({ [setting]: `${origin}/` })
        expect(() => validateReleaseConfig()).toThrow('same frontend origin')
      }
    }
  })
  it('rejects a release served from a foreign or cross-environment frontend origin', () => {
    for (const origin of ['https://pawlocal.example.test', 'https://foreign.example.test']) {
      setReleaseConfig()
      vi.stubGlobal('location', { origin })
      expect(() => validateReleaseConfig()).toThrow('must use the serving frontend origin')
    }
  })

  it('leaves local development without release configuration available', () => {
    vi.stubEnv('VITE_RELEASE_ENV', '')
    vi.stubEnv('PROD', false)
    vi.stubGlobal('location', { origin: 'http://localhost:5173' })
    expect(() => validateReleaseConfig()).not.toThrow()
  })
})
