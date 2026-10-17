import type { Contribution } from '../types/place'

/** Explicitly synthetic content used only to exercise contribution reporting in Stage 1. */
export const demoContributions: Contribution[] = [
  {
    id: '00000000-0000-4000-8000-000000000099',
    kind: 'tip',
    body: 'DEMO ONLY: Example contribution for testing the report flow. This is not community data or verified place information.',
    createdAt: '2026-01-01T00:00:00.000Z',
    demoOnly: true,
  },
]
