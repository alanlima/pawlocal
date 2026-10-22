// Real Vite bundles and browser redirects; all identities/APIs are local fixtures.
import assert from 'node:assert/strict'
import { spawnSync } from 'node:child_process'
import { cp, mkdtemp, readFile, rm } from 'node:fs/promises'
import { createServer } from 'node:http'
import { createRequire } from 'node:module'
import { tmpdir } from 'node:os'
import { dirname, extname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '../../..')
const frontend = join(root, 'frontend')
const require = createRequire(join(frontend, 'package.json'))
const { chromium } = require('@playwright/test')
const oldConfig = JSON.parse(await readFile(process.argv[2], 'utf8'))
const newConfig = JSON.parse(await readFile(process.argv[3], 'utf8'))
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
      VITE_RELEASE_ENV: process.argv[4] || 'development',
      VITE_USE_MOCK_BACKEND: 'false',
      VITE_TELEMETRY_ENABLED: 'false',
    }
    for (const script of [
      ['scripts/validate-release-config.mjs'],
      ['node_modules/vite/bin/vite.js', 'build'],
    ]) {
      const result = spawnSync(process.execPath, script, { cwd: frontend, env, encoding: 'utf8' })
      assert.equal(result.status, 0, 'Fixture frontend build must succeed')
    }
    await cp(join(frontend, 'dist'), join(temporary, target), { recursive: true })
    return join(temporary, target)
  }
  async function observedRedirect() {
    const page = await browser.newPage()
    await page.route(`${new URL(oldConfig.VITE_API_BASE_URL).origin}/**`, (route) =>
      route.fulfill({ json: { items: [], total: 0, page: 1, page_size: 20 } }),
    )
    await page.route('https://*.amazoncognito.com/**', (route) =>
      route.fulfill({ contentType: 'text/html', body: '<html>OAuth fixture</html>' }),
    )
    await page.goto(`http://127.0.0.1:${server.address().port}/`)
    const request = page.waitForRequest((request) => request.url().includes('/oauth2/authorize'))
    await page.getByRole('button', { name: /^Sign in/ }).click()
    const url = new URL((await request).url())
    const result = {
      origin: url.origin,
      client: url.searchParams.get('client_id'),
      callback: url.searchParams.get('redirect_uri'),
    }
    await page.close()
    return result
  }
  const expected = (config) => ({
    origin: config.VITE_COGNITO_DOMAIN,
    client: config.VITE_COGNITO_CLIENT_ID,
    callback: config.VITE_COGNITO_REDIRECT_URI,
  })
  published = await build(oldConfig, 'old')
  assert.deepEqual(await observedRedirect(), expected(oldConfig))
  // GitHub values have reconciled to newConfig, but the published old bytes remain stale.
  assert.notDeepEqual(await observedRedirect(), expected(newConfig))
  published = await build(newConfig, 'replacement')
  assert.deepEqual(await observedRedirect(), expected(newConfig))
  console.log(
    'Fixture PASS: stale served bundle fails replacement readiness; rebuilt publication uses the reconciled OAuth host/client/callback.',
  )
} finally {
  await browser.close()
  await new Promise((resolve) => server.close(resolve))
  await rm(temporary, { recursive: true, force: true })
}
