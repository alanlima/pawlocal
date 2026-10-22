// Compare only the public OAuth fields from the same-run configuration snapshot.
export function matchesOAuthSnapshot(actual, config) {
  const scopes = (value) => [...new Set((value || '').trim().split(/\s+/).filter(Boolean))].sort()
  const expectedScopes = scopes(config.VITE_COGNITO_SCOPES)
  return (
    expectedScopes.length > 0 &&
    actual.origin === config.VITE_COGNITO_DOMAIN &&
    actual.searchParams.get('client_id') === config.VITE_COGNITO_CLIENT_ID &&
    actual.searchParams.get('redirect_uri') === config.VITE_COGNITO_REDIRECT_URI &&
    JSON.stringify(scopes(actual.searchParams.get('scope'))) === JSON.stringify(expectedScopes)
  )
}
