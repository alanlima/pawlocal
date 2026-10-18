import { afterEach, describe, expect, it, vi } from 'vitest'

const cognitoConfig = () => {
  vi.stubEnv('VITE_COGNITO_DOMAIN', 'https://pawlocal-test.auth.ap-southeast-2.amazoncognito.com')
  vi.stubEnv('VITE_COGNITO_CLIENT_ID', 'public-app-client')
  vi.stubEnv('VITE_COGNITO_REDIRECT_URI', 'https://pawlocal.example.test/')
  vi.stubEnv('VITE_COGNITO_LOGOUT_URI', 'https://pawlocal.example.test/')
}

const accessToken = (expiresInSeconds = 600) => {
  const claims = btoa(
    JSON.stringify({
      token_use: 'access',
      client_id: 'public-app-client',
      exp: Math.floor(Date.now() / 1000) + expiresInSeconds,
    }),
  )
  return `header.${claims}.signature`
}

afterEach(() => {
  vi.unstubAllEnvs()
  vi.resetModules()
  vi.unstubAllGlobals()
  sessionStorage.clear()
  window.history.replaceState({}, '', '/')
})

describe('Cognito User Pool authentication', () => {
  it('does not report a session when Cognito is not configured', async () => {
    const { getAccessToken, getAuthSession } = await import('./authSession')

    expect(getAuthSession()).toBeUndefined()
    expect(await getAccessToken()).toBeNull()
  })

  it('rejects partial client configuration', async () => {
    vi.stubEnv('VITE_COGNITO_CLIENT_ID', 'public-app-client')
    const { getAuthSession } = await import('./authSession')

    expect(() => getAuthSession()).toThrow(/requires VITE_COGNITO_DOMAIN/)
  })

  it('uses an unexpired access token from the tab session', async () => {
    cognitoConfig()
    const token = accessToken()
    sessionStorage.setItem(
      'pawlocal.cognito.session',
      JSON.stringify({
        accessToken: token,
        expiresAt: Date.now() + 600_000,
        refreshToken: 'refresh',
      }),
    )
    const fetchStub = vi.fn()
    vi.stubGlobal('fetch', fetchStub)
    const { getAccessToken } = await import('./authSession')

    await expect(getAccessToken()).resolves.toBe(token)
    expect(fetchStub).not.toHaveBeenCalled()
  })

  it('refreshes an expiring access token with the Cognito refresh grant', async () => {
    cognitoConfig()
    sessionStorage.setItem(
      'pawlocal.cognito.session',
      JSON.stringify({
        accessToken: accessToken(1),
        expiresAt: Date.now() + 1_000,
        refreshToken: 'refresh',
      }),
    )
    const token = accessToken()
    const fetchStub = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ access_token: token, expires_in: 600 }),
    })
    vi.stubGlobal('fetch', fetchStub)
    const { getAccessToken } = await import('./authSession')

    await expect(getAccessToken()).resolves.toBe(token)
    expect(fetchStub).toHaveBeenCalledWith(
      'https://pawlocal-test.auth.ap-southeast-2.amazoncognito.com/oauth2/token',
      expect.objectContaining({
        method: 'POST',
      }),
    )
    expect(
      ((fetchStub.mock.calls[0][1] as RequestInit).body as URLSearchParams).toString(),
    ).toContain('grant_type=refresh_token')
    expect(JSON.parse(sessionStorage.getItem('pawlocal.cognito.session') ?? '{}').accessToken).toBe(
      token,
    )
  })

  it('exchanges a callback code only when the PKCE state matches', async () => {
    cognitoConfig()
    sessionStorage.setItem(
      'pawlocal.cognito.pending',
      JSON.stringify({
        verifier: 'pkce-verifier',
        state: 'expected-state',
        returnTo: '/places/one',
      }),
    )
    window.history.replaceState({}, '', '/?code=authorization-code&state=expected-state')
    const token = accessToken()
    const fetchStub = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ access_token: token, refresh_token: 'refresh', expires_in: 600 }),
    })
    vi.stubGlobal('fetch', fetchStub)
    const { getAccessToken } = await import('./authSession')

    await expect(getAccessToken()).resolves.toBe(token)
    expect(fetchStub).toHaveBeenCalledOnce()
    expect(
      ((fetchStub.mock.calls[0][1] as RequestInit).body as URLSearchParams).toString(),
    ).toContain('code_verifier=pkce-verifier')
    expect(window.location.pathname).toBe('/places/one')
    expect(window.location.search).toBe('')
  })

  it('rejects a callback with a mismatched state without contacting Cognito', async () => {
    cognitoConfig()
    sessionStorage.setItem(
      'pawlocal.cognito.pending',
      JSON.stringify({ verifier: 'pkce-verifier', state: 'expected-state', returnTo: '/' }),
    )
    window.history.replaceState({}, '', '/?code=authorization-code&state=attacker-state')
    const fetchStub = vi.fn()
    vi.stubGlobal('fetch', fetchStub)
    const { getAccessToken } = await import('./authSession')

    await expect(getAccessToken()).resolves.toBeNull()
    expect(fetchStub).not.toHaveBeenCalled()
    expect(sessionStorage.getItem('pawlocal.cognito.session')).toBeNull()
    expect(window.location.search).toBe('')
  })
})
