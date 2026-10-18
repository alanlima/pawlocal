import { afterEach, describe, expect, it } from 'vitest'
import { getAccessToken } from './authSession'

afterEach(() => {
  delete window.pawLocalAuth
})

describe('host-provided authentication session', () => {
  it('returns no token when no host session is configured', async () => {
    expect(await getAccessToken()).toBeNull()
  })

  it('supports a synchronous access-token provider', async () => {
    window.pawLocalAuth = { getAccessToken: () => 'sync-access-token' }

    expect(await getAccessToken()).toBe('sync-access-token')
  })

  it('supports an asynchronous access-token provider', async () => {
    window.pawLocalAuth = { getAccessToken: async () => 'async-access-token' }

    expect(await getAccessToken()).toBe('async-access-token')
  })
})
