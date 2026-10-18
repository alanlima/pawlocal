import '@testing-library/jest-dom/vitest'
import { vi } from 'vitest'

// Component/unit tests use seeded fixtures unless a test explicitly switches service mode.
vi.stubEnv('VITE_USE_MOCK_BACKEND', 'true')

const values = new Map<string, string>()
Object.defineProperty(globalThis, 'localStorage', {
  configurable: true,
  value: {
    getItem: (key: string) => values.get(key) ?? null,
    setItem: (key: string, value: string) => {
      values.set(key, String(value))
    },
    removeItem: (key: string) => {
      values.delete(key)
    },
    clear: () => values.clear(),
    get length() {
      return values.size
    },
    key: (index: number) => [...values.keys()][index] ?? null,
  } satisfies Storage,
})
