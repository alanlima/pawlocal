export interface PawLocalAuthSession {
  getAccessToken: () => Promise<string | null>
  signIn: () => Promise<void>
  signOut: () => Promise<void>
}

declare global {
  interface Window {
    __PAWLOCAL_E2E_ACCESS_TOKEN__?: string | null
    __PAWLOCAL_E2E_SIGN_IN_TOKEN__?: string
  }
}

const session: PawLocalAuthSession = {
  getAccessToken: async () => window.__PAWLOCAL_E2E_ACCESS_TOKEN__ ?? null,
  signIn: async () => {
    window.__PAWLOCAL_E2E_ACCESS_TOKEN__ = window.__PAWLOCAL_E2E_SIGN_IN_TOKEN__ ?? null
  },
  signOut: async () => {
    window.__PAWLOCAL_E2E_ACCESS_TOKEN__ = null
  },
}

export function getAuthSession(): PawLocalAuthSession {
  return session
}

export async function getAccessToken(): Promise<string | null> {
  return session.getAccessToken()
}
