import { afterEach, describe, expect, it, vi } from 'vitest'
import { validateReleaseConfig } from './releaseConfig'

function setReleaseConfig(overrides: Record<string, string> = {}) {
  vi.stubEnv('VITE_RELEASE_ENV', 'development')
  vi.stubEnv('VITE_TELEMETRY_ENABLED', 'false')
  vi.stubEnv('VITE_USE_MOCK_BACKEND', 'false')
  vi.stubEnv('VITE_API_BASE_URL', 'https://api-dev.example.test/api/v1')
  vi.stubEnv('VITE_COGNITO_DOMAIN', 'https://pawlocal-test.auth.ap-southeast-2.amazoncognito.com')
  vi.stubEnv('VITE_COGNITO_CLIENT_ID', 'public-app-client')
  vi.stubEnv('VITE_COGNITO_REDIRECT_URI', 'https://pawlocal-dev.example.test/')
  vi.stubEnv('VITE_COGNITO_LOGOUT_URI', 'https://pawlocal-dev.example.test/')
  for (const [name, value] of Object.entries(overrides)) vi.stubEnv(name, value)
}

afterEach(() => vi.unstubAllEnvs())

describe('cloud release configuration', () => {
  it('allows complete dev or prod configs only with HTTP mode and telemetry off', () => {
    setReleaseConfig({
      VITE_RELEASE_ENV: 'production',
      VITE_API_BASE_URL: 'https://api.example.test/api/v1',
    })
    expect(() => validateReleaseConfig()).not.toThrow()
  })

  it('requires telemetry to be explicitly disabled', () => {
    setReleaseConfig({ VITE_TELEMETRY_ENABLED: 'true' })
    expect(() => validateReleaseConfig()).toThrow(
      'Cloud release builds require VITE_TELEMETRY_ENABLED=false',
    )
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

  it('requires the dedicated API hostname URL in cloud builds', () => {
    setReleaseConfig({ VITE_API_BASE_URL: '/api/v1' })
    expect(() => validateReleaseConfig()).toThrow(
      'Cloud release VITE_API_BASE_URL must be an absolute HTTPS URL',
    )

    setReleaseConfig({
      VITE_RELEASE_ENV: 'production',
      VITE_API_BASE_URL: 'https://api.example.test/api/v1',
    })
    expect(() => validateReleaseConfig()).not.toThrow()

    setReleaseConfig({ VITE_API_BASE_URL: 'https://api.example.test/api/v1' })
    expect(() => validateReleaseConfig()).toThrow('must use the api-dev.<domain> API hostname')
  })
})
