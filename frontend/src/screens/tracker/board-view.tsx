import { useQueries } from "@tanstack/react-query"

import { api } from "@/lib/api/endpoints"

import { BoardColumn } from "@/screens/tracker/board-column"

/*
  The board (WS-39) — the reference panel 5's stage columns, grounded in the
  contract that actually exists.

  The backend honours **single-status** filters only (`src/api/routes/
  tracking.py:220-221` — a multi-status call silently returns the
  unfiltered list), and there is no stage-count endpoint. So the board is
  five per-status single reads, one per column, made **once on mount**:
  the tracker has no polling today and this view adds none. Each column
  header carries that response's server `total`.

  The columns are the five pipeline statuses of the real vocabulary
  (`lib/status.ts`): the reference's "Saved" and "Preparing" are not backend
  statuses, so their honest counterparts here are "Shortlisted" and
  "Prepared". Applications in the statuses that are not columns — the human
  outcomes, and the earliest states — are not hidden by that choice: the
  honesty note says so, and the List view holds every application.

  On a phone the board falls back to the List (the screen renders the list
  under this view's tab below `md`): five columns do not fit 360 px, and a
  sideways-scrolling table is the one responsive failure the design contract
  names.
*/

/**
 * The board's columns — real backend statuses only, in lifecycle order.
 *
 * `shortlisted` precedes `prepared` in the vocabulary, and the current
 * flows create applications directly in `prepared` — so the column will
 * usually read 0. Zero is the server's own answer for that status, not a
 * fabricated stage.
 */
export const BOARD_STATUSES = [
  "shortlisted",
  "prepared",
  "awaiting_approval",
  "submitted",
  "verified",
] as const

/**
 * How many applications each column loads.
 *
 * The column shows the cards it loaded; anything beyond is the footer's
 * "+N more" hand-off to the list. Eight keeps even a tall column honest
 * about being a page, without asking the server for hundreds of rows.
 */
export const BOARD_COLUMN_LIMIT = 8

export function BoardView({
  onShowAll,
}: {
  /** Hand a stage off to the List view, filtered to that status. */
  onShowAll: (status: string) => void
}) {
  const columns = useQueries({
    queries: BOARD_STATUSES.map((status) => ({
      queryKey: ["applications", "board", status],
      queryFn: ({ signal }: { signal: AbortSignal }) =>
        api.listApplications(
          { status: [status], limit: BOARD_COLUMN_LIMIT, offset: 0 },
          signal
        ),
      staleTime: 30_000,
    })),
  })

  return (
    <section aria-label="Applications by stage" className="space-y-3">
      {/*
        The honesty note: what the columns are, where their counts come
        from, and where the applications that are not columns live.
      */}
      <p className="max-w-[68ch] text-sm leading-relaxed text-muted-foreground">
        Per-stage view. Each column is its own server query for exactly one
        status, and its count is that status&apos;s total on the server — read
        when this view opened, not live. Applications in other statuses (the
        human outcomes, and the earliest states) are not columns here; the List
        view holds every application.
      </p>

      <div className="grid grid-cols-1 gap-3 md:grid-cols-3 xl:grid-cols-5 xl:items-start">
        {BOARD_STATUSES.map((status, index) => {
          // The queries array is built from the same tuple as the columns,
          // so every index exists; the guard is for the type system only.
          const query = columns[index]
          return query ? (
            <BoardColumn
              key={status}
              status={status}
              query={query}
              onShowAll={onShowAll}
            />
          ) : null
        })}
      </div>
    </section>
  )
}
