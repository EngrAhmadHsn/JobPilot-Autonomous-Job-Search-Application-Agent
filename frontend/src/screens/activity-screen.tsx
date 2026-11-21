import { useQuery } from "@tanstack/react-query"
import { useMemo, useState } from "react"

import { EmptyState } from "@/components/common/progress-state"
import { ErrorNotice } from "@/components/common/error-notice"
import { Pagination } from "@/components/common/pagination"
import { PageHeader } from "@/components/ui/page-header"
import { RelativeTime } from "@/components/common/relative-time"
import {
  EventList,
  RunTimeline,
} from "@/components/observability/event-timeline"

import { api } from "@/lib/api/endpoints"
import { groupRuns, type AgentRun } from "@/lib/observability"
import { ACTIVITY_POLL_MS } from "@/lib/polling"
import {
  ACTIVITY_FILTERS,
  type ActivityFilter,
  matchesFilter,
} from "@/screens/facts/activity/filters"
import { ActivityFilters } from "@/screens/facts/activity/filter-chips"

type Filter = ActivityFilter

/** How many trail rows one page shows. */
const TRAIL_PAGE_SIZE = 10

/** The day heading a feed row sits under ("Today" / "Yesterday" / a date). */
function dayLabel(iso: string | null | undefined): string {
  if (!iso) return "Undated"
  const parsed = new Date(iso)
  if (Number.isNaN(parsed.getTime())) return "Undated"
  const startOf = (date: Date) =>
    new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime()
  const diff = Math.round((startOf(new Date()) - startOf(parsed)) / 86_400_000)
  if (diff === 0) return "Today"
  if (diff === 1) return "Yesterday"
  return parsed.toLocaleDateString(undefined, {
    weekday: "long",
    day: "numeric",
    month: "long",
  })
}

/**
 * Agent activity — the observability screen, rebuilt to the design file's
 * screen `16:242` ("Nothing happens in the dark.").
 *
 * The question it answers is "what has the agent actually been doing, and
 * how did each execution go?". The data is the account's own audit trail:
 * the same rows the backend writes for every external action, in the
 * server's own vocabulary. The console translates the vocabulary but never
 * adds a step that is not in the data.
 *
 * The design's composition: the filter pills with their real counts, the
 * feed grouped by day — each row a time, an actor chip, the action, and a
 * **Details** disclosure carrying the raw record — and the right rail
 * showing the latest execution as an ordered proof. The design draws the
 * rail for a *selected* event; the console selects the **latest** run,
 * because the audit rows carry no application id a rail link could name,
 * and a link to nothing is a lie — the proof card names the workflow id
 * the trail actually recorded.
 *
 * **On real-time.** There is no streaming endpoint. Rather than dress
 * polling up as "live", the caption beside the filters says plainly that
 * the screen refetches on an interval and when it last read. Genuine
 * streaming would need a server-sent-events endpoint the backend does not
 * have yet; that is recorded as a known backend dependency, not faked here.
 */
export function ActivityScreen() {
  const [filter, setFilter] = useState<Filter>("all")
  const [trailPage, setTrailPage] = useState(0)

  const audit = useQuery({
    queryKey: ["audit", "activity"],
    queryFn: ({ signal }) => api.audit(signal),
    refetchInterval: ACTIVITY_POLL_MS,
  })

  const events = useMemo(() => audit.data?.events ?? [], [audit.data])
  const runs = useMemo(() => groupRuns(events), [events])
  const visible = useMemo(
    () => events.filter((event) => matchesFilter(event, filter)),
    [events, filter]
  )
  /*
    The chips carry real counts — how many rows each would show — so an empty
    chip is honest before it is clicked rather than after.
  */
  const counts = useMemo(() => {
    const result = {} as Record<ActivityFilter, number>
    for (const { value } of ACTIVITY_FILTERS) {
      result[value] = events.filter((event) =>
        matchesFilter(event, value)
      ).length
    }
    return result
  }, [events])
  const trailPages = Math.max(1, Math.ceil(visible.length / TRAIL_PAGE_SIZE))
  const trailPageSafe = Math.min(trailPage, trailPages - 1)
  const pageRows = visible.slice(
    trailPageSafe * TRAIL_PAGE_SIZE,
    (trailPageSafe + 1) * TRAIL_PAGE_SIZE
  )
  /** The page's rows, grouped into the day sections the design draws. */
  const dayGroups = useMemo(() => {
    const groups: { label: string; rows: typeof pageRows }[] = []
    for (const event of pageRows) {
      const label = dayLabel(event.recorded_at)
      const last = groups[groups.length - 1]
      if (last && last.label === label) {
        last.rows.push(event)
      } else {
        groups.push({ label, rows: [event] })
      }
    }
    return groups
  }, [pageRows])

  const lastRead = audit.dataUpdatedAt
  const latestRun: AgentRun | null = runs[0] ?? null

  return (
    <div className="space-y-6">
      <PageHeader
        title="Nothing happens in the dark."
        description="A readable record of agent work and your decisions."
      />

      {audit.isError ? (
        <ErrorNotice error={audit.error} onRetry={() => audit.refetch()} />
      ) : null}

      <div className="flex flex-wrap items-center justify-between gap-x-6 gap-y-3">
        <ActivityFilters
          value={filter}
          onChange={(next) => {
            setFilter(next)
            // A filter that keeps the page index would land on an empty
            // page: the filtered list is shorter than "everything".
            setTrailPage(0)
          }}
          counts={counts}
        />
        <p className="text-xs leading-[17px] text-muted-foreground">
          Data read{" "}
          <RelativeTime
            value={lastRead ? new Date(lastRead).toISOString() : null}
          />{" "}
          · refreshes every 30s — polling, not a live stream (the backend has no
          event stream yet).
        </p>
      </div>

      <div className="grid gap-6 xl:grid-cols-[minmax(0,2fr)_minmax(0,1fr)] xl:items-start">
        <div className="min-w-0 space-y-3">
          {audit.isPending ? (
            <p className="text-sm text-muted-foreground">
              Reading the trail...
            </p>
          ) : visible.length === 0 ? (
            <EmptyState
              title={
                filter === "attention"
                  ? "Nothing needs you"
                  : "No recorded activity yet"
              }
              description={
                filter === "attention"
                  ? "No refusal, block or failure is in the trail the API returned."
                  : "Upload a résumé or run a search, and the agent's steps will appear here."
              }
            />
          ) : (
            <div className="space-y-3">
              {/*
                The filtered region: the chips above it select these rows, and
                the execution proof in the rail is unfiltered — so the two
                must not be confused by a test or a screen reader.
              */}
              <div data-testid="activity-trail">
                {dayGroups.map((group) => (
                  <section
                    key={group.label}
                    className="rounded-surface border border-border-surface bg-card p-5"
                  >
                    <h2 className="text-[20px] leading-[29px] font-semibold text-primary">
                      {group.label}
                    </h2>
                    <div className="mt-3">
                      <EventList events={group.rows} />
                    </div>
                  </section>
                ))}
                {dayGroups.length > 1 ? (
                  <p className="text-xs text-muted-foreground">
                    Each card is one day, newest first.
                  </p>
                ) : null}
              </div>
              <Pagination
                page={trailPageSafe}
                pageSize={TRAIL_PAGE_SIZE}
                total={visible.length}
                onPageChange={setTrailPage}
                label="recorded actions"
              />
            </div>
          )}
        </div>

        <aside className="min-w-0 space-y-3 xl:sticky xl:top-[calc(var(--header-height,7rem)+1rem)]">
          {/*
            The latest execution, as the design's ordered proof. It is not
            filtered with the feed — it is the run's own record, and the run
            keeps its identity whatever the chips select.
          */}
          {latestRun ? (
            <RunTimeline run={latestRun} />
          ) : (
            <section className="flex min-w-0 flex-col gap-2 rounded-surface border border-border-surface bg-card p-5">
              <h2 className="text-[20px] leading-[29px] font-semibold text-primary">
                No execution recorded yet
              </h2>
              <p className="text-sm leading-relaxed text-muted-foreground">
                An application workflow is recorded here once the agent prepares
                one — every step that shares a workflow id, in order.
              </p>
            </section>
          )}

          {/*
            The evidence rule, in the design's own words: evidence exists only
            where the product could capture it, and this feed is the latest
            events, never lifetime analytics.
          */}
          <section className="flex min-w-0 flex-col gap-2 rounded-surface bg-forest-soft p-[18px]">
            <h2 className="text-[15px] font-semibold text-primary">
              Evidence appears when it exists.
            </h2>
            <p className="text-sm leading-relaxed text-muted-foreground">
              No screenshot or confirmation is available for a queued
              application. This feed shows the latest events, not lifetime
              analytics.
            </p>
          </section>
        </aside>
      </div>
    </div>
  )
}
