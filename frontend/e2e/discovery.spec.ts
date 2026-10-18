import { expect, test } from '@playwright/test'

test('search, open a stable detail URL, and share the place', async ({ page, context }) => {
  await context.grantPermissions(['clipboard-read', 'clipboard-write'])
  await page.addInitScript(() => {
    const nativeSetTimeout = window.setTimeout.bind(window)
    window.setTimeout = (handler, delay, ...args) =>
      nativeSetTimeout(handler, delay === 180 ? 1500 : delay, ...args)
  })
  await page.goto('/')
  await expect(page.getByText('Finding your places…')).toBeVisible()
  await expect(
    page.getByRole('button', { name: 'View Nudgee Beach Dog Off-Leash Area' }),
  ).toBeVisible()
  await page.getByRole('button', { name: 'View Nudgee Beach Dog Off-Leash Area' }).click()
  await expect(page.getByRole('heading', { name: 'Nudgee Beach Dog Off-Leash Area' })).toBeVisible()
  await expect(page.getByText('Dog access details are unconfirmed')).toBeVisible()
  await expect(page).toHaveURL(/\/places\/0d8a22c2-4316-4dd3-b25b-0baa110a1ae1$/)
  await page.getByRole('button', { name: 'Share this place' }).click()
  await expect(page.getByRole('status')).toContainText('Link copied')
  expect(await page.evaluate(() => navigator.clipboard.readText())).toContain(
    '/places/0d8a22c2-4316-4dd3-b25b-0baa110a1ae1',
  )
  await page.reload()
  await expect(page.getByRole('heading', { name: 'Nudgee Beach Dog Off-Leash Area' })).toBeVisible()
})

test('browser back from a place detail returns to discovery with the matching URL', async ({
  page,
}) => {
  await page.goto('/')
  await page.getByRole('button', { name: 'View New Farm Park' }).click()
  await expect(page.getByRole('heading', { name: 'New Farm Park' })).toBeVisible()
  await page.goBack()
  await expect(page).toHaveURL('/')
  await expect(page.getByLabel('Search places or areas')).toBeVisible()
  await expect(page.getByRole('heading', { name: 'New Farm Park' })).not.toBeVisible()
})

test('rapid navigation between place details keeps the rendered detail aligned with the URL', async ({
  page,
}) => {
  await page.goto('/')
  await page.getByRole('button', { name: 'View New Farm Park' }).click()
  await expect(page.getByRole('heading', { name: 'New Farm Park' })).toBeVisible()
  await page.getByRole('button', { name: 'All places' }).click()
  await expect(page).toHaveURL('/')
  await page.getByRole('button', { name: 'View Nudgee Beach Dog Off-Leash Area' }).click()
  await expect(page.getByRole('heading', { name: 'Nudgee Beach Dog Off-Leash Area' })).toBeVisible()
  await expect(page).toHaveURL(/\/places\/0d8a22c2-4316-4dd3-b25b-0baa110a1ae1$/)
})

test('search with no matches shows the empty state and can be cleared', async ({ page }) => {
  await page.goto('/')
  await page.getByLabel('Search places or areas').fill('a place that is not in demo data')
  await expect(page.getByText('No spots on this search')).toBeVisible()
  await page.getByRole('button', { name: 'Clear all filters' }).click()
  await expect(page.getByText('New Farm Park')).toBeVisible()
})

test('always shows build identity in the footer on desktop and mobile routes', async ({ page }) => {
  await page.goto('/')
  const footer = page.getByRole('contentinfo')
  await expect(footer).toContainText('BUILD local')
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  )

  await page.getByRole('button', { name: 'View New Farm Park' }).click()
  await expect(page.getByRole('heading', { name: 'New Farm Park' })).toBeVisible()
  await expect(page.getByRole('contentinfo')).toContainText('BUILD local')

  await page.setViewportSize({ width: 375, height: 812 })
  const mobileFooter = page.getByRole('contentinfo')
  await expect(mobileFooter).toContainText('BUILD local')
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  )
})

test('uses consistent artwork icons and keeps mobile hero decorations out of the footer note', async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/')

  const allPlaces = page.getByRole('button', { name: /All places/ })
  await expect(allPlaces.locator('.category-icon svg')).toBeVisible()
  await expect(page.locator('.card-art-button .art-graphic svg').first()).toBeVisible()
  await expect(page.locator('.hero-stamp')).toBeHidden()
  await expect(page.locator('.hero-doodle')).toBeHidden()
  await expect(page.locator('.hero-foot-note')).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  )
})

test('demo member can submit a review and a location suggestion', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('button', { name: 'View New Farm Park' }).click()
  await expect(page.getByRole('heading', { name: 'New Farm Park' })).toBeVisible()
  await page.getByRole('button', { name: 'Write a review' }).click()
  await page.getByRole('button', { name: 'Continue as demo member' }).click()
  await expect(page.getByRole('button', { name: 'Demo member' })).toBeVisible()
  await expect(page.getByText(/visitor mode/i)).not.toBeVisible()
  await page.getByLabel('What would you like to share?').selectOption('review')
  await page.getByRole('button', { name: 'Rate 4 stars' }).click()
  await expect(page.getByRole('button', { name: 'Rate 4 stars' })).toHaveAttribute(
    'aria-pressed',
    'true',
  )
  await page.getByLabel('Your note').fill('A thoughtful demo review.')
  await page.getByRole('button', { name: 'Share with PawLocal' }).click()
  await expect(page.getByRole('status')).toContainText('Thanks for helping the PawLocal community!')

  await page.getByRole('button', { name: 'All places' }).click()
  await expect(page.getByLabel('Search places or areas')).toBeVisible()
  await page.getByRole('button', { name: 'Add a place' }).click()
  await page.getByLabel('What would you like to share?').selectOption('location_suggestion')
  await page.getByLabel('Your note').fill('A new place to verify in demo mode.')
  await page.getByRole('button', { name: 'Share with PawLocal' }).click()
  await expect(page.getByRole('status')).toContainText('Thanks for helping the PawLocal community!')
})

test('contribution dialog contains keyboard focus and returns focus to its trigger', async ({
  page,
}) => {
  await page.goto('/')
  const trigger = page.getByRole('button', { name: 'Add a place' })
  await trigger.click()
  const dialog = page.getByRole('dialog')
  const closeButton = dialog.getByRole('button', { name: 'Close' })
  await expect(closeButton).toBeFocused()
  await page.keyboard.press('Shift+Tab')
  await expect(dialog.getByRole('button', { name: 'Cancel' })).toBeFocused()
  await page.keyboard.press('Escape')
  await expect(dialog).not.toBeVisible()
  await expect(trigger).toBeFocused()
})

test('submitted demo contributions are visible report targets and switching to place report preserves the form', async ({
  page,
}) => {
  await page.goto('/')
  await page.getByRole('button', { name: 'Add a place' }).click()
  const dialog = page.getByRole('dialog')
  await dialog.getByRole('button', { name: 'Continue as demo member' }).click()
  await expect(dialog.getByLabel('Your note')).toBeFocused()
  await dialog.getByLabel('What would you like to share?').selectOption('tip')
  await dialog.getByLabel('Your note').fill('Unique demo contribution to report')
  await dialog.getByRole('button', { name: 'Share with PawLocal' }).click()
  await expect(dialog).not.toBeVisible()

  await page.getByRole('button', { name: 'View New Farm Park' }).click()
  await page.getByRole('button', { name: /Report a community contribution/ }).click()
  const reportDialog = page.getByRole('dialog')
  const targetType = reportDialog.getByLabel('What are you reporting?')
  await targetType.selectOption('contribution')
  const contributionPicker = reportDialog.getByLabel('Choose a community contribution')
  await expect(contributionPicker).toContainText('Unique demo contribution to report')
  const contributionId = await contributionPicker.evaluate(
    (select: HTMLSelectElement) =>
      [...select.options].find((option) =>
        option.text.includes('Unique demo contribution to report'),
      )?.value ?? '',
  )
  await contributionPicker.selectOption(contributionId)
  await expect(reportDialog.getByRole('note')).toContainText('DEMO ONLY')
  await targetType.selectOption('place')
  await expect(reportDialog.getByLabel('What should our community team check?')).toBeVisible()
  await reportDialog
    .getByLabel('What should our community team check?')
    .fill('Please check this listing.')
  await reportDialog.getByRole('button', { name: 'Send report' }).click()
  await expect(page.getByRole('status')).toContainText('Your report has been sent')
})
