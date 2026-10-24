import { expect, it } from 'vitest'
import { getBuildIdentity } from './app/buildIdentity'

it('preserves the application build identity through the real reporter', () => {
  expect(getBuildIdentity('a'.repeat(40), '2026-10-24T00:00:00Z')).toBe(
    'BUILD aaaaaaa · 2026-10-24 00:00 UTC',
  )
})
