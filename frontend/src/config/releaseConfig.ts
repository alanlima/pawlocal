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
  if (import.meta.env.VITE_TELEMETRY_ENABLED !== 'false') {
    throw new Error('Cloud release builds require VITE_TELEMETRY_ENABLED=false')
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
  if (apiUrl.pathname.replace(/\/$/, '') !== '/api/v1') {
    throw new Error('Cloud release VITE_API_BASE_URL must end with /api/v1')
  }
  const expectedApiHostPrefix = releaseEnvironment === 'development' ? 'api-dev.' : 'api.'
  if (!apiUrl.hostname.startsWith(expectedApiHostPrefix)) {
    throw new Error(
      `Cloud ${releaseEnvironment} builds must use the ${expectedApiHostPrefix}<domain> API hostname`,
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
    if (new URL(setting!).protocol !== 'https:') {
      throw new Error('Cloud release Cognito domain and redirect URLs must use HTTPS')
    }
  }
}
