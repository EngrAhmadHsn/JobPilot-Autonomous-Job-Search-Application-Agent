import { Button } from "@/components/ui/button"

/**
 * A page control for a list the console has already loaded.
 *
 * The total is the console's own count (the backend returns the whole list
 * for these screens), so the counter says exactly what is on screen. When
 * everything fits on one page, the control renders nothing.
 */
export function Pagination({
  page,
  pageSize,
  total,
  onPageChange,
  label,
  className,
}: {
  /** Zero-based page index. */
  page: number
  pageSize: number
  total: number
  onPageChange: (page: number) => void
  /** What is being counted, for the counter ("résumés", "entries"). */
  label?: string
  className?: string
}) {
  if (total <= pageSize) return null

  const pages = Math.max(1, Math.ceil(total / pageSize))
  const first = page * pageSize + 1
  const last = Math.min(total, (page + 1) * pageSize)

  return (
    <div
      className={
        "flex flex-wrap items-center justify-between gap-3 pt-1 " + (className ?? "")
      }
    >
      <p className="text-xs text-muted-foreground tabular-nums">
        {first}–{last} of {total}
        {label ? ` ${label}` : ""}
      </p>
      <div className="flex items-center gap-2">
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={page === 0}
          onClick={() => onPageChange(page - 1)}
        >
          Previous
        </Button>
        <span className="text-xs text-muted-foreground tabular-nums">
          Page {page + 1} of {pages}
        </span>
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={page + 1 >= pages}
          onClick={() => onPageChange(page + 1)}
        >
          Next
        </Button>
      </div>
    </div>
  )
}