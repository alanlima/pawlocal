import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import App from './App'
import { placeService } from '../services'
import { demoPlaces } from '../data/demo-places'

afterEach(() => { cleanup(); window.history.pushState({}, '', '/') })

describe('PawLocal journeys', () => {
  it('discovers places and opens a stable detail URL with unknown access called out', async () => {
    const user = userEvent.setup()
    render(<App />)
    expect(await screen.findByText('Nudgee Beach Dog Off-Leash Area')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'View Nudgee Beach Dog Off-Leash Area' }))
    expect(await screen.findByText('Dog access details are unconfirmed')).toBeInTheDocument()
    expect(window.location.pathname).toBe('/places/0d8a22c2-4316-4dd3-b25b-0baa110a1ae1')
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
    expect(await screen.findByRole('button', { name: 'Remove New Farm Park from saved places' })).toBeInTheDocument()
  })

  it('opens and validates the contribution form', async () => {
    const user = userEvent.setup()
    render(<App />)
    await screen.findByText('New Farm Park')
    await user.click(screen.getByRole('button', { name: 'Add a place' }))
    const dialog = screen.getByRole('dialog')
    expect(within(dialog).getByText(/visitor mode/i)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /Sign in/ }))
    await user.type(within(dialog).getByLabelText('Your note'), 'A helpful local tip')
    await user.click(within(dialog).getByRole('button', { name: /Share with PawLocal/ }))
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    expect(screen.getByRole('status')).toHaveTextContent('Thanks for helping the PawLocal community!')
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
    vi.spyOn(placeService, 'getPlace').mockResolvedValueOnce({ ...demoPlaces[0], dogAccessRules: 'Test fixture access note', facilities: ['Shade'], averageRating: 4.1, reviewCount: null })
    render(<App />)
    expect(await screen.findByText('Test fixture access note')).toBeInTheDocument()
    expect(screen.getByText('Shade')).toBeInTheDocument()
    expect(screen.queryByText('Facility details are unknown')).not.toBeInTheDocument()
    expect(screen.queryByText('Dog access details are unconfirmed')).not.toBeInTheDocument()
    expect(screen.getByRole('img', { name: '4.1 out of 5 stars' })).toHaveTextContent('★★★★★')
    expect(screen.getByRole('img', { name: '4.1 out of 5 stars' }).firstElementChild).toHaveStyle({ width: '82%' })
    expect(screen.getByText('Review count not provided')).toBeInTheDocument()
  })

  it('can report a contribution by its UUID', async () => {
    const user = userEvent.setup()
    const report = vi.spyOn(placeService, 'submitReport').mockResolvedValueOnce(undefined)
    render(<App />)
    await user.click(await screen.findByRole('button', { name: 'View New Farm Park' }))
    await user.click(await screen.findByRole('button', { name: /Report a community contribution/ }))
    const dialog = screen.getByRole('dialog')
    await user.click(within(dialog).getByRole('button', { name: 'Continue as demo member' }))
    await user.selectOptions(within(dialog).getByLabelText('What are you reporting?'), 'contribution')
    const id = '00000000-0000-4000-8000-000000000001'
    await user.type(within(dialog).getByLabelText('Contribution ID'), id)
    await user.type(within(dialog).getByLabelText('What should our community team check?'), 'Please review this contribution.')
    await user.click(within(dialog).getByRole('button', { name: 'Send report' }))
    await waitFor(() => expect(report).toHaveBeenCalledWith({ targetType: 'contribution', targetId: id, reason: 'Please review this contribution.' }))
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
