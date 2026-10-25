import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import App from './App'
import { placeService } from '../services'
import { demoPlaces } from '../data/demo-places'

// Synthetic records stay in tests; they are never published as directory listings.
const places = Array.from({ length: 105 }, (_, index) => ({
  ...demoPlaces[0],
  id: `pagination-fixture-${index + 1}`,
  name: `Pagination fixture ${index + 1}`,
}))
const pagination = () => screen.getByRole('navigation', { name: 'Place list pagination' })
const cards = () => screen.getAllByRole('article')

beforeEach(() => {
  vi.spyOn(placeService, 'listPlaces').mockResolvedValue(places)
  vi.spyOn(placeService, 'listFavourites').mockResolvedValue(places.map((place) => place.id))
})

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
  window.history.pushState({}, '', '/')
})

describe('place list pagination', { timeout: 20_000 }, () => {
  it('keeps the selector available for a single result with both boundaries disabled', async () => {
    vi.mocked(placeService.listPlaces).mockResolvedValue(places.slice(0, 1))
    render(<App />)
    await screen.findByText(/Showing 1–1 of 1 places/)
    expect(screen.getByLabelText('Places per page')).toHaveValue('20')
    expect(screen.getByRole('button', { name: 'Previous' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Next' })).toBeDisabled()
  })

  it('shows 20 by default and traverses every result without omissions or duplicates', async () => {
    const user = userEvent.setup()
    render(<App />)
    await screen.findByText(/Showing 1–20 of 105 places/)
    expect(cards()).toHaveLength(20)
    expect(screen.getByRole('button', { name: 'Previous' })).toBeDisabled()
    const names: string[] = []
    for (let page = 1; page <= 6; page++) {
      expect(pagination()).toHaveTextContent(`Page ${page} of 6`)
      names.push(
        ...cards().map((card) =>
          within(card)
            .getByRole('button', { name: /^View / })
            .getAttribute('aria-label')!,
        ),
      )
      if (page < 6) await user.click(screen.getByRole('button', { name: 'Next' }))
    }
    expect(names).toEqual(places.map((place) => `View ${place.name}`))
    expect(cards()).toHaveLength(5)
    expect(pagination()).toHaveTextContent('Showing 101–105 of 105 places')
    expect(screen.getByRole('button', { name: 'Next' })).toBeDisabled()
    await user.click(screen.getByRole('button', { name: 'Previous' }))
    expect(pagination()).toHaveTextContent('Showing 81–100 of 105 places')
    expect(placeService.listPlaces).toHaveBeenCalledTimes(1)
  })

  it('offers exactly the five requested sizes and resets each size change to page one', async () => {
    const user = userEvent.setup()
    render(<App />)
    await screen.findByText(/Showing 1–20/)
    const selector = screen.getByLabelText('Places per page')
    expect(
      within(selector)
        .getAllByRole('option')
        .map((option) => option.textContent),
    ).toEqual(['20', '40', '60', '80', '100'])
    for (const size of [40, 60, 80, 100, 20]) {
      await user.click(screen.getByRole('button', { name: 'Next' }))
      await user.selectOptions(selector, `${size}`)
      expect(cards()).toHaveLength(size)
      expect(pagination()).toHaveTextContent(`Showing 1–${size} of 105 places`)
      expect(screen.getByRole('button', { name: 'Previous' })).toBeDisabled()
    }
  })

  it('resets search, area, category, facility and view changes without losing the chosen size', async () => {
    const user = userEvent.setup()
    render(<App />)
    await screen.findByText(/Showing 1–20/)
    await user.selectOptions(screen.getByLabelText('Places per page'), '40')
    const changes = [
      () => user.type(screen.getByLabelText('Search places or areas'), 'x'),
      () => user.selectOptions(screen.getByLabelText('Select an area'), 'Brisbane City'),
      () => user.click(screen.getByRole('button', { name: /Dog parks/ })),
      async () => {
        await user.click(screen.getByRole('button', { name: 'Filters' }))
        await user.click(screen.getByLabelText('Fenced'))
      },
      () => user.click(screen.getByRole('button', { name: 'Saved places' })),
      () => user.click(screen.getByRole('button', { name: 'Explore' })),
    ]
    for (const change of changes) {
      await user.click(screen.getByRole('button', { name: 'Next' }))
      await change()
      await waitFor(() => expect(pagination()).toHaveTextContent('Showing 1–40 of 105 places'))
      expect(screen.getByLabelText('Places per page')).toHaveValue('40')
    }
  })

  it('returns from details to the same page and size', async () => {
    const user = userEvent.setup()
    vi.spyOn(placeService, 'getPlace').mockResolvedValue(places[40])
    render(<App />)
    await screen.findByText(/Showing 1–20/)
    await user.selectOptions(screen.getByLabelText('Places per page'), '40')
    await user.click(screen.getByRole('button', { name: 'Next' }))
    await user.click(screen.getByRole('button', { name: 'View Pagination fixture 41' }))
    await screen.findByRole('heading', { name: 'Pagination fixture 41' })
    await user.click(screen.getByRole('button', { name: 'All places' }))
    expect(pagination()).toHaveTextContent('Showing 41–80 of 105 places · Page 2 of 3')
    expect(screen.getByLabelText('Places per page')).toHaveValue('40')
  })

  it('clamps the last favourites page after its only saved place is removed', async () => {
    const user = userEvent.setup()
    vi.mocked(placeService.listFavourites).mockResolvedValue(
      places.slice(0, 21).map((place) => place.id),
    )
    vi.spyOn(placeService, 'toggleFavourite').mockResolvedValue(undefined)
    render(<App />)
    await screen.findByText(/Showing 1–20/)
    await user.click(screen.getByRole('button', { name: 'Sign in' }))
    await user.click(screen.getByRole('button', { name: 'Saved places' }))
    await user.click(screen.getByRole('button', { name: 'Next' }))
    expect(cards()).toHaveLength(1)
    vi.mocked(placeService.listFavourites).mockResolvedValue(
      places.slice(0, 20).map((place) => place.id),
    )
    await user.click(
      screen.getByRole('button', { name: 'Remove Pagination fixture 21 from saved places' }),
    )
    await waitFor(() =>
      expect(pagination()).toHaveTextContent('Showing 1–20 of 20 places · Page 1 of 1'),
    )
    expect(cards()).toHaveLength(20)
    expect(screen.getByRole('button', { name: 'Next' })).toBeDisabled()
  })

  it.each(['empty', 'error', 'loading'] as const)(
    'preserves the %s state without stale pagination controls',
    async (state) => {
      if (state === 'empty') vi.mocked(placeService.listPlaces).mockResolvedValue([])
      if (state === 'error')
        vi.mocked(placeService.listPlaces).mockRejectedValue(new Error('test failure'))
      if (state === 'loading')
        vi.mocked(placeService.listPlaces).mockReturnValue(new Promise(() => {}))
      render(<App />)
      if (state === 'empty') await screen.findByText('No spots on this search')
      if (state === 'error') await screen.findByText("We couldn't find the places")
      if (state === 'loading') expect(screen.getByLabelText('Loading places')).toBeVisible()
      expect(
        screen.queryByRole('navigation', { name: 'Place list pagination' }),
      ).not.toBeInTheDocument()
    },
  )
})
