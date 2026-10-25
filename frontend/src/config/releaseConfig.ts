export function validateReleaseConfig() {
  const releaseEnvironment = import.meta.env.VITE_RELEASE_ENV?.trim()
  if (!releaseEnvironment) {
    if (import.meta.env.PROD) {
      throw new Error(
        'Production frontend bundles require VITE_RELEASE_ENV and cloud configuration',
      )
    }
    return
  }
  if (releaseEnvironment !== 'development' && releaseEnvironment !== 'production') {
    throw new Error('VITE_RELEASE_ENV must be "development" or "production"')
  }
  if (
    import.meta.env.VITE_TELEMETRY_ENABLED !== 'false' &&
    import.meta.env.VITE_TELEMETRY_ENABLED !== 'true'
  ) {
    throw new Error('Cloud release builds require an explicit boolean VITE_TELEMETRY_ENABLED')
  }
  if (import.meta.env.VITE_TELEMETRY_ENABLED === 'true') {
    let collector
    try {
      collector = new URL(import.meta.env.VITE_FARO_COLLECTOR_URL ?? '')
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
  if (import.meta.env.VITE_USE_MOCK_BACKEND !== 'false') {
    throw new Error('Cloud release builds require VITE_USE_MOCK_BACKEND=false')
  }

  const apiBaseUrl = import.meta.env.VITE_API_BASE_URL?.trim()
  if (!apiBaseUrl) {
    throw new Error('Cloud release builds require an explicit VITE_API_BASE_URL')
  }
  let apiUrl: URL
  try {
    apiUrl = new URL(apiBaseUrl)
  } catch {
    throw new Error('Cloud release VITE_API_BASE_URL must be an absolute HTTPS URL')
  }
  if (apiUrl.protocol !== 'https:') {
    throw new Error('Cloud release API endpoints must use HTTPS')
  }
  if (apiUrl.pathname.replace(/\/$/, '') !== '/api/v1' || apiUrl.search || apiUrl.hash) {
    throw new Error(
      'Cloud release VITE_API_BASE_URL must end with /api/v1 and have no query or fragment',
    )
  }
  const expectedFrontendHostPrefix =
    releaseEnvironment === 'development' ? 'pawlocal-dev.' : 'pawlocal.'
  if (
    !apiUrl.hostname.startsWith(expectedFrontendHostPrefix) ||
    apiUrl.port ||
    apiUrl.username ||
    apiUrl.password
  ) {
    throw new Error(
      `Cloud ${releaseEnvironment} builds must use the ${expectedFrontendHostPrefix}<domain> frontend origin for VITE_API_BASE_URL`,
    )
  }

  const requiredCognitoSettings = [
    import.meta.env.VITE_COGNITO_DOMAIN,
    import.meta.env.VITE_COGNITO_CLIENT_ID,
    import.meta.env.VITE_COGNITO_REDIRECT_URI,
    import.meta.env.VITE_COGNITO_LOGOUT_URI,
  ]
  if (requiredCognitoSettings.some((setting) => !setting?.trim())) {
    throw new Error('Cloud release builds require complete public Cognito client configuration')
  }
  for (const setting of [
    import.meta.env.VITE_COGNITO_DOMAIN,
    import.meta.env.VITE_COGNITO_REDIRECT_URI,
    import.meta.env.VITE_COGNITO_LOGOUT_URI,
  ]) {
    const url = new URL(setting!)
    if (url.protocol !== 'https:' || url.username || url.password || url.search || url.hash) {
      throw new Error('Cloud release Cognito domain and redirect URLs must use HTTPS')
    }
  }
  for (const setting of [
    import.meta.env.VITE_COGNITO_REDIRECT_URI,
    import.meta.env.VITE_COGNITO_LOGOUT_URI,
  ]) {
    if (new URL(setting!).origin !== apiUrl.origin) {
      throw new Error(
        'Cloud release Cognito redirect and logout URLs must use the same frontend origin as VITE_API_BASE_URL',
      )
    }
  }
  if (apiUrl.origin !== window.location.origin) {
    throw new Error('Cloud release VITE_API_BASE_URL must use the serving frontend origin')
  }
}
