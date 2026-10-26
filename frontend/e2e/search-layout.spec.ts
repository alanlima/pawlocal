import { expect, test, type Page } from '@playwright/test'
import { demoPlaces } from '../src/data/demo-places'

const geometry = (page: Page, selector: string) => page.locator(selector).boundingBox()
for (const width of [1440, 768, 390]) {
  test(`stable search frame at ${width}px`, async ({ page }) => {
    await page.addInitScript('window.__pauseSearch = true')
    await page.setViewportSize({ width, height: 1000 })
    const longName = `Long fixture ${'Unbroken'.repeat(35)} walking trail`
    await page.route('**/src/data/demo-places.ts', (route) =>
      route.fulfill({
        contentType: 'application/javascript',
        body: `export const demoPlaces = ${JSON.stringify([...demoPlaces, ...Array.from({ length: 20 }, (_, index) => ({ ...demoPlaces[0], id: `filler-${index}`, name: `Filler ${index}` })), { ...demoPlaces[0], id: 'long-fixture', name: longName }])}`,
      }),
    )
    await page.route('**/src/services/MockPlaceService.ts', async (route) => {
      const response = await route.fetch()
      await route.fulfill({
        response,
        body: (await response.text()).replace(
          'await wait(180, signal);',
          'while (globalThis.__pauseSearch) await wait(10, signal); await wait(900, signal); if (query.q === "fixture-error") throw new Error("test failure");',
        ),
      })
    })
    await page.goto('/')
    await expect(page.getByLabel('Loading places')).toBeVisible()
    const initial = await geometry(page, '.content-wrap')
    await page.evaluate('window.__pauseSearch = false')
    await expect(page.getByRole('article')).toHaveCount(20)
    await page.evaluate(() => document.fonts.ready)
    const baseline = await geometry(page, '.content-wrap')
    expect(baseline!.width).toBeCloseTo(initial!.width, 1)
    const stable = async () => {
      const frame = await geometry(page, '.content-wrap')
      expect(frame!.x).toBeCloseTo(baseline!.x, 1)
      expect(frame!.width).toBeCloseTo(baseline!.width, 1)
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
        true,
      )
    }
    await page.getByRole('button', { name: 'Next', exact: true }).click()
    await expect(page.getByRole('article')).toHaveCount(13)
    const grid = await geometry(page, '.place-grid')
    const banner = await geometry(page, '.community-banner')
    const input = page.getByLabel('Search places or areas')
    await input.fill('New Farm')
    await expect(page.getByText(/Previous results are shown below/)).toBeVisible()
    await expect(page.getByRole('region', { name: 'Places', exact: true })).toHaveAttribute(
      'aria-busy',
      'true',
    )
    await expect(page.getByRole('article')).toHaveCount(13)
    expect(await geometry(page, '.place-grid')).toEqual(grid)
    expect(await geometry(page, '.community-banner')).toEqual(banner)
    await stable()
    await expect(page.getByRole('article')).toHaveCount(1)
    await stable()
    const card = await geometry(page, '.place-card')
    const columns = width <= 650 ? 2 : width <= 900 ? 3 : 4
    expect(card!.width).toBeCloseTo(
      (grid!.width - (columns - 1) * (width <= 650 ? 10 : 15)) / columns,
      1,
    )
    expect(
      await page.getByRole('article').evaluate((el) => getComputedStyle(el).animationName),
    ).toBe('none')
    await input.fill('zero-fixture')
    await expect(page.getByText('No spots on this search')).toBeVisible()
    await stable()
    const emptyHeight = (await geometry(page, '.discovery-results'))!.height
    expect(emptyHeight).toBeGreaterThanOrEqual(width <= 650 ? 310 : 340)
    expect(emptyHeight).toBeLessThan(500)
    const emptyFrame = await geometry(page, '.discovery-results')
    const emptyBanner = await geometry(page, '.community-banner')
    await page.getByRole('button', { name: 'Clear all filters' }).click()
    await expect(page.getByText(/Finding your places/)).toBeVisible()
    expect(await geometry(page, '.discovery-results')).toEqual(emptyFrame)
    expect(await geometry(page, '.community-banner')).toEqual(emptyBanner)
    await expect(page.getByRole('article')).toHaveCount(20)
    await input.fill('New Farm')
    await input.fill('Nudgee')
    await expect(page.getByRole('article')).toHaveCount(1)
    await expect(
      page.getByRole('button', { name: 'View Nudgee Beach Dog Off-Leash Area' }),
    ).toBeVisible()
    await stable()
    await input.fill('Long fixture')
    await expect(page.getByText(longName, { exact: true })).toBeVisible()
    await stable()
    expect(
      await page
        .locator('.place-name')
        .evaluate((el) => el.scrollHeight <= el.clientHeight && el.scrollWidth <= el.clientWidth),
    ).toBe(true)
    await input.fill('fixture-error')
    await expect(page.getByText("We couldn't find the places")).toBeVisible()
    await stable()
    await page.getByRole('button', { name: 'Try again' }).click()
    await expect(page.getByText(/Finding your places/)).toBeVisible()
    await input.fill('New Farm')
    await expect(page.getByRole('article')).toHaveCount(1)
    await stable()
    console.log(JSON.stringify({ width, frame: baseline, oneCardWidth: card!.width, emptyHeight }))
  })
}
