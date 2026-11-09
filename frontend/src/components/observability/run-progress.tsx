import type { ReactNode } from "react"

import { Banner } from "@/components/common/banner"
import { Disclosure } from "@/components/common/disclosure"
import { FieldList } from "@/components/common/field-list"
import { RelativeTime } from "@/components/common/relative-time"
import { formatDateTime } from "@/lib/format"
import type { RunEvent, RunSummary } from "@/lib/api/types"

/**
 * The state of one durable run, in words.
 *
 * The vocabulary belongs to the backend (`src/runs/state.py`); this is the
 * sentence a person reads instead of the enum. The distinction that matters
 * most is **who acts next**: a queued run is waiting for a worker, a paused
 * run is waiting for the daily reset, an interrupted one is waiting for an
 * administrator.
 */
const STATUS: Record<string, { label: string; help: string; tone: string }> = {
  QUEUED: {
    label: "Waiting for a worker",
    help: "The work is recorded and the API has accepted it. It runs as soon as a worker is available.",
    tone: "text-muted-foreground",
  },
  RUNNING: {
    label: "Working now",
    help: "A worker is executing this run.",
    tone: "text-foreground",
  },
  RETRY_WAIT: {
    label: "Waiting to retry",
    help: "A step failed in a way that may pass on its own; the worker will try it again.",
    // The *foreground* of the clay, not the fill: `--color-terracotta` is the
    // pale swatch meant to sit behind text (a badge background), and using it
    // as text paints an unreadable peach on the ivory surface.
    tone: "text-terracotta-foreground",
  },
  PAUSED: {
    label: "Paused — daily budget spent",
    help: "The work is kept. It resumes after the daily reset, and the same limit applies then.",
    tone: "text-terracotta-foreground",
  },
  RECOVERABLE: {
    label: "Interrupted — needs an administrator",
    help: "The worker stopped while this run still had work outstanding. Nothing is lost: an administrator resumes only what remains.",
    tone: "text-terracotta-foreground",
  },
  COMPLETED: { label: "Finished", help: "", tone: "text-foreground" },
  PARTIAL: {
    label: "Finished with failures",
    help: "Some items failed permanently. What succeeded is kept.",
    tone: "text-terracotta-foreground",
  },
  FAILED: {
    label: "Failed",
    help: "Nothing completed. An administrator can inspect it and retry.",
    tone: "text-destructive",
  },
  CANCELLED: { label: "Cancelled", help: "", tone: "text-muted-foreground" },
}

/** The statuses after which nothing more happens without a person acting. */
export const TERMINAL_RUN_STATUSES = [
  "COMPLETED",
  "PARTIAL",
  "FAILED",
  "CANCELLED",
]

export function isRunTerminal(status: string): boolean {
  return TERMINAL_RUN_STATUSES.includes(status)
}

export function runStatusCopy(status: string) {
  return (
    STATUS[status] ?? {
      label: status,
      help: "",
      tone: "text-muted-foreground",
    }
  )
}

/** The type of work, as a noun. */
export function runTypeLabel(jobType: string, plural = false): string {
  if (jobType === "refresh") return plural ? "refreshes" : "corpus refresh"
  if (jobType === "embedding") return plural ? "embeddings" : "embedding pass"
  if (jobType === "reconcile")
    return plural ? "reconciliations" : "reconciliation"
  return jobType
}

/**
 * One durable run: where it is, how far it got, and what went wrong.
 *
 * Shared by the Operations screen (the operator's own runs) and the
 * Administration screen (every run, where `verbose` adds the run id, the
 * lease and the raw lifecycle events). Both show the same numbers because
 * both read the same backend state — the point of WS-18 is that there is
 * one truth about a run, not one per screen.
 */
export function RunProgress({
  run,
  events = [],
  verbose = false,
  children,
}: {
  run: RunSummary
  events?: RunEvent[]
  /** Show the run id, the priority, the lease and the event log. */
  verbose?: boolean
  children?: ReactNode
}) {
  const copy = runStatusCopy(run.status)
  const settled = isRunTerminal(run.status)

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <p className="text-sm font-medium text-foreground">
          {runTypeLabel(run.job_type, false)}
          <span className="font-normal text-muted-foreground">
            {" "}
            · {copy.label}
          </span>
        </p>
        <p className="text-xs text-muted-foreground">
          {run.started_at ? (
            <>
              started <RelativeTime value={run.started_at} />
            </>
          ) : (
            <>
              queued <RelativeTime value={run.created_at} />
            </>
          )}
          {run.completed_at ? (
            <>
              {" "}
              · finished <RelativeTime value={run.completed_at} />
            </>
          ) : (
            ""
          )}
        </p>
      </div>

      <div
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(run.progress_percent)}
        aria-label={`${runTypeLabel(run.job_type)} progress`}
        className="h-2 w-full overflow-hidden rounded-full bg-muted"
      >
        <span
          className="block h-full rounded-full bg-primary transition-[width] duration-500"
          style={{ width: `${run.progress_percent}%` }}
        />
      </div>

      <FieldList
        items={[
          {
            label: "Items",
            value: `${run.completed_items} of ${run.total_items} done${
              run.remaining_items > 0 ? ` · ${run.remaining_items} left` : ""
            }`,
          },
          { label: "Failed", value: run.failed_items },
          { label: "Skipped", value: run.skipped_items },
          {
            label: "Last heartbeat",
            value: run.heartbeat_at ? formatDateTime(run.heartbeat_at) : "—",
          },
          ...(verbose
            ? [
                { label: "Run id", value: run.id },
                { label: "Priority", value: run.priority },
                {
                  label: "Lease",
                  value: run.lease.owner
                    ? `${run.lease.owner} until ${formatDateTime(run.lease.expires_at)}`
                    : "none",
                },
                {
                  label: "Embedding space",
                  value: run.embedding_model
                    ? `${run.embedding_model} (${run.embedding_dimension}-dim)`
                    : "—",
                },
              ]
            : []),
        ]}
      />

      {copy.help ? (
        <p className="text-sm leading-relaxed text-muted-foreground">
          {copy.help}
        </p>
      ) : null}

      {run.last_error ? (
        <Banner
          tone={settled ? "warning" : "neutral"}
          title={
            run.last_error_kind === "quota"
              ? "The daily embedding budget is spent"
              : settled
                ? "How the run ended"
                : "Why the run is waiting"
          }
        >
          <p>{run.last_error}</p>
        </Banner>
      ) : null}

      {run.metadata?.refresh ? <RefreshReport metadata={run.metadata} /> : null}

      {children}

      {verbose && events.length > 0 ? (
        <Disclosure
          summary="Lifecycle events"
          hint={`${events.length} recorded`}
        >
          <ol className="space-y-2 text-xs">
            {events.map((event) => (
              <li key={event.id} className="flex flex-wrap gap-x-2">
                <span className="font-mono text-muted-foreground">
                  {formatDateTime(event.at)}
                </span>
                <span className="font-medium text-foreground">
                  {event.event}
                </span>
                <span className="text-muted-foreground">
                  {event.actor}
                  {event.message ? ` — ${event.message}` : ""}
                </span>
              </li>
            ))}
          </ol>
        </Disclosure>
      ) : null}

      {!verbose && events.length > 0 ? (
        <Disclosure
          summary="What the worker recorded"
          hint={`${events.length} events`}
        >
          <EventSummary events={events} />
        </Disclosure>
      ) : null}
    </div>
  )
}

/** The refresh's own report, when the run carried one. */
function RefreshReport({ metadata }: { metadata: Record<string, unknown> }) {
  const refresh = metadata.refresh as Record<string, unknown> | undefined
  if (!refresh) return null
  const errors = (refresh.source_errors ?? {}) as Record<string, string>
  const asCount = (value: unknown) => (typeof value === "number" ? value : 0)

  return (
    <div className="space-y-2">
      <p className="text-xs font-medium tracking-wide text-muted-foreground uppercase">
        The refresh report
      </p>
      <FieldList
        items={[
          { label: "Listings found", value: asCount(refresh.found) },
          { label: "Unique after dedup", value: asCount(refresh.deduped) },
          { label: "Persisted", value: asCount(refresh.persisted) },
          { label: "Screened out", value: asCount(refresh.screened_out) },
          {
            label: "Capped by admission",
            value: asCount(refresh.admission_capped),
          },
        ]}
      />
      {Object.keys(errors).length > 0 ? (
        <ul className="list-disc space-y-1 pl-5 text-sm text-muted-foreground">
          {Object.entries(errors).map(([source, message]) => (
            <li key={source}>
              <span className="font-medium text-foreground">{source}</span>:{" "}
              {message}
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  )
}

/** The lifecycle events, as sentences. */
function EventSummary({ events }: { events: RunEvent[] }) {
  return (
    <ol className="space-y-2 text-xs">
      {events.map((event) => (
        <li key={event.id} className="flex flex-wrap gap-x-2">
          <RelativeTime value={event.at} className="text-muted-foreground" />
          <span className="text-foreground">
            {event.message ?? event.event}
          </span>
        </li>
      ))}
    </ol>
  )
}
