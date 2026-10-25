import './pagination.css'

type Props = {
  itemLabel?: string
  pageSizeLabel?: string
  ariaLabel?: string
  page: number
  pageSize: number
  total: number
  onPageChange: (page: number) => void
  onPageSizeChange: (size: number) => void
}

export function Pagination({
  page,
  pageSize,
  total,
  onPageChange,
  onPageSizeChange,
  itemLabel = 'items',
  pageSizeLabel = 'Items per page',
  ariaLabel = 'Pagination',
}: Props) {
  const totalPages = Math.max(1, Math.ceil(total / pageSize))
  return (
    <nav className="pagination" aria-label={ariaLabel}>
      <label className="page-size">
        {pageSizeLabel}
        <select value={pageSize} onChange={(event) => onPageSizeChange(Number(event.target.value))}>
          {[20, 40, 60, 80, 100].map((size) => (
            <option key={size} value={size}>
              {size}
            </option>
          ))}
        </select>
      </label>
      <span className="page-range" aria-live="polite" aria-atomic="true">
        Showing {total === 0 ? 0 : (page - 1) * pageSize + 1}–{Math.min(page * pageSize, total)} of{' '}
        {total} {itemLabel}
        {' · '}Page {page} of {totalPages}
      </span>
      <div className="page-navigation">
        <button type="button" disabled={page <= 1} onClick={() => onPageChange(page - 1)}>
          Previous
        </button>
        <button type="button" disabled={page >= totalPages} onClick={() => onPageChange(page + 1)}>
          Next
        </button>
      </div>
    </nav>
  )
}
