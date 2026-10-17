import { expect, test } from '@playwright/test'

test('verified local JWT drives browser writes persisted in PostgreSQL', async ({
  browser,
  context,
  page,
  request,
}) => {
  const apiBase = 'http://127.0.0.1:18001/api/v1'
  const anonymous = await request.get(`${apiBase}/me/favourites`)
  expect(anonymous.status()).toBe(401)

  const tokenResponse = await request.get('http://127.0.0.1:18002/test-access-token')
  expect(tokenResponse.ok()).toBeTruthy()
  const { access_token: accessToken } = (await tokenResponse.json()) as {
    access_token: string
  }
  await context.grantPermissions(['clipboard-read', 'clipboard-write'])
  await page.addInitScript((token) => {
    window.__PAWLOCAL_E2E_ACCESS_TOKEN__ = token
  }, accessToken)

  const authenticatedRead = page.waitForRequest(
    (apiRequest) =>
      apiRequest.url().includes('/api/v1/me/favourites') &&
      apiRequest.headers()['authorization'] === `Bearer ${accessToken}`,
  )
  await page.goto('/')
  await authenticatedRead
  const card = page.getByRole('button', { name: 'View Synthetic Stage 3 E2E Dog Park' })
  await expect(card).toBeVisible()
  await card.click()
  await expect(page.getByRole('heading', { name: 'Synthetic Stage 3 E2E Dog Park' })).toBeVisible()
  await expect(page.getByText('Dog access details are unconfirmed')).toBeVisible()
  await page.getByRole('button', { name: 'Share this place' }).click()
  await expect(page.getByRole('status')).toContainText('Link copied')

  // This UI control only opens the mock-stage contribution form. The request
  // itself is authenticated by the real, short-lived token above and verified
  // by the backend's normal issuer/JWKS/exp/client_id checks.
  await page.getByRole('button', { name: 'Add a place' }).click()
  await page.getByRole('button', { name: 'Continue as demo member' }).click()
  await page.getByLabel('What would you like to share?').selectOption('tip')
  const contributionText = `Browser API persistence ${Date.now()}`
  await page.getByLabel('Your note').fill(contributionText)
  const contributionResponse = page.waitForResponse(
    (response) =>
      response.url().includes('/api/v1/contributions') && response.request().method() === 'POST',
  )
  await page.getByRole('button', { name: 'Share with PawLocal' }).click()
  expect((await contributionResponse).status()).toBe(201)

  const favouriteResponse = page.waitForResponse(
    (response) =>
      response.url().includes('/api/v1/me/favourites') && response.request().method() === 'PUT',
  )
  await page.getByRole('button', { name: 'Save this place' }).click()
  expect((await favouriteResponse).status()).toBe(204)

  await page.getByRole('button', { name: 'Report a community contribution' }).click()
  const reportDialog = page.getByRole('dialog')
  await reportDialog.getByLabel('What are you reporting?').selectOption('contribution')
  const contributionPicker = reportDialog.getByLabel('Choose a community contribution')
  await expect(contributionPicker).toContainText(contributionText)
  await contributionPicker.selectOption({ label: contributionText })
  await reportDialog
    .getByLabel('What should our community team check?')
    .fill('Synthetic E2E report')
  const reportResponse = page.waitForResponse(
    (response) =>
      response.url().includes('/api/v1/reports') && response.request().method() === 'POST',
  )
  await reportDialog.getByRole('button', { name: 'Send report' }).click()
  expect((await reportResponse).status()).toBe(202)

  // A fresh browser session obtains saved and reportable records from new API
  // requests, hence new SQLAlchemy sessions backed by the same Postgres DB.
  const freshContext = await browser.newContext()
  await freshContext.addInitScript((token) => {
    window.__PAWLOCAL_E2E_ACCESS_TOKEN__ = token
  }, accessToken)
  const freshPage = await freshContext.newPage()
  await freshPage.goto('/')
  await expect(
    freshPage.getByRole('button', { name: 'View Synthetic Stage 3 E2E Dog Park' }),
  ).toBeVisible()
  await freshPage.getByRole('button', { name: 'View Synthetic Stage 3 E2E Dog Park' }).click()
  await expect(freshPage.getByRole('button', { name: 'Saved to your list' })).toBeVisible()
  await freshPage.getByRole('button', { name: 'Report a community contribution' }).click()
  await freshPage
    .getByRole('dialog')
    .getByLabel('What are you reporting?')
    .selectOption('contribution')
  await expect(freshPage.getByLabel('Choose a community contribution')).toContainText(
    contributionText,
  )
  await freshContext.close()
})
