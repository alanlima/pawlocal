// Real Vite bundles and browser redirects; all identities/APIs are local fixtures.
import assert from 'node:assert/strict'
import { spawnSync } from 'node:child_process'
import { cp, mkdtemp, readFile, rm } from 'node:fs/promises'
import { createServer } from 'node:http'
import { createRequire } from 'node:module'
import { tmpdir } from 'node:os'
import { dirname, extname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { matchesOAuthSnapshot } from '../oauth-snapshot.mjs'
import { verifyServedBuildIdentity } from '../verify-served-build-identity.mjs'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '../../..')
const frontend = join(root, 'frontend')
const require = createRequire(join(frontend, 'package.json'))
const { chromium } = require('@playwright/test')
const oldConfig = JSON.parse(await readFile(process.argv[2], 'utf8'))
const newConfig = JSON.parse(await readFile(process.argv[3], 'utf8'))
const buildCommit = 'a'.repeat(40)
const buildTime = new Date().toISOString()
const temporary = await mkdtemp(join(tmpdir(), 'pawlocal-config-recovery-'))
let published
const server = createServer(async (request, response) => {
  try {
    const path = new URL(request.url, 'http://localhost').pathname
    const asset = join(published, path === '/' ? 'index.html' : path)
    if (!resolve(asset).startsWith(resolve(published))) throw new Error('outside fixture')
    const body = await readFile(asset)
    response.setHeader('Cache-Control', 'no-store')
    response.setHeader(
      'Content-Type',
      { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css' }[extname(asset)] ||
        'application/octet-stream',
    )
    response.end(body)
  } catch {
    response.statusCode = 404
    response.end()
  }
})
await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve))
const browser = await chromium.launch({ headless: true })
try {
  async function build(config, target) {
    const env = {
      ...process.env,
      ...config,
      VITE_APP_COMMIT: buildCommit,
      VITE_APP_BUILD_TIME: buildTime,
      VITE_RELEASE_ENV: process.argv[4] || 'development',
      VITE_USE_MOCK_BACKEND: 'false',
      VITE_TELEMETRY_ENABLED: 'false',
    }
    for (const script of [
      ['scripts/validate-release-config.mjs'],
      ['node_modules/vite/bin/vite.js', 'build'],
    ]) {
      const result = spawnSync(process.execPath, script, {
        cwd: frontend,
        env,
        encoding: 'utf8',
      })
      assert.equal(result.status, 0, 'Fixture frontend build must succeed')
    }
    await cp(join(frontend, 'dist'), join(temporary, target), {
      recursive: true,
    })
    return join(temporary, target)
  }
  async function observedRedirect() {
    const page = await browser.newPage()
    const applicationOrigin = new URL(oldConfig.VITE_API_BASE_URL).origin
    // Serve fixture bytes through the logical cloud origin so runtime validation
    // exercises the same-origin contract without contacting a public endpoint.
    await page.route(`${applicationOrigin}/**`, async (route) => {
      const requested = new URL(route.request().url())
      const response = await fetch(`http://127.0.0.1:${server.address().port}${requested.pathname}${requested.search}`)
      return route.fulfill({
        status: response.status,
        headers: Object.fromEntries(response.headers),
        body: Buffer.from(await response.arrayBuffer()),
      })
    })
    await page.route(`${applicationOrigin}/api/**`, (route) => {
      const place = {
        id: 'release-fixture',
        name: 'Synthetic release fixture',
        category: 'dog_park',
        area: 'Fixture',
        description:
          'Synthetic public source: https://www.google.com/maps/search/?api=1&query=Baringa%20Dog%20Park%20Baringa%20Queensland',
      }
      return route.fulfill({
        json: new URL(route.request().url()).pathname.endsWith('/places/release-fixture')
          ? place
          : { items: [place], total: 1, page: 1, page_size: 20 },
      })
    })
    await page.route('https://*.amazoncognito.com/**', (route) =>
      route.fulfill({
        contentType: 'text/html',
        body: '<html>OAuth fixture</html>',
      }),
    )
    await page.goto(`${applicationOrigin}/`)
    for (const width of [1280, 375]) {
      await page.setViewportSize({ width, height: 900 })
      await page.locator('button.card-content').first().waitFor({ state: 'visible' })
      await verifyServedBuildIdentity(page, buildCommit, buildTime)
      assert.equal(
        await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
        true,
      )
      await page.getByRole('button', { name: 'View Synthetic release fixture' }).click()
      const detail = page.locator('main.detail-page')
      await detail.waitFor({ state: 'visible' })
      await detail
        .getByRole('heading', { level: 1, name: 'Synthetic release fixture', exact: true })
        .waitFor()
      await detail.getByRole('button', { name: 'Share this place', exact: true }).waitFor()
      assert.equal(
        await detail.locator('.detail-description').innerText(),
        'Synthetic public source: https://www.google.com/maps/search/?api=1&query=Baringa%20Dog%20Park%20Baringa%20Queensland',
      )
      await verifyServedBuildIdentity(page, buildCommit, buildTime)
      assert.equal(
        await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
        true,
        `Fully rendered detail must not overflow at ${width}px`,
      )
      await page.goto(`${applicationOrigin}/`)
    }
    const request = page.waitForRequest((request) => request.url().includes('/oauth2/authorize'))
    await page.getByRole('button', { name: /^Sign in/ }).click()
    const url = new URL((await request).url())
    await page.close()
    return url
  }
  published = await build(oldConfig, 'old')
  assert.equal(matchesOAuthSnapshot(await observedRedirect(), oldConfig), true)
  // GitHub values have reconciled to newConfig, but the published old bytes remain stale.
  assert.equal(matchesOAuthSnapshot(await observedRedirect(), newConfig), false)
  published = await build(newConfig, 'replacement')
  assert.equal(matchesOAuthSnapshot(await observedRedirect(), newConfig), true)
  const scopesOnly = { ...newConfig, VITE_COGNITO_SCOPES: 'openid' }
  assert.notEqual(newConfig.VITE_COGNITO_SCOPES, scopesOnly.VITE_COGNITO_SCOPES)
  // Host/client/callback now match, but the served scopes alone are stale.
  assert.equal(matchesOAuthSnapshot(await observedRedirect(), scopesOnly), false)
  published = await build(scopesOnly, 'replacement-scopes')
  assert.equal(matchesOAuthSnapshot(await observedRedirect(), scopesOnly), true)
  const actual = await observedRedirect()
  actual.searchParams.set('scope', 'profile openid email')
  assert.equal(
    matchesOAuthSnapshot(actual, {
      ...scopesOnly,
      VITE_COGNITO_SCOPES: 'email profile openid',
    }),
    true,
  )
  actual.searchParams.delete('scope')
  assert.equal(matchesOAuthSnapshot(actual, scopesOnly), false)
  console.log(
    'Fixture PASS: stale served identity or scopes fail readiness; rebuilt publication matches the reconciled OAuth snapshot.',
  )
} finally {
  await browser.close()
  await new Promise((resolve) => server.close(resolve))
  await rm(temporary, { recursive: true, force: true })
}
