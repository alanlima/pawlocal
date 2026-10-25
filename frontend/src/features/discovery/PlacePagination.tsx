import './placePagination.css'

type Props = {
  page: number
  pageSize: number
  total: number
  onPageChange: (page: number) => void
  onPageSizeChange: (size: number) => void
}

export function PlacePagination({ page, pageSize, total, onPageChange, onPageSizeChange }: Props) {
  const totalPages = Math.ceil(total / pageSize)
  return (
    <nav className="place-pagination" aria-label="Place list pagination">
      <label className="page-size">
        Places per page
        <select value={pageSize} onChange={(event) => onPageSizeChange(Number(event.target.value))}>
          {[20, 40, 60, 80, 100].map((size) => (
            <option key={size} value={size}>
              {size}
            </option>
          ))}
        </select>
      </label>
      <span className="page-range" aria-live="polite" aria-atomic="true">
        Showing {(page - 1) * pageSize + 1}–{Math.min(page * pageSize, total)} of {total} places
        {' · '}Page {page} of {totalPages}
      </span>
      <div className="page-navigation">
        <button type="button" disabled={page === 1} onClick={() => onPageChange(page - 1)}>
          Previous
        </button>
        <button type="button" disabled={page === totalPages} onClick={() => onPageChange(page + 1)}>
          Next
        </button>
      </div>
    </nav>
  )
}
