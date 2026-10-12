export const RECORDS_PER_PAGE = 10;

type RecordPaginationProps = {
  page: number;
  pageSize: number;
  totalItems: number;
  label: string;
  onPageChange: (page: number) => void;
};

export default function RecordPagination({
  page,
  pageSize,
  totalItems,
  label,
  onPageChange,
}: RecordPaginationProps) {
  const totalPages = Math.ceil(totalItems / pageSize);
  if (totalPages <= 1) return null;

  const firstItem = (page - 1) * pageSize + 1;
  const lastItem = Math.min(page * pageSize, totalItems);

  return (
    <nav className="pagination" aria-label={label}>
      <span>Showing {firstItem}–{lastItem} of {totalItems}</span>
      <button type="button" disabled={page <= 1} onClick={() => onPageChange(page - 1)}>
        Previous
      </button>
      <span aria-live="polite">Page {page} of {totalPages}</span>
      <button type="button" disabled={page >= totalPages} onClick={() => onPageChange(page + 1)}>
        Next
      </button>
    </nav>
  );
}
