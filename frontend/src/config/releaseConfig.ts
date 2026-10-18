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
  if (/^http:\/\//i.test(apiBaseUrl)) {
    throw new Error('Cloud release API endpoints must use HTTPS')
  }
  if (/^https:\/\//i.test(apiBaseUrl)) {
    new URL(apiBaseUrl)
  } else if (!apiBaseUrl.startsWith('/') || apiBaseUrl.startsWith('//')) {
    throw new Error('VITE_API_BASE_URL must be an absolute HTTPS URL or a same-origin path')
  }
  if (releaseEnvironment === 'production' && apiBaseUrl !== '/api/v1') {
    throw new Error('Production VITE_API_BASE_URL must be exactly /api/v1')
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
