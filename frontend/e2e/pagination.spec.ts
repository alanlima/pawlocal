import { expect, test } from '@playwright/test'
import { demoPlaces } from '../src/data/demo-places'

test('paginates a large directory with keyboard controls and preserves detail return on mobile', async ({
  page,
}) => {
  const places = Array.from({ length: 105 }, (_, index) => ({
    ...demoPlaces[0],
    id: `pagination-fixture-${index + 1}`,
    name: `Pagination fixture ${index + 1}`,
  }))
  // Replace only the mock data module in this browser, without production test hooks.
  await page.route('**/src/data/demo-places.ts', (route) =>
    route.fulfill({
      contentType: 'application/javascript',
      body: `export const demoPlaces = ${JSON.stringify(places)}`,
    }),
  )
  await page.goto('/')
  const pagination = page.getByRole('navigation', { name: 'Place list pagination' })
  await expect(pagination).toContainText('Showing 1–20 of 105 places · Page 1 of 6')
  await expect(page.getByRole('article')).toHaveCount(20)
  await expect(page.getByRole('button', { name: 'Previous', exact: true })).toBeDisabled()
  await page.getByLabel('Places per page').focus()
  await page.keyboard.press('ArrowDown')
  await page.keyboard.press('Enter')
  await expect(page.getByLabel('Places per page')).toHaveValue('40')
  await expect(page.getByRole('article')).toHaveCount(40)
  await page.getByRole('button', { name: 'Next', exact: true }).focus()
  await page.keyboard.press('Enter')
  await expect(pagination).toContainText('Showing 41–80 of 105 places · Page 2 of 3')
  await page.getByRole('button', { name: 'View Pagination fixture 41', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Pagination fixture 41' })).toBeVisible()
  await page.goBack()
  await expect(pagination).toContainText('Showing 41–80 of 105 places · Page 2 of 3')
  await page.getByRole('button', { name: 'Next', exact: true }).click()
  await expect(pagination).toContainText('Showing 81–105 of 105 places · Page 3 of 3')
  await expect(page.getByRole('article')).toHaveCount(25)
  await expect(page.getByRole('button', { name: 'Next', exact: true })).toBeDisabled()
  await page.setViewportSize({ width: 375, height: 812 })
  await pagination.scrollIntoViewIfNeeded()
  await expect(page.getByLabel('Places per page')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Previous', exact: true })).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  )
})
