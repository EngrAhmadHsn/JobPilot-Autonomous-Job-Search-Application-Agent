import type { UseQueryResult } from "@tanstack/react-query"

import { ErrorNotice } from "@/components/common/error-notice"
import { Skeleton } from "@/components/ui/skeleton"

import type { ApplicationList } from "@/lib/api/types"

import { ApplicationCard } from "@/screens/tracker/application-card"
import type { StageGroup } from "@/screens/tracker/stage-groups"

/*
  One stage column of the board (WS-39, rebuilt to the design in WS-42).

  The design file (screen 05, node 49:1146) draws a column as: a paper card
  list on a sage `#eeefe7` surface, under a header row that holds the stage
  title, the count chip and a ghost "⋯" — and the card list scrolls
  **independently** while the header stays put. That independent scroll is
  the point of the board — comparing four stages side by side only works if
  the columns do not drag one another's position around.

  Three honesty rules survive, because they are not cosmetic:

  1. The count is the **server's total for this group**, from the response's
     `total` field — never `items.length`. A page of eight is a page.
  2. When the total exceeds what the column loaded, the footer says so and
     hands off to the List view, which pages the whole set server-side. The
     column never implies it is showing everything.
  3. The stage's meaning travels on the cards themselves (`stage-copy.ts`'s
     helper line) rather than as a header paragraph — the design's header is
     title + count + ghost only, and the cards carry the words.

  The header's "⋯" is drawn as the design draws it — a quiet glyph, not a
  button: it makes no promise of hidden actions the console does not have.
*/
export function BoardColumn({
  group,
  query,
  onShowAll,
}: {
  group: StageGroup
  query: UseQueryResult<ApplicationList, Error>
  onShowAll: () => void
}) {
  const total = query.data?.total
  const items = query.data?.items ?? []
  const hidden = total !== undefined ? Math.max(0, total - items.length) : 0
  const countLabel =
    total === undefined
      ? "count unavailable"
      : `${total} ${total === 1 ? "application" : "applications"}`

  return (
    <section
      aria-label={`${group.label} — ${countLabel}`}
      className="flex h-[412px] shrink-0 flex-col gap-3 rounded-[var(--radius-surface)] bg-[#eeefe7] p-3 md:h-[575px] md:w-[314px] w-[304px] xl:h-[601px] xl:w-auto xl:flex-1"
    >
      {/*
        The header. It stays put while the cards scroll, which is what makes a
        column readable at a glance after scrolling to card 40.
      */}
      <header className="flex shrink-0 items-center gap-3">
        <h3 className="type-card-title min-w-0 flex-1 truncate text-sm leading-5">
          {group.label}
        </h3>
        <span
          title={`The server reports ${
            total ?? "an unknown number of"
          } application${total === 1 ? "" : "s"} in this stage`}
          className="shrink-0 rounded-md bg-forest-soft px-[9px] py-1 text-[11px] font-semibold leading-4 text-primary tabular-nums"
        >
          {query.isPending ? "…" : (total ?? "—")}
        </span>
        <span
          aria-hidden="true"
          className="grid h-[37px] w-[39px] shrink-0 place-items-center text-[13px] font-semibold text-primary select-none"
        >
          ⋯
        </span>
      </header>

      {/*
        The cards, scrolling on their own, under the design's thin sage
        scrollbar (`.board-scroll`, styled once in `board-view.tsx`).
      */}
      <div className="board-scroll min-h-0 flex-1 overflow-y-auto overscroll-contain">
        {query.isPending ? (
          <ul aria-label="Loading this stage" className="space-y-3">
            <li aria-hidden="true">
              <Skeleton className="h-[92px] w-full rounded-[var(--radius-surface)]" />
            </li>
            <li aria-hidden="true">
              <Skeleton className="h-[92px] w-full rounded-[var(--radius-surface)]" />
            </li>
          </ul>
        ) : null}

        {query.isError ? (
          <div className="px-1 py-1">
            <ErrorNotice
              error={query.error}
              onRetry={() => void query.refetch()}
            />
          </div>
        ) : null}

        {query.data && items.length === 0 ? (
          <p className="type-caption px-2 py-3">Nothing in this stage.</p>
        ) : null}

        {query.data && items.length > 0 ? (
          <ul className="space-y-3">
            {items.map((application, index) => (
              <ApplicationCard
                key={application.id}
                application={application}
                index={index}
              />
            ))}
          </ul>
        ) : null}
      </div>

      {/*
        The hand-off. It appears only when the server has more than the column
        loaded, and it says how many — so the column never quietly stops.
      */}
      {hidden > 0 ? (
        <div className="shrink-0 border-t border-border-surface px-1 pt-2">
          <button
            type="button"
            onClick={onShowAll}
            className="text-[13px] font-semibold text-forest underline-offset-4 outline-none hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
          >
            Show all {total} in the list →
          </button>
        </div>
      ) : null}
    </section>
  )
}
