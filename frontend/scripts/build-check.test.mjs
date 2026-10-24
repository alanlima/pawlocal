import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const { scripts } = JSON.parse(await readFile(new URL('../package.json', import.meta.url), 'utf8'))

test('disposable checks run the TypeScript compiler before the Vite bundle build', () => {
  // This is the trusted compiler command shared with the release build. An echo,
  // skipped compiler, or release-only wrapper would invalidate incident checks.
  assert.equal(scripts['build:check'], 'tsc -b && vite build')
  assert.equal(scripts['prebuild:check'], undefined)
  assert.equal(scripts['postbuild:check'], undefined)
})

test('ordinary builds retain release configuration and bundle validation around compilation', () => {
  assert.equal(scripts.prebuild, 'node scripts/validate-release-config.mjs')
  assert.equal(scripts.build, 'npm run build:check')
  assert.equal(scripts.postbuild, 'node scripts/validate-release-bundle.mjs')
})
