import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Pagination } from './Pagination'

afterEach(cleanup)

describe('shared pagination', () => {
  it('supports another entity through caller labels and reports navigation and size changes', async () => {
    const user = userEvent.setup()
    const onPageChange = vi.fn()
    const onPageSizeChange = vi.fn()
    const props = {
      page: 2,
      pageSize: 20,
      total: 45,
      itemLabel: 'reviews',
      pageSizeLabel: 'Reviews per page',
      ariaLabel: 'Review list pagination',
      onPageChange,
      onPageSizeChange,
    }
    const { rerender } = render(<Pagination {...props} />)
    expect(screen.getByRole('navigation', { name: 'Review list pagination' })).toHaveTextContent(
      'Showing 21–40 of 45 reviews · Page 2 of 3',
    )
    expect(screen.queryByText(/places/i)).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Previous' }))
    expect(onPageChange).toHaveBeenLastCalledWith(1)
    await user.click(screen.getByRole('button', { name: 'Next' }))
    expect(onPageChange).toHaveBeenLastCalledWith(3)
    await user.selectOptions(screen.getByLabelText('Reviews per page'), '60')
    expect(onPageSizeChange).toHaveBeenCalledWith(60)

    rerender(<Pagination {...props} page={1} />)
    expect(screen.getByRole('button', { name: 'Previous' })).toBeDisabled()
    rerender(<Pagination {...props} page={3} />)
    expect(screen.getByRole('button', { name: 'Next' })).toBeDisabled()
    expect(screen.getByText(/Showing 41–45 of 45 reviews/)).toBeVisible()
  })

  it('uses generic defaults and represents an empty collection without invalid ranges', () => {
    render(
      <Pagination
        page={1}
        pageSize={20}
        total={0}
        onPageChange={vi.fn()}
        onPageSizeChange={vi.fn()}
      />,
    )
    expect(screen.getByRole('navigation', { name: 'Pagination' })).toHaveTextContent(
      'Showing 0–0 of 0 items · Page 1 of 1',
    )
    expect(screen.getByLabelText('Items per page')).toHaveValue('20')
    expect(screen.getByRole('button', { name: 'Previous' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Next' })).toBeDisabled()
  })
})
