import { describe, expect, it } from 'vitest'
import { getBuildIdentity } from './buildIdentity'

const commit = 'abcdef0123456789abcdef0123456789abcdef01'

describe('getBuildIdentity', () => {
  it('shows a short commit hash and UTC build time', () => {
    expect(getBuildIdentity(commit, '2026-10-18T02:45:32Z')).toBe(
      'BUILD abcdef0 · 2026-10-18 02:45 UTC',
    )
  })

  it('uses the local label when metadata is missing', () => {
    expect(getBuildIdentity()).toBe('BUILD local')
    expect(getBuildIdentity(commit)).toBe('BUILD local')
  })

  it('uses the local label when metadata is malformed or not UTC', () => {
    expect(getBuildIdentity('not-a-commit', '2026-10-18T02:45:32Z')).toBe('BUILD local')
    expect(getBuildIdentity(commit, '2026-10-18T02:45:32+10:00')).toBe('BUILD local')
    expect(getBuildIdentity(commit, 'not-a-time')).toBe('BUILD local')
  })
})
