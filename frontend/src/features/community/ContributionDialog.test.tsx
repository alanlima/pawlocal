import { describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { ContributionDialog } from './ContributionDialog'

describe('ContributionDialog authentication actions', () => {
  it('delegates HTTP-mode sign-in to the host without offering demo-member auth', () => {
    const onSignIn = vi.fn()

    render(
      <ContributionDialog
        dialog="contribute"
        hasSelectedPlace
        signedIn={false}
        isMockBackend={false}
        kind="review"
        setKind={vi.fn()}
        rating={5}
        setRating={vi.fn()}
        message=""
        setMessage={vi.fn()}
        writeError=""
        reportTargetType="place"
        reportTargetId=""
        reportPlaceId=""
        reportableContributions={[]}
        setReportTargetType={vi.fn()}
        setReportTargetId={vi.fn()}
        onClose={vi.fn()}
        onSignIn={onSignIn}
        onSubmit={vi.fn()}
      />,
    )

    expect(screen.queryByRole('button', { name: 'Continue as demo member' })).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Sign in' }))
    expect(onSignIn).toHaveBeenCalledOnce()
  })
})
