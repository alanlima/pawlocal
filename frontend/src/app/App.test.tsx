import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import App from './App'
import { placeService } from '../services'

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
})
