import { CircleDashedIcon } from "lucide-react"
import type { UseQueryResult } from "@tanstack/react-query"

import { ErrorNotice } from "@/components/common/error-notice"
import { Skeleton } from "@/components/ui/skeleton"
import { STATUS_ICONS } from "@/components/ui/status-badge"

import { describeStatus } from "@/lib/status"
import type { ApplicationList } from "@/lib/api/types"

import { ApplicationCard } from "@/screens/tracker/application-card"

/*
  One stage column of the board (WS-39).

  The header carries the **server's total** for this status — the response's
  `total` field, never the length of the loaded page (a partial page must
  never be presented as a stage total). When the total exceeds what the
  column loaded, the footer says so and hands off to the List view filtered
  to this status, which pages through the whole set server-side.

  The column is a surface, not a Card: the cards inside it are the paper
  layer, the column is the board's own structure — the one structural reason
  the design contract allows a bordered block under cards, and the reference
  panel draws exactly that.

  The `awaiting_approval` column carries the terracotta wash: a human
  decision is what holds applications there, and terracotta is the human's
  colour (the same law that colours the status badge and the next-action
  tiles). It is attention, not error — `destructive` stays reserved for
  failures.
*/
export function BoardColumn({
  status,
  query,
  onShowAll,
}: {
  status: string
  query: UseQueryResult<ApplicationList, Error>
  onShowAll: (status: string) => void
}) {
  const presentation = describeStatus(status)
  const Icon =
    (STATUS_ICONS as Record<string, typeof CircleDashedIcon>)[
      presentation.icon
    ] ?? CircleDashedIcon

  const awaiting = status === "awaiting_approval"
  const total = query.data?.total
  const items = query.data?.items ?? []
  const hidden = total !== undefined ? Math.max(0, total - items.length) : 0
  const countLabel = query.isPending
    ? "loading"
    : `${total ?? 0} ${total === 1 ? "application" : "applications"}`

  return (
    <section
      aria-label={`${presentation.label} — ${countLabel}`}
      className={
        awaiting
          ? "rounded-xl border border-terracotta/50 bg-terracotta-soft/40"
          : "rounded-xl border border-border bg-card/50"
      }
    >
      <div className="flex items-center justify-between gap-2 px-3 pt-3 pb-2">
        <h3 className="flex min-w-0 items-center gap-1.5 text-sm font-medium text-foreground">
          <Icon
            aria-hidden={true}
            className="size-3.5 shrink-0"
            strokeWidth={2}
          />
          <span className="truncate">{presentation.label}</span>
        </h3>
        <span
          title={`The server reports ${total ?? "?"} application(s) with this status`}
          className="shrink-0 rounded-full bg-muted px-2 py-0.5 text-xs font-medium text-muted-foreground tabular-nums"
        >
          {query.isPending ? "…" : (total ?? "—")}
        </span>
      </div>

      <div className="space-y-2 px-2 pb-2">
        {query.isPending ? (
          <ul aria-label="Loading this stage" className="space-y-2">
            <li aria-hidden={true}>
              <Skeleton className="h-[86px] w-full rounded-xl" />
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
          <p className="px-1 py-2 text-xs leading-relaxed text-muted-foreground">
            No applications with this status.
          </p>
        ) : null}

        {query.data && items.length > 0 ? (
          <ul className="space-y-2">
            {items.map((application, index) => (
              <ApplicationCard
                key={application.id}
                application={application}
                index={index}
              />
            ))}
          </ul>
        ) : null}

        {hidden > 0 ? (
          <button
            type="button"
            onClick={() => onShowAll(status)}
            className="block px-1 pt-1 text-xs font-medium text-muted-foreground underline underline-offset-4 transition-colors hover:text-foreground"
          >
            Show all {total} in the list
          </button>
        ) : null}
      </div>
    </section>
  )
}
