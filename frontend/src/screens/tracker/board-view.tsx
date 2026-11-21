import { useQueries } from "@tanstack/react-query"
import type { UseQueryResult } from "@tanstack/react-query"
import type { ReactNode } from "react"

import { LinkButton } from "@/components/ui/link-button"

import { api } from "@/lib/api/endpoints"
import { pluralize } from "@/lib/format"
import type { ApplicationList } from "@/lib/api/types"

import { BoardColumn } from "@/screens/tracker/board-column"
import { STAGE_GROUPS, type StageGroup } from "@/screens/tracker/stage-groups"

/*
  The board (WS-39, regrouped for WS-42).

  The design file's screen 05 draws **four** columns — Awaiting review, Needs
  you, In progress, Outcome recorded — over a backend vocabulary of eleven
  statuses. So a column is a **group** of statuses, which is only expressible
  now: until 2026-11-19 a request carrying more than one status silently
  returned the *unfiltered* list, which is why the previous board used one
  column per status (five reads) and the design's four groups were not
  available at all.

  Each column is **one** request for its whole group, and its header carries
  that response's server `total` — never the number of cards loaded, and
  never a sum of the other columns' counts (a sum of pages is not a total).

  The toolbar above the columns is the design's (nodes 49:1133–49:1143): the
  Board/List pills (the active view filled forest), a Filters pill, the
  total count, and "Find another role →". Two of these are honest
  restatements of what already existed, and one is a judgement call:

  - **Filters** has no panel of its own on the board — the only server-side
    filter this API offers is the list's single-status filter, and faking a
    filter sheet would promise filtering the board does not do. The pill
    hands off to the List view, where the real filter lives.
  - **The count** is the sum of the four columns' server `total`s, shown
    only when every column answered: the four groups partition the tracked
    statuses, so the sum is the server's total for the board — but a
    pending or failed column would make it a guess, and a guess is not
    rendered.
*/

/**
 * How many applications each column loads.
 *
 * The column shows the cards it loaded; anything beyond is the footer's
 * "+N more" hand-off to the List view, which pages through the whole set
 * server-side. Eight keeps even a tall column honest about being a page.
 */
export const BOARD_COLUMN_LIMIT = 8

/*
  The design's thin sage scrollbar for the two scroll surfaces (column
  cards, and the horizontal column swipe on narrow screens). Declared once,
  here — the board is the only consumer.
*/
const SCROLLBAR_STYLE = `
  .board-scroll { scrollbar-width: thin; scrollbar-color: #9aae94 #dfe5da; }
  .board-scroll::-webkit-scrollbar { width: 4px; height: 4px; }
  .board-scroll::-webkit-scrollbar-track { background: #dfe5da; border-radius: 2px; }
  .board-scroll::-webkit-scrollbar-thumb { background: #9aae94; border-radius: 2px; }
`

export function BoardView({
  tabs,
  onShowAll,
  onOpenList,
}: {
  /**
   * The screen's Board/List pills (design 49:1134–49:1137), rendered first
   * in the toolbar row exactly where the design puts them. They are owned
   * by the screen so the List view they switch to can offer the way back.
   */
  tabs: ReactNode
  /** Hand a stage off to the List view, filtered to that stage's statuses. */
  onShowAll: (group: StageGroup) => void
  /** Hand the whole screen off to the List view (the Filters pill). */
  onOpenList: () => void
}) {
  /*
    One read per column, made **once on mount**: the tracker does not poll,
    and this view adds none. `useQueries` keeps the four requests in one hook
    so their order and lifetime match the columns exactly.
  */
  const queries = useQueries({
    queries: STAGE_GROUPS.map((group) => ({
      queryKey: ["applications", "board", group.key],
      queryFn: ({ signal }: { signal: AbortSignal }) =>
        api.listApplications(
          { status: group.statuses, limit: BOARD_COLUMN_LIMIT },
          signal
        ),
      retry: false,
    })),
  }) as UseQueryResult<ApplicationList, Error>[]

  /*
    The board's total: the four columns' server totals, only when all four
    answered. A sum of server totals is the server's number for the board
    (the groups partition the tracked statuses); a sum over a pending or
    failed column would be a guess, and the console does not render guesses.
  */
  const total = queries.every((query) => query.isSuccess)
    ? queries.reduce((sum, query) => sum + (query.data?.total ?? 0), 0)
    : null

  return (
    <div className="space-y-5">
      <style>{SCROLLBAR_STYLE}</style>

      {/*
        The toolbar (design 49:1133): the screen's Board/List pills, the
        Filters hand-off, the total, and the way back to the search.
      */}
      <div className="flex flex-wrap items-center gap-2.5">
        {tabs}

        {/*
          The Filters pill is a hand-off, not a panel: the board's columns
          are themselves the stages, and the server's one real filter lives
          on the List view. Opening a fake filter sheet here would promise
          filtering the board does not do.
        */}
        <button
          type="button"
          onClick={onOpenList}
          title="The server-side status filter lives on the List view"
          className="inline-flex h-[39px] items-center gap-2 rounded-lg border border-border-surface bg-paper px-3.5 py-2 text-[13px] leading-[19px] font-semibold text-primary outline-none hover:bg-accent focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
        >
          Filters
          <span className="text-[11px] leading-4 font-normal text-muted-foreground">
            F
          </span>
        </button>

        <span className="min-w-0 flex-1 text-xs leading-[17px] text-muted-foreground">
          {total === null ? "" : pluralize(total, "application")}
        </span>

        <LinkButton
          to="/app/matches"
          variant="outline"
          className="h-[39px] rounded-lg px-3.5 py-2 text-[13px] leading-[19px] font-semibold"
        >
          Find another role →
        </LinkButton>
      </div>

      {/*
        The horizontal viewport. At full width the four columns share the
        row (the design's 1440 drawing); below that the same columns swipe
        sideways under sticky headers, the design's 768/390 drawing — never
        a squeezed grid, and never a different surface.
      */}
      <div className="board-scroll -mx-1 overflow-x-auto px-1 pb-1">
        <div className="flex min-w-full gap-4">
          {STAGE_GROUPS.map((group, index) => (
            <BoardColumn
              key={group.key}
              group={group}
              query={queries[index] as UseQueryResult<ApplicationList, Error>}
              onShowAll={() => onShowAll(group)}
            />
          ))}
        </div>
      </div>

      {/*
        The integrity note (design 49:1255) — the design's own copy, which
        is the honesty contract for everything above it. It hides at the
        narrowest width exactly as the design file does (the 390 frame
        carries it `hidden`).
      */}
      <aside
        role="note"
        aria-label="What a stage means"
        className="flex flex-col gap-1.5 rounded-[var(--radius-surface)] bg-forest-soft p-4 max-md:hidden"
      >
        <p className="text-[15px] leading-[22px] font-semibold text-primary">
          A stage is a fact, not a guess.
        </p>
        <p className="text-[13px] leading-[19px] text-muted-foreground">
          Queued does not mean sent. Employer handoff does not mean submitted.
          Each column scrolls independently; its header stays in place.
        </p>
      </aside>
    </div>
  )
}
