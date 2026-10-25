import assert from 'node:assert/strict'
import test from 'node:test'
import { validateReleaseSettings } from './validate-release-config.mjs'

function releaseSettings(environment = 'development') {
  const origin =
    environment === 'production'
      ? 'https://pawlocal.example.test'
      : 'https://pawlocal-dev.example.test'
  return {
    CI: 'true',
    VITE_RELEASE_ENV: environment,
    VITE_APP_COMMIT: 'a'.repeat(40),
    VITE_APP_BUILD_TIME: '2026-10-26T01:23:45Z',
    VITE_USE_MOCK_BACKEND: 'false',
    VITE_TELEMETRY_ENABLED: 'false',
    VITE_API_BASE_URL:
      environment === 'production'
        ? 'https://pawlocal.example.test/api/v1'
        : 'https://pawlocal-dev.example.test/api/v1',
    VITE_COGNITO_DOMAIN: 'https://pawlocal-test.auth.ap-southeast-2.amazoncognito.com',
    VITE_COGNITO_CLIENT_ID: 'public-app-client',
    VITE_COGNITO_REDIRECT_URI: `${origin}/auth/callback`,
    VITE_COGNITO_LOGOUT_URI: `${origin}/`,
  }
}

test('accepts complete development and production release settings', () => {
  assert.equal(validateReleaseSettings(releaseSettings('development')).environment, 'development')
  assert.equal(validateReleaseSettings(releaseSettings('production')).environment, 'production')
})

test('requires release settings for every production build', () => {
  const settings = releaseSettings()
  delete settings.VITE_RELEASE_ENV
  assert.throws(() => validateReleaseSettings(settings), /Set VITE_RELEASE_ENV/)
  assert.throws(() => validateReleaseSettings({}), /Set VITE_RELEASE_ENV/)
})

test('requires mock mode and telemetry to be explicitly disabled', () => {
  assert.throws(
    () => validateReleaseSettings({ ...releaseSettings(), VITE_USE_MOCK_BACKEND: 'true' }),
    /VITE_USE_MOCK_BACKEND=false/,
  )
  assert.throws(
    () => validateReleaseSettings({ ...releaseSettings(), VITE_TELEMETRY_ENABLED: 'true' }),
    /verified public Faro collector URL/,
  )
})

test('rejects an invalid or insecure API URL', () => {
  for (const value of [
    'http://api.example.test/api/v1',
    'https://:bad',
    '//api.example.test/api/v1',
    'api/v1',
  ]) {
    assert.throws(
      () => validateReleaseSettings({ ...releaseSettings(), VITE_API_BASE_URL: value }),
      /VITE_API_BASE_URL/,
    )
  }
})

test('cloud release API URL must use its environment frontend origin and /api/v1 path', () => {
  for (const [environment, value] of [
    ['production', 'https://pawlocal-dev.example.test/api/v1'],
    ['development', 'https://pawlocal.example.test/api/v1'],
    ['production', 'https://pawlocal.example.test/api/v2'],
    ['production', '/api/v1'],
  ]) {
    assert.throws(
      () =>
        validateReleaseSettings({
          ...releaseSettings(environment),
          VITE_API_BASE_URL: value,
        }),
      /VITE_API_BASE_URL/,
    )
  }
})

test('rejects malformed Cognito domain, callback, and logout URLs', () => {
  assert.throws(
    () =>
      validateReleaseSettings({ ...releaseSettings(), VITE_COGNITO_DOMAIN: 'https://bad/path' }),
    /VITE_COGNITO_DOMAIN/,
  )
  assert.throws(
    () =>
      validateReleaseSettings({
        ...releaseSettings(),
        VITE_COGNITO_DOMAIN: 'https://bad/#fragment',
      }),
    /VITE_COGNITO_DOMAIN/,
  )
  for (const value of [
    'not a URL',
    'http://pawlocal.example.test/callback',
    'https://pawlocal.example.test/#fragment',
  ]) {
    assert.throws(
      () => validateReleaseSettings({ ...releaseSettings(), VITE_COGNITO_REDIRECT_URI: value }),
      /VITE_COGNITO_REDIRECT_URI/,
    )
    assert.throws(
      () => validateReleaseSettings({ ...releaseSettings(), VITE_COGNITO_LOGOUT_URI: value }),
      /VITE_COGNITO_LOGOUT_URI/,
    )
  }
})

test('accepts enabled public Faro bindings and rejects credentials or foreign collectors', () => {
  assert.doesNotThrow(() =>
    validateReleaseSettings({
      ...releaseSettings(),
      VITE_TELEMETRY_ENABLED: 'true',
      VITE_FARO_COLLECTOR_URL: 'https://faro.grafana.net/collect/public-key',
    }),
  )
  for (const value of [
    'https://user:private@faro.grafana.net/collect/key',
    'https://faro.grafana.net/collect/key?token=private',
    'https://foreign.example.test/collect/key',
  ]) {
    assert.throws(() =>
      validateReleaseSettings({
        ...releaseSettings(),
        VITE_TELEMETRY_ENABLED: 'true',
        VITE_FARO_COLLECTOR_URL: value,
      }),
    )
  }
})

test('rejects missing or invalid release build identity in either environment', () => {
  for (const environment of ['development', 'production']) {
    for (const value of [undefined, '', 'local', 'abcdef0', 'g'.repeat(40)]) {
      assert.throws(
        () => validateReleaseSettings({ ...releaseSettings(environment), VITE_APP_COMMIT: value }),
        /VITE_APP_COMMIT/,
      )
    }
    for (const value of [
      undefined,
      '',
      'not-a-time',
      '2026-10-26',
      '2026-10-26T01:23:45+10:00',
      '2026-13-26T01:23:45Z',
      '2026-02-30T01:23:45Z',
    ]) {
      assert.throws(
        () =>
          validateReleaseSettings({ ...releaseSettings(environment), VITE_APP_BUILD_TIME: value }),
        /VITE_APP_BUILD_TIME/,
      )
    }
  }
})

test('rejects foreign API or auth origins, legacy API hosts, and decorated URLs', () => {
  for (const value of [
    'https://pawlocal-dev.foreign.test/api/v1',
    'https://pawlocal-dev.example.test:8443/api/v1',
    'https://user:password@pawlocal-dev.example.test/api/v1',
    'https://pawlocal-dev.example.test/api/v1?query=value',
    'https://pawlocal-dev.example.test/api/v1#fragment',
    'https://api-dev.example.test/api/v1',
  ]) {
    assert.throws(() => validateReleaseSettings({ ...releaseSettings(), VITE_API_BASE_URL: value }))
  }
  for (const variableName of ['VITE_COGNITO_REDIRECT_URI', 'VITE_COGNITO_LOGOUT_URI']) {
    for (const origin of ['https://pawlocal.example.test', 'https://pawlocal-dev.foreign.test']) {
      assert.throws(
        () => validateReleaseSettings({ ...releaseSettings(), [variableName]: `${origin}/` }),
        /same frontend origin/,
      )
    }
  }
})
