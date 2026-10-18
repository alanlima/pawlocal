import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import App from './App'
import { placeService } from '../services'
import { demoContributions } from '../data/demo-contributions'
import { demoPlaces } from '../data/demo-places'

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
  window.history.pushState({}, '', '/')
})

describe('PawLocal journeys', () => {
  it('keeps the build identity in the footer on discovery and place-detail pages', async () => {
    const user = userEvent.setup()
    render(<App />)
    expect(await screen.findByRole('contentinfo')).toHaveTextContent('BUILD local')

    await user.click(await screen.findByRole('button', { name: 'View New Farm Park' }))
    expect(await screen.findByRole('heading', { name: 'New Farm Park' })).toBeVisible()
    expect(screen.getByRole('contentinfo')).toHaveTextContent('BUILD local')
  })

  it('discovers places and opens a stable detail URL with unknown access called out', async () => {
    const user = userEvent.setup()
    render(<App />)
    expect(await screen.findByText('Nudgee Beach Dog Off-Leash Area')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'View Nudgee Beach Dog Off-Leash Area' }))
    expect(await screen.findByText('Dog access details are unconfirmed')).toBeInTheDocument()
    expect(window.location.pathname).toBe('/places/0d8a22c2-4316-4dd3-b25b-0baa110a1ae1')
  })

  it('ignores a detail response after navigating back to discovery', async () => {
    const user = userEvent.setup()
    let resolvePlace!: (place: (typeof demoPlaces)[number] | null) => void
    vi.spyOn(placeService, 'getPlace').mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          resolvePlace = resolve
        }),
    )
    render(<App />)
    const place = demoPlaces.find((item) => item.name === 'New Farm Park')!
    await user.click(await screen.findByRole('button', { name: 'View New Farm Park' }))
    expect(window.location.pathname).toBe(`/places/${place.id}`)

    window.history.pushState({}, '', '/')
    window.dispatchEvent(new PopStateEvent('popstate'))
    resolvePlace(place)

    await waitFor(() => expect(screen.getByLabelText('Search places or areas')).toBeVisible())
    expect(screen.queryByRole('heading', { name: 'New Farm Park' })).not.toBeInTheDocument()
    expect(window.location.pathname).toBe('/')
  })

  it('keeps the newer place when an earlier detail response resolves last', async () => {
    const user = userEvent.setup()
    let resolveFirst!: (place: (typeof demoPlaces)[number] | null) => void
    const first = demoPlaces.find((item) => item.name === 'New Farm Park')!
    const second = demoPlaces.find((item) => item.name === 'Nudgee Beach Dog Off-Leash Area')!
    vi.spyOn(placeService, 'getPlace')
      .mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            resolveFirst = resolve
          }),
      )
      .mockResolvedValueOnce(second)
    render(<App />)
    await user.click(await screen.findByRole('button', { name: `View ${first.name}` }))
    await user.click(screen.getByRole('button', { name: `View ${second.name}` }))
    expect(await screen.findByRole('heading', { name: second.name })).toBeVisible()
    resolveFirst(first)

    await waitFor(() => expect(screen.getByRole('heading', { name: second.name })).toBeVisible())
    expect(screen.queryByRole('heading', { name: first.name })).not.toBeInTheDocument()
    expect(window.location.pathname).toBe(`/places/${second.id}`)
  })

  it('filters by category and shows a clear empty state', async () => {
    const user = userEvent.setup()
    render(<App />)
    await screen.findByText('New Farm Park')
    await user.click(screen.getByRole('button', { name: /Cafés/ }))
    expect(await screen.findByText('The Rabbit Hole')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /Dog parks/ }))
    const search = screen.getByLabelText('Search places or areas')
    await user.type(search, 'nothing matches')
    expect(await screen.findByText('No spots on this search')).toBeInTheDocument()
  })

  it('requires the demo member state before saving a favourite', async () => {
    const user = userEvent.setup()
    render(<App />)
    await screen.findByText('New Farm Park')
    await user.click(screen.getByRole('button', { name: 'Save New Farm Park' }))
    expect(screen.getByRole('status')).toHaveTextContent('Sign in to save favourites.')
    await user.click(screen.getByRole('button', { name: /Sign in/ }))
    await user.click(screen.getByRole('button', { name: 'Save New Farm Park' }))
    expect(
      await screen.findByRole('button', { name: 'Remove New Farm Park from saved places' }),
    ).toBeInTheDocument()
  })

  it('opens and validates the contribution form', async () => {
    const user = userEvent.setup()
    render(<App />)
    await screen.findByText('New Farm Park')
    await user.click(screen.getByRole('button', { name: 'Add a place' }))
    const dialog = screen.getByRole('dialog')
    expect(within(dialog).getByText(/visitor mode/i)).toBeInTheDocument()
    await user.click(within(dialog).getByRole('button', { name: 'Continue as demo member' }))
    const note = within(dialog).getByLabelText('Your note')
    expect(note).toHaveFocus()
    await user.type(note, 'A helpful local tip')
    await user.click(within(dialog).getByRole('button', { name: /Share with PawLocal/ }))
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    expect(screen.getByRole('status')).toHaveTextContent(
      'Thanks for helping the PawLocal community!',
    )
  })

  it('offers only place suggestions from the global Add a place dialog', async () => {
    const user = userEvent.setup()
    render(<App />)
    await screen.findByText('New Farm Park')
    await user.click(screen.getByRole('button', { name: 'Add a place' }))

    const dialog = within(screen.getByRole('dialog'))
    const kind = dialog.getByLabelText('What would you like to share?')
    expect(within(kind).queryByRole('option', { name: 'A review' })).not.toBeInTheDocument()
    expect(within(kind).getByRole('option', { name: 'Suggest a place' })).toBeInTheDocument()
  })

  it('continues to offer reviews from a selected place detail', async () => {
    const user = userEvent.setup()
    render(<App />)
    await user.click(await screen.findByRole('button', { name: 'View New Farm Park' }))
    await user.click(await screen.findByRole('button', { name: 'Write a review' }))

    const dialog = within(screen.getByRole('dialog'))
    expect(
      within(dialog.getByLabelText('What would you like to share?')).getByRole('option', {
        name: 'A review',
      }),
    ).toBeInTheDocument()
  })

  it('does not submit a stale review after its selected place disappears', async () => {
    const user = userEvent.setup()
    const submitContribution = vi.spyOn(placeService, 'submitContribution')
    render(<App />)
    await user.click(await screen.findByRole('button', { name: 'View New Farm Park' }))
    await user.click(await screen.findByRole('button', { name: 'Write a review' }))
    const dialog = within(screen.getByRole('dialog'))
    await user.click(dialog.getByRole('button', { name: 'Continue as demo member' }))

    window.history.pushState({}, '', '/')
    window.dispatchEvent(new PopStateEvent('popstate'))
    await waitFor(() =>
      expect(dialog.getByLabelText('What would you like to share?')).toHaveValue(
        'location_suggestion',
      ),
    )
    await user.type(dialog.getByLabelText('Your note'), 'A review without its place')
    await user.click(dialog.getByRole('button', { name: /Share with PawLocal/ }))

    expect(await dialog.findByRole('alert')).toHaveTextContent(
      'Choose a place before submitting a review.',
    )
    expect(submitContribution).not.toHaveBeenCalled()
  })

  it('shows an API error state and recovers on retry', async () => {
    const user = userEvent.setup()
    vi.spyOn(placeService, 'listPlaces').mockRejectedValueOnce(new Error('offline'))
    render(<App />)
    expect(await screen.findByText("We couldn't find the places")).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Try again' }))
    expect(await screen.findByText('New Farm Park')).toBeInTheDocument()
  })

  it('shows provided access and facilities, and renders stars to the supplied rating', async () => {
    window.history.pushState({}, '', `/places/${demoPlaces[0].id}`)
    vi.spyOn(placeService, 'getPlace').mockResolvedValueOnce({
      ...demoPlaces[0],
      dogAccessRules: 'Test fixture access note',
      facilities: ['Shade'],
      averageRating: 4.1,
      reviewCount: null,
    })
    render(<App />)
    expect(await screen.findByText('Test fixture access note')).toBeInTheDocument()
    expect(screen.getByText('Shade')).toBeInTheDocument()
    expect(screen.queryByText('Facility details are unknown')).not.toBeInTheDocument()
    expect(screen.queryByText('Dog access details are unconfirmed')).not.toBeInTheDocument()
    expect(screen.getByRole('img', { name: '4.1 out of 5 stars' })).toHaveTextContent('★★★★★')
    expect(screen.getByRole('img', { name: '4.1 out of 5 stars' }).firstElementChild).toHaveStyle({
      width: '82%',
    })
    expect(screen.getByText('Review count not provided')).toBeInTheDocument()
  })

  it('can select a visible demo contribution, then restore place reporting with the place ID', async () => {
    const user = userEvent.setup()
    const listReportableContributions = vi.spyOn(placeService, 'listReportableContributions')
    const report = vi.spyOn(placeService, 'submitReport').mockResolvedValueOnce(undefined)
    render(<App />)
    await user.click(await screen.findByRole('button', { name: 'View New Farm Park' }))
    await user.click(await screen.findByRole('button', { name: /Report a community contribution/ }))
    const dialog = screen.getByRole('dialog')
    await user.click(within(dialog).getByRole('button', { name: 'Continue as demo member' }))
    await user.selectOptions(
      within(dialog).getByLabelText('What are you reporting?'),
      'contribution',
    )
    await waitFor(() => expect(listReportableContributions).toHaveBeenCalledOnce())
    await screen.findByLabelText('Choose a community contribution')
    await user.selectOptions(
      within(dialog).getByLabelText('Choose a community contribution'),
      '00000000-0000-4000-8000-000000000099',
    )
    expect(within(dialog).getByRole('note')).toHaveTextContent('DEMO ONLY')
    await user.selectOptions(within(dialog).getByLabelText('What are you reporting?'), 'place')
    expect(
      within(dialog).queryByLabelText('Choose a community contribution'),
    ).not.toBeInTheDocument()
    expect(within(dialog).getByLabelText('What should our community team check?')).toBeVisible()
    await user.type(
      within(dialog).getByLabelText('What should our community team check?'),
      'Please review this contribution.',
    )
    await user.click(within(dialog).getByRole('button', { name: 'Send report' }))
    await waitFor(() =>
      expect(report).toHaveBeenCalledWith({
        targetType: 'place',
        targetId: demoPlaces.find((place) => place.name === 'New Farm Park')?.id,
        reason: 'Please review this contribution.',
      }),
    )
  })

  it('shows a loading state while reportable contributions are pending', async () => {
    const user = userEvent.setup()
    vi.spyOn(placeService, 'listReportableContributions').mockImplementation(
      () => new Promise(() => {}),
    )
    render(<App />)
    await user.click(await screen.findByRole('button', { name: 'View New Farm Park' }))
    await user.click(await screen.findByRole('button', { name: /Report a community contribution/ }))
    const dialog = within(screen.getByRole('dialog'))
    await user.selectOptions(dialog.getByLabelText('What are you reporting?'), 'contribution')

    expect(await dialog.findByRole('status')).toHaveTextContent('Loading published contributions…')
    expect(
      dialog.queryByText('No published community contributions are available to report yet.'),
    ).not.toBeInTheDocument()
  })

  it('shows a retryable error when reportable contributions fail to load', async () => {
    const user = userEvent.setup()
    vi.spyOn(placeService, 'listReportableContributions').mockRejectedValueOnce(
      new Error('offline'),
    )
    render(<App />)
    await user.click(await screen.findByRole('button', { name: 'View New Farm Park' }))
    await user.click(await screen.findByRole('button', { name: /Report a community contribution/ }))
    const dialog = within(screen.getByRole('dialog'))
    await user.selectOptions(dialog.getByLabelText('What are you reporting?'), 'contribution')

    expect(await dialog.findByRole('alert')).toHaveTextContent(
      'We couldn’t load published contributions. Please try again.',
    )
    expect(
      dialog.queryByText('No published community contributions are available to report yet.'),
    ).not.toBeInTheDocument()
  })

  it('retries a failed reportable contribution request and displays returned targets', async () => {
    const user = userEvent.setup()
    const listReportableContributions = vi
      .spyOn(placeService, 'listReportableContributions')
      .mockRejectedValueOnce(new Error('offline'))
      .mockResolvedValueOnce(demoContributions)
    render(<App />)
    await user.click(await screen.findByRole('button', { name: 'View New Farm Park' }))
    await user.click(await screen.findByRole('button', { name: /Report a community contribution/ }))
    const dialog = within(screen.getByRole('dialog'))
    await user.selectOptions(dialog.getByLabelText('What are you reporting?'), 'contribution')
    await dialog.findByRole('alert')
    await user.click(dialog.getByRole('button', { name: 'Try again' }))

    const picker = await dialog.findByLabelText('Choose a community contribution')
    expect(picker).toHaveValue(demoContributions[0].id)
    expect(picker).toHaveTextContent(demoContributions[0].body)
    expect(listReportableContributions).toHaveBeenCalledTimes(2)
  })

  it('shows a valid empty result after reportable contributions load successfully', async () => {
    const user = userEvent.setup()
    vi.spyOn(placeService, 'listReportableContributions').mockResolvedValueOnce([])
    render(<App />)
    await user.click(await screen.findByRole('button', { name: 'View New Farm Park' }))
    await user.click(await screen.findByRole('button', { name: /Report a community contribution/ }))
    const dialog = within(screen.getByRole('dialog'))
    await user.selectOptions(dialog.getByLabelText('What are you reporting?'), 'contribution')

    expect(await dialog.findByRole('status')).toHaveTextContent(
      'No published community contributions are available to report yet.',
    )
    expect(dialog.queryByRole('alert')).not.toBeInTheDocument()
    expect(dialog.queryByRole('button', { name: 'Try again' })).not.toBeInTheDocument()
  })

  it('keeps contribution text and shows a helpful message when submit fails', async () => {
    const user = userEvent.setup()
    vi.spyOn(placeService, 'submitContribution').mockRejectedValueOnce(new Error('offline'))
    render(<App />)
    await screen.findByText('New Farm Park')
    await user.click(screen.getByRole('button', { name: 'Add a place' }))
    const dialog = screen.getByRole('dialog')
    await user.click(within(dialog).getByRole('button', { name: 'Continue as demo member' }))
    const note = within(dialog).getByLabelText('Your note')
    await user.type(note, 'Keep this note if sending fails.')
    await user.click(within(dialog).getByRole('button', { name: 'Share with PawLocal' }))
    expect(await within(dialog).findByRole('alert')).toHaveTextContent('Your note is still here')
    expect(note).toHaveValue('Keep this note if sending fails.')
  })

  it('does not show an unsupported proximity control', async () => {
    render(<App />)
    await screen.findByText('New Farm Park')
    expect(screen.queryByRole('button', { name: 'Near me' })).not.toBeInTheDocument()
  })
})
