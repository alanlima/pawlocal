type CognitoConfig = {
  domain: string
  clientId: string
  redirectUri: string
  logoutUri: string
  scopes: string[]
}

export interface PawLocalAuthSession {
  getAccessToken: () => Promise<string | null>
  signIn: () => Promise<void>
  signOut: () => Promise<void>
}

const STORAGE_KEY = 'pawlocal.cognito.session'
const PENDING_KEY = 'pawlocal.cognito.pending'
const REFRESH_BEFORE_EXPIRY_SECONDS = 60

type StoredSession = { accessToken: string; expiresAt: number; refreshToken: string }
type PendingAuth = { verifier: string; state: string; returnTo: string }

function getConfig(): CognitoConfig | undefined {
  const domain = import.meta.env.VITE_COGNITO_DOMAIN?.trim().replace(/\/$/, '')
  const clientId = import.meta.env.VITE_COGNITO_CLIENT_ID?.trim()
  const redirectUri = import.meta.env.VITE_COGNITO_REDIRECT_URI?.trim()
  const logoutUri = import.meta.env.VITE_COGNITO_LOGOUT_URI?.trim()
  const scopes = (import.meta.env.VITE_COGNITO_SCOPES ?? 'openid email profile')
    .split(/\s+/)
    .filter(Boolean)

  if (!domain && !clientId && !redirectUri && !logoutUri) return undefined
  if (!domain || !clientId || !redirectUri || !logoutUri) {
    throw new Error(
      'Cognito auth requires VITE_COGNITO_DOMAIN, VITE_COGNITO_CLIENT_ID, VITE_COGNITO_REDIRECT_URI, and VITE_COGNITO_LOGOUT_URI',
    )
  }
  const parsedDomain = new URL(domain)
  if (
    parsedDomain.protocol !== 'https:' ||
    parsedDomain.pathname !== '/' ||
    parsedDomain.search ||
    parsedDomain.hash
  ) {
    throw new Error('VITE_COGNITO_DOMAIN must use HTTPS')
  }
  return { domain, clientId, redirectUri, logoutUri, scopes }
}

function encodeBase64Url(bytes: Uint8Array): string {
  let binary = ''
  bytes.forEach((byte) => (binary += String.fromCharCode(byte)))
  return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
}

function randomVerifier(): string {
  return encodeBase64Url(crypto.getRandomValues(new Uint8Array(32)))
}

async function sha256(value: string): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(value))
  return encodeBase64Url(new Uint8Array(digest))
}

function readSession(): StoredSession | undefined {
  try {
    const value = sessionStorage.getItem(STORAGE_KEY)
    return value ? (JSON.parse(value) as StoredSession) : undefined
  } catch {
    sessionStorage.removeItem(STORAGE_KEY)
    return undefined
  }
}

function saveSession(value: StoredSession) {
  sessionStorage.setItem(STORAGE_KEY, JSON.stringify(value))
}

function clearSession() {
  sessionStorage.removeItem(STORAGE_KEY)
}

function tokenExpiry(accessToken: string, expectedClientId: string): number {
  try {
    const payload = accessToken.split('.')[1]
    const base64 = payload.replace(/-/g, '+').replace(/_/g, '/')
    const padded = base64.padEnd(Math.ceil(base64.length / 4) * 4, '=')
    const claims = JSON.parse(atob(padded)) as {
      exp?: number
      token_use?: string
      client_id?: string
    }
    const expiry = typeof claims.exp === 'number' ? claims.exp * 1000 : 0
    if (
      claims.token_use !== 'access' ||
      claims.client_id !== expectedClientId ||
      expiry <= Date.now()
    ) {
      return 0
    }
    return expiry
  } catch {
    return 0
  }
}

class CognitoAuthSession implements PawLocalAuthSession {
  private readonly config: CognitoConfig
  private tokenRequest?: Promise<string | null>

  constructor(config: CognitoConfig) {
    this.config = config
  }

  async getAccessToken(): Promise<string | null> {
    if (!this.tokenRequest) {
      this.tokenRequest = this.resolveAccessToken().finally(() => {
        this.tokenRequest = undefined
      })
    }
    return this.tokenRequest
  }

  async signIn(): Promise<void> {
    const verifier = randomVerifier()
    const state = randomVerifier()
    const challenge = await sha256(verifier)
    const pending: PendingAuth = {
      verifier,
      state,
      returnTo: `${window.location.pathname}${window.location.search}${window.location.hash}`,
    }
    sessionStorage.setItem(PENDING_KEY, JSON.stringify(pending))

    const authorize = new URL(`${this.config.domain}/oauth2/authorize`)
    authorize.search = new URLSearchParams({
      client_id: this.config.clientId,
      response_type: 'code',
      scope: this.config.scopes.join(' '),
      redirect_uri: this.config.redirectUri,
      state,
      code_challenge: challenge,
      code_challenge_method: 'S256',
    }).toString()
    window.location.assign(authorize.toString())
  }

  async signOut(): Promise<void> {
    clearSession()
    sessionStorage.removeItem(PENDING_KEY)
    const logout = new URL(`${this.config.domain}/logout`)
    logout.search = new URLSearchParams({
      client_id: this.config.clientId,
      logout_uri: this.config.logoutUri,
    }).toString()
    window.location.assign(logout.toString())
  }

  private async resolveAccessToken(): Promise<string | null> {
    const callbackToken = await this.exchangeAuthorizationCode()
    if (callbackToken) return callbackToken

    const session = readSession()
    if (!session) return null
    const verifiedExpiry = tokenExpiry(session.accessToken, this.config.clientId)
    if (verifiedExpiry > Date.now() + REFRESH_BEFORE_EXPIRY_SECONDS * 1000) {
      return session.accessToken
    }
    if (!session.refreshToken) {
      clearSession()
      return null
    }
    try {
      const response = await this.tokenEndpoint({
        grant_type: 'refresh_token',
        client_id: this.config.clientId,
        refresh_token: session.refreshToken,
      })
      const accessToken = typeof response.access_token === 'string' ? response.access_token : ''
      const expiresAt = tokenExpiry(accessToken, this.config.clientId)
      if (!expiresAt) throw new Error('Cognito did not return a valid access token')
      saveSession({
        accessToken,
        expiresAt,
        refreshToken:
          typeof response.refresh_token === 'string'
            ? response.refresh_token
            : session.refreshToken,
      })
      return accessToken
    } catch {
      clearSession()
      return null
    }
  }

  private async exchangeAuthorizationCode(): Promise<string | null> {
    const callback = new URL(window.location.href)
    const code = callback.searchParams.get('code')
    const returnedState = callback.searchParams.get('state')
    if (!code && !returnedState) return null

    const rawPending = sessionStorage.getItem(PENDING_KEY)
    sessionStorage.removeItem(PENDING_KEY)
    let pending: PendingAuth | undefined
    try {
      pending = rawPending ? (JSON.parse(rawPending) as PendingAuth) : undefined
    } catch {
      pending = undefined
    }
    if (!code || !returnedState || !pending || returnedState !== pending.state) {
      callback.searchParams.delete('code')
      callback.searchParams.delete('state')
      callback.searchParams.delete('error')
      callback.searchParams.delete('error_description')
      window.history.replaceState({}, '', `${callback.pathname}${callback.search}${callback.hash}`)
      clearSession()
      return null
    }

    callback.searchParams.delete('code')
    callback.searchParams.delete('state')
    window.history.replaceState({}, '', `${pending.returnTo || '/'}${callback.hash}`)
    try {
      const response = await this.tokenEndpoint({
        grant_type: 'authorization_code',
        client_id: this.config.clientId,
        code,
        redirect_uri: this.config.redirectUri,
        code_verifier: pending.verifier,
      })
      const accessToken = typeof response.access_token === 'string' ? response.access_token : ''
      const refreshToken = typeof response.refresh_token === 'string' ? response.refresh_token : ''
      const expiresAt = tokenExpiry(accessToken, this.config.clientId)
      if (!expiresAt || !refreshToken) throw new Error('Cognito token response is incomplete')
      saveSession({ accessToken, expiresAt, refreshToken })
      return accessToken
    } catch {
      clearSession()
      return null
    }
  }

  private async tokenEndpoint(params: Record<string, string>): Promise<Record<string, unknown>> {
    const response = await fetch(`${this.config.domain}/oauth2/token`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: new URLSearchParams(params),
    })
    if (!response.ok) throw new Error('Cognito token request failed')
    return (await response.json()) as Record<string, unknown>
  }
}

let authSession: CognitoAuthSession | undefined

export function getAuthSession(): PawLocalAuthSession | undefined {
  const config = getConfig()
  if (!config) return undefined
  authSession ??= new CognitoAuthSession(config)
  return authSession
}

export async function getAccessToken(): Promise<string | null> {
  return (await getAuthSession()?.getAccessToken()) ?? null
}
