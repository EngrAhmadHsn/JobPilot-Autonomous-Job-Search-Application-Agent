import { useQuery } from "@tanstack/react-query"
import { useEffect, useMemo, useState } from "react"

import { Banner } from "@/components/common/banner"
import { EmptyState } from "@/components/common/progress-state"
import { ErrorNotice } from "@/components/common/error-notice"
import { PageHeader, Section } from "@/components/common/page-header"
import { StatTile } from "@/components/common/stat-tile"
import { EventList, RunTimeline } from "@/components/observability/event-timeline"
import { Card, CardContent } from "@/components/ui/card"

import { api } from "@/lib/api/endpoints"
import {
  formatRelativeTime,
  groupRuns,
  needsAttention,
  summarizeEvents,
} from "@/lib/observability"

type Filter = "all" | "attention"

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

  const audit = useQuery({
    queryKey: ["audit", "activity"],
    queryFn: ({ signal }) => api.audit(signal),
    refetchInterval: 30_000,
  })

  // A ticking clock so "data read N ago" actually ages between refetches.
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 15_000)
    return () => window.clearInterval(timer)
  }, [])

  const events = useMemo(() => audit.data?.events ?? [], [audit.data])
  const summary = summarizeEvents(events)
  const runs = useMemo(() => groupRuns(events), [events])
  const visible = useMemo(
    () => (filter === "attention" ? events.filter(needsAttention) : events),
    [events, filter]
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
            {formatRelativeTime(lastRead ? new Date(lastRead).toISOString() : null, now)} ·
            refreshes every 30s
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

      {audit.isError ? <ErrorNotice error={audit.error} onRetry={() => audit.refetch()} /> : null}

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <StatTile label="Recorded actions" value={summary.total} hint="In the trail the API returned" />
        <StatTile label="By the agent" value={summary.agent} tone="agent" hint="Automated steps" />
        <StatTile label="By people" value={summary.human} tone="human" hint="Approvals and outcomes" />
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
          <div
            role="group"
            aria-label="Filter the trail"
            className="inline-flex rounded-lg border border-border bg-card p-0.5"
          >
            {(["all", "attention"] as const).map((value) => (
              <button
                key={value}
                type="button"
                onClick={() => setFilter(value)}
                aria-pressed={filter === value}
                className={
                  filter === value
                    ? "rounded-md bg-primary px-3 py-1 text-xs font-medium text-primary-foreground"
                    : "rounded-md px-3 py-1 text-xs font-medium text-muted-foreground hover:text-foreground"
                }
              >
                {value === "all" ? "Everything" : "Needs attention"}
              </button>
            ))}
          </div>
        }
      >
        {audit.isPending ? (
          <p className="text-sm text-muted-foreground">Reading the trail...</p>
        ) : visible.length === 0 ? (
          <EmptyState
            title={filter === "attention" ? "Nothing needs attention" : "No recorded activity yet"}
            description={
              filter === "attention"
                ? "No refusal, block or failure is in the trail the API returned."
                : "Upload a résumé or run a search, and the agent's steps will appear here."
            }
          />
        ) : (
          <Card>
            <CardContent>
              <EventList events={visible} />
            </CardContent>
          </Card>
        )}
      </Section>
    </div>
  )
}
