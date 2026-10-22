// Check the actual served app's sign-in redirect without creating a user/session.
import { createRequire } from 'node:module'
import { resolve } from 'node:path'

const require = createRequire(resolve('frontend/package.json'))
let browser
try {
  const { chromium } = require('@playwright/test')
  const config = JSON.parse(process.env.RECONCILED_FRONTEND_CONFIG || '{}')
  if (
    !config.PAWLOCAL_PUBLIC_BASE_URL ||
    !config.VITE_COGNITO_DOMAIN ||
    !config.VITE_COGNITO_CLIENT_ID ||
    !config.VITE_COGNITO_REDIRECT_URI
  )
    throw new Error('missing snapshot')
  browser = await chromium.launch({ headless: true })
  let verified = false
  for (let attempt = 0; attempt < 6 && !verified; attempt++) {
    const page = await browser.newPage({ extraHTTPHeaders: { 'Cache-Control': 'no-cache' } })
    try {
      // Observe generated navigation, then stop before contacting the identity provider.
      await page.route('**/oauth2/authorize**', (route) =>
        route.fulfill({ contentType: 'text/html', body: '<html>Redirect observed</html>' }),
      )
      await page.goto(config.PAWLOCAL_PUBLIC_BASE_URL, {
        waitUntil: 'domcontentloaded',
        timeout: 30000,
      })
      const [authorization] = await Promise.all([
        page.waitForRequest((request) => new URL(request.url()).pathname === '/oauth2/authorize', {
          timeout: 15000,
        }),
        page.getByRole('button', { name: /^Sign in/ }).click({ timeout: 15000 }),
      ])
      const actual = new URL(authorization.url())
      verified =
        actual.origin === config.VITE_COGNITO_DOMAIN &&
        actual.searchParams.get('client_id') === config.VITE_COGNITO_CLIENT_ID &&
        actual.searchParams.get('redirect_uri') === config.VITE_COGNITO_REDIRECT_URI
    } catch {
      // Report no URLs, client IDs, page content or browser error payloads.
    } finally {
      await page.close()
    }
    if (!verified && attempt < 5) await new Promise((resolve) => setTimeout(resolve, 5000))
  }
  if (!verified) throw new Error('served configuration mismatch')
  console.log('Served OAuth host/client/callback match the same-run reconciled configuration.')
} catch {
  console.error('Served OAuth configuration verification failed.')
  process.exitCode = 1
} finally {
  if (browser) await browser.close()
}
