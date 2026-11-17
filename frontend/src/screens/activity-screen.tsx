import { useQuery } from "@tanstack/react-query"
import { useMemo, useState } from "react"

import { Banner } from "@/components/common/banner"
import { Pagination } from "@/components/common/pagination"
import { EmptyState } from "@/components/common/progress-state"
import { ErrorNotice } from "@/components/common/error-notice"
import { RelativeTime } from "@/components/common/relative-time"
import { PageHeader, Section } from "@/components/common/page-header"
import { StatTile } from "@/components/common/stat-tile"
import {
  EventList,
  RunTimeline,
} from "@/components/observability/event-timeline"
import { Card, CardContent } from "@/components/ui/card"

import { api } from "@/lib/api/endpoints"
import { groupRuns, needsAttention, summarizeEvents } from "@/lib/observability"
import { ACTIVITY_POLL_MS } from "@/lib/polling"
import {
  ACTIVITY_FILTERS,
  type ActivityFilter,
  matchesFilter,
} from "@/screens/facts/activity/filters"
import { ActivityFilters } from "@/screens/facts/activity/filter-chips"

type Filter = ActivityFilter | "attention"

/** How many trail rows one page shows. */
const TRAIL_PAGE_SIZE = 10

/**
 * Agent activity — the observability screen.
 *
 * The question it answers is "what has the agent actually been doing, and
 * how did each execution go?". The data is the account's own audit trail:
 * the same rows the backend writes for every external action, in the
 * server's own vocabulary. The console translates the vocabulary but never
 * adds a step that is not in the data.
 *
 * **On real-time.** There is no streaming endpoint. Rather than dress
 * polling up as "live", the screen says plainly that it refetches on an
 * interval and when it last read. Genuine streaming would need a
 * server-sent-events endpoint the backend does not have yet; that is
 * recorded as a known backend dependency, not faked here.
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
  const summary = summarizeEvents(events)
  const runs = useMemo(() => groupRuns(events), [events])
  const visible = useMemo(
    () =>
      filter === "attention"
        ? events.filter(needsAttention)
        : events.filter((event) => matchesFilter(event, filter)),
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

  const lastRead = audit.dataUpdatedAt

  return (
    <div className="space-y-8">
      <PageHeader
        title="Agent activity"
        description="Every action recorded against this account — what the agent did, what a person did, and what the platform refused. This screen shows the trail the server wrote, translated, never invented."
        actions={
          <span className="text-xs text-muted-foreground">
            Data read{" "}
            <RelativeTime
              value={lastRead ? new Date(lastRead).toISOString() : null}
            />{" "}
            · refreshes every 30s
          </span>
        }
      />

      <Banner tone="neutral" title="This is not a live stream">
        <p>
          The backend has no event-streaming endpoint, so the console refetches
          on an interval instead of pretending to be real-time. Genuine updates
          would need a server-sent-events route; until then, the timestamp above
          is when this data was read.
        </p>
      </Banner>

      {audit.isError ? (
        <ErrorNotice error={audit.error} onRetry={() => audit.refetch()} />
      ) : null}

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <StatTile
          label="Recorded actions"
          value={summary.total}
          hint="In the trail the API returned"
        />
        <StatTile
          label="By the agent"
          value={summary.agent}
          tone="agent"
          hint="Automated steps"
        />
        <StatTile
          label="By people"
          value={summary.human}
          tone="human"
          hint="Approvals and outcomes"
        />
        <StatTile
          label="Needs attention"
          value={summary.attention}
          tone="attention"
          hint="Refused, blocked or failed"
        />
      </div>

      <Section
        title="Executions"
        description="Actions that share a workflow, grouped into the execution they belong to. One application, from preparation to verification, is one workflow."
      >
        {runs.length === 0 ? (
          <EmptyState
            title="No executions recorded"
            description="An application workflow is recorded here once the agent prepares one — every step that shares a workflow id, in order."
          />
        ) : (
          <div className="space-y-4">
            {runs.slice(0, 5).map((run) => (
              <RunTimeline key={run.workflowId} run={run} />
            ))}
            {runs.length > 5 ? (
              <p className="text-xs text-muted-foreground">
                Showing the 5 most recent of {runs.length} executions. The full
                list is in the trail below.
              </p>
            ) : null}
          </div>
        )}
      </Section>

      <Section
        title="The trail"
        description="Newest first. Each row can be opened for the raw action, resource and workflow id."
        action={
          <div className="flex flex-wrap items-center gap-2">
            <ActivityFilters
              value={filter === "attention" ? "all" : filter}
              onChange={(next) => {
                setFilter(next)
                // A filter that keeps the page index would land on an empty
                // page: the filtered list is shorter than "everything".
                setTrailPage(0)
              }}
              counts={counts}
            />
            {/*
              "Needs attention" survives as its own control beside the four
              reference chips: it is the one view an operator actually acts
              on, and it is a derived predicate (`needsAttention`), not an
              actor kind — folding it into the chip radio group would claim
              it is a fifth source of events, which it is not.
            */}
            <button
              type="button"
              onClick={() => {
                setFilter(filter === "attention" ? "all" : "attention")
                setTrailPage(0)
              }}
              aria-pressed={filter === "attention"}
              className={
                filter === "attention"
                  ? "rounded-full border border-terracotta bg-terracotta-soft px-3 py-1 text-xs font-medium text-terracotta-foreground"
                  : "rounded-full border border-border bg-card px-3 py-1 text-xs font-medium text-muted-foreground hover:bg-accent hover:text-foreground"
              }
            >
              Needs attention
              <span className="ml-1.5 tabular-nums opacity-60">
                {summary.attention}
              </span>
            </button>
          </div>
        }
      >
        {audit.isPending ? (
          <p className="text-sm text-muted-foreground">Reading the trail...</p>
        ) : visible.length === 0 ? (
          <EmptyState
            title={
              filter === "attention"
                ? "Nothing needs attention"
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
            {/* The filtered region: the chips above it select these rows, and
                the Executions timeline higher up is unfiltered — so the two
                must not be confused by a test or a screen reader. */}
            <Card data-testid="activity-trail">
              <CardContent>
                <EventList events={pageRows} />
              </CardContent>
            </Card>
            <Pagination
              page={trailPageSafe}
              pageSize={TRAIL_PAGE_SIZE}
              total={visible.length}
              onPageChange={setTrailPage}
              label="recorded actions"
            />
          </div>
        )}
      </Section>
    </div>
  )
}
