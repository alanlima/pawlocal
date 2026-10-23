import { fileURLToPath } from 'node:url'
import { resolve } from 'node:path'

function parseHttpsUrl(value, variableName, { rootOnly = false } = {}) {
  let parsed
  try {
    parsed = new URL(value)
  } catch {
    throw new Error(`${variableName} must be a valid HTTPS URL`)
  }
  if (
    parsed.protocol !== 'https:' ||
    !parsed.hostname ||
    parsed.username ||
    parsed.password ||
    (rootOnly && parsed.pathname !== '/') ||
    parsed.search ||
    parsed.hash
  ) {
    throw new Error(`${variableName} must be a valid HTTPS URL${rootOnly ? ' origin' : ''}`)
  }
  return parsed
}

export function validateReleaseSettings(env = process.env) {
  const releaseEnvironment = env.VITE_RELEASE_ENV?.trim()
  if (!releaseEnvironment) {
    throw new Error('Set VITE_RELEASE_ENV to "development" or "production" before a release build')
  }
  if (releaseEnvironment !== 'development' && releaseEnvironment !== 'production') {
    throw new Error('VITE_RELEASE_ENV must be "development" or "production"')
  }
  if (env.VITE_USE_MOCK_BACKEND !== 'false') {
    throw new Error('Cloud release builds require VITE_USE_MOCK_BACKEND=false')
  }
  if (env.VITE_TELEMETRY_ENABLED !== 'false' && env.VITE_TELEMETRY_ENABLED !== 'true') {
    throw new Error('Cloud release builds require an explicit boolean VITE_TELEMETRY_ENABLED')
  }
  if (env.VITE_TELEMETRY_ENABLED === 'true') {
    let collector
    try {
      collector = new URL(env.VITE_FARO_COLLECTOR_URL ?? '')
    } catch {
      throw new Error('Enabled cloud telemetry requires a verified public Faro collector URL')
    }
    if (
      collector.protocol !== 'https:' ||
      !collector.hostname.endsWith('.grafana.net') ||
      collector.username ||
      collector.password ||
      collector.port ||
      collector.search ||
      collector.hash ||
      !/^\/collect\/[A-Za-z0-9_-]+$/.test(collector.pathname)
    ) {
      throw new Error('Enabled cloud telemetry requires a verified public Faro collector URL')
    }
  }

  const apiBaseUrl = env.VITE_API_BASE_URL?.trim()
  if (!apiBaseUrl) throw new Error('Cloud release builds require an explicit VITE_API_BASE_URL')
  let apiUrl
  try {
    apiUrl = parseHttpsUrl(apiBaseUrl, 'VITE_API_BASE_URL')
  } catch {
    throw new Error('Cloud release VITE_API_BASE_URL must be an absolute HTTPS URL')
  }
  if (apiUrl.pathname.replace(/\/$/, '') !== '/api/v1' || apiUrl.search || apiUrl.hash) {
    throw new Error(
      'Cloud release VITE_API_BASE_URL must end with /api/v1 and have no query or fragment',
    )
  }
  const expectedApiHostPrefix = releaseEnvironment === 'development' ? 'api-dev.' : 'api.'
  if (!apiUrl.hostname.startsWith(expectedApiHostPrefix)) {
    throw new Error(
      `Cloud ${releaseEnvironment} builds must set VITE_API_BASE_URL to the ${expectedApiHostPrefix}<domain> API hostname`,
    )
  }

  const clientId = env.VITE_COGNITO_CLIENT_ID?.trim()
  if (!clientId) throw new Error('Cloud release builds require VITE_COGNITO_CLIENT_ID')
  parseHttpsUrl(env.VITE_COGNITO_DOMAIN?.trim() ?? '', 'VITE_COGNITO_DOMAIN', {
    rootOnly: true,
  })
  parseHttpsUrl(env.VITE_COGNITO_REDIRECT_URI?.trim() ?? '', 'VITE_COGNITO_REDIRECT_URI')
  parseHttpsUrl(env.VITE_COGNITO_LOGOUT_URI?.trim() ?? '', 'VITE_COGNITO_LOGOUT_URI')

  return { skipped: false, environment: releaseEnvironment }
}

function run() {
  const result = validateReleaseSettings(process.env)
  console.log(`Validated ${result.environment} frontend release configuration.`)
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    run()
  } catch (error) {
    console.error(error instanceof Error ? error.message : String(error))
    process.exitCode = 1
  }
}
