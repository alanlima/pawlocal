export interface PawLocalAuthSession {
  getAccessToken: () => string | null | Promise<string | null>
  signIn?: () => void | Promise<void>
  signOut?: () => void | Promise<void>
}

declare global {
  interface Window {
    pawLocalAuth?: PawLocalAuthSession
  }
}

export function getAuthSession(): PawLocalAuthSession | undefined {
  return typeof window === 'undefined' ? undefined : window.pawLocalAuth
}

export async function getAccessToken(): Promise<string | null> {
  const session = getAuthSession()
  return session ? await session.getAccessToken() : null
}
