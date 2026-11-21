import { Button } from "@/components/ui/button"
import { cn } from "cn"

/**
 * A page control for a list the console has already loaded.
 *
 * The total is the console's own count (the backend returns the whole list
 * for these screens), so the counter says exactly what is on screen. When
 * everything fits on one page, the control renders nothing.
 *
 * WS-48: the root sits on the canonical base-nova pagination shell — a
 * `<nav role="navigation" aria-label="pagination" data-slot="pagination">`.
 * The canonical base's page-link parts (`PaginationLink` renders anchors
 * through `Button render`) don't fit a console whose lists are already
 * loaded in memory, so only the shell is adopted; the buttons and the
 * counter keep their measured layout classes, and the prop API is
 * unchanged.
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
    <nav
      role="navigation"
      aria-label="pagination"
      data-slot="pagination"
      className={cn(
        "flex flex-wrap items-center justify-between gap-3 pt-1",
        className
      )}
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
    </nav>
  )
}

import { ChevronLeft, ChevronRight } from "lucide-react"

/**
 * The design's table pager (nodes 49:2420–49:2428): the range on the left;
 * on the right a page-size control ("Rows 10"), the ‹/› pills (35×39,
 * disabled at 40% opacity) and the current-page chip (41×24, sage wash).
 *
 * The old `Pagination` above stays for the list controls that already use
 * it; the tables take this one, whose geometry is the component sets'.
 */
export function TablePager({
  page,
  pageSize,
  total,
  onPageChange,
  onPageSizeChange,
  pageSizeOptions = [10, 25, 50],
  className,
}: {
  /** Zero-based page index. */
  page: number
  pageSize: number
  total: number
  onPageChange: (page: number) => void
  onPageSizeChange: (pageSize: number) => void
  pageSizeOptions?: number[]
  className?: string
}) {
  const pages = Math.max(1, Math.ceil(total / pageSize))
  const first = total === 0 ? 0 : page * pageSize + 1
  const last = Math.min(total, (page + 1) * pageSize)

  /*
    The same canonical pagination shell as the list pager above: a
    navigation landmark named "pagination", whatever the inner layout.
  */
  return (
    <nav
      role="navigation"
      aria-label="pagination"
      data-slot="pagination"
      className={cn(
        "flex flex-wrap items-center justify-between gap-3",
        className
      )}
    >
      <p className="text-xs leading-[17px] text-muted-foreground tabular-nums">
        {first}–{last} of {total}
      </p>
      <div className="flex items-center gap-2">
        {/*
          The page-size control. A native `select` keeps it keyboard- and
          screen-reader-native; the design's pill is its skin.
        */}
        <label className="sr-only" htmlFor="table-page-size">
          Rows per page
        </label>
        <select
          id="table-page-size"
          value={pageSize}
          onChange={(event) => onPageSizeChange(Number(event.target.value))}
          className="h-[39px] rounded-lg border border-[#dce1d6] bg-card px-3 text-[13px] font-semibold text-forest outline-none focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
        >
          {pageSizeOptions.map((option) => (
            <option key={option} value={option}>
              Rows {option}
            </option>
          ))}
        </select>
        <button
          type="button"
          aria-label="Previous page"
          disabled={page === 0}
          onClick={() => onPageChange(page - 1)}
          className="grid h-[39px] w-[35px] place-items-center rounded-lg border border-[#dce1d6] bg-card text-forest transition-colors outline-none hover:bg-accent/60 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring disabled:opacity-40"
        >
          <ChevronLeft aria-hidden="true" className="size-4" />
        </button>
        <span className="grid h-6 min-w-[41px] place-items-center rounded-md bg-forest-soft px-2 text-[11px] leading-[16px] font-semibold text-forest tabular-nums">
          {page + 1} / {pages}
        </span>
        <button
          type="button"
          aria-label="Next page"
          disabled={page + 1 >= pages}
          onClick={() => onPageChange(page + 1)}
          className="grid h-[39px] w-[35px] place-items-center rounded-lg border border-[#dce1d6] bg-card text-forest transition-colors outline-none hover:bg-accent/60 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring disabled:opacity-40"
        >
          <ChevronRight aria-hidden="true" className="size-4" />
        </button>
      </div>
    </nav>
  )
}
