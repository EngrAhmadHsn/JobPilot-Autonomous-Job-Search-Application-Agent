import { cn } from "cn"

import { RelativeTime } from "@/components/common/relative-time"
import type { AuditEvent } from "@/lib/api/types"
import { formatDateTime, formatTimeOfDay } from "@/lib/format"
import {
  describeAction,
  describeOutcome,
  needsAttention,
  type AgentRun,
} from "@/lib/observability"

/*
  The colour rule, applied to the trail (design `16:242`): **lime is the
  agent, clay is a person**, and a row the platform blocked or refused is
  called out — it is the one kind of row a human must read.
*/
const ACTOR_CHIP: Record<string, { label: string; class: string }> = {
  agent: {
    label: "Agent",
    class: "bg-lime-soft text-lime-foreground",
  },
  user: {
    label: "You",
    class: "bg-terracotta-soft text-terracotta-foreground",
  },
  system: {
    label: "System",
    class: "border border-border-surface text-muted-foreground",
  },
}

/** The chip for the actor, from the row's kind — never invented. */
function ActorChip({ event }: { event: AuditEvent }) {
  const meta = ACTOR_CHIP[event.actor_kind] ?? {
    label: event.actor_kind,
    class: "border border-border-surface text-muted-foreground",
  }
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-[6px] px-2.5 py-1 text-[11px] leading-4 font-semibold",
        meta.class
      )}
    >
      {meta.label}
    </span>
  )
}

/** The time-of-day voice the design's feed rows use (12/400). */
function EventTime({ event }: { event: AuditEvent }) {
  return (
    <time
      className="w-12 shrink-0 text-xs leading-[17px] text-muted-foreground tabular-nums"
      dateTime={event.recorded_at ?? undefined}
      title={formatDateTime(event.recorded_at)}
    >
      {event.recorded_at ? formatTimeOfDay(event.recorded_at) : "—"}
    </time>
  )
}

/**
 * One row of the feed (design `16:242`): the time, the actor chip, the
 * action in the server's own translated vocabulary, one line of meaning —
 * the outcome — and the technical detail behind a **Details** disclosure.
 *
 * Every row is one audit record: what happened, who did it, whether it
 * succeeded, and — when it did not — why the platform stopped it. The
 * technical detail (the raw action, the resource, the workflow id, the
 * metadata) is behind the disclosure, so the feed reads as sentences first
 * and as a trace when a human asks for it.
 */
export function EventList({ events }: { events: AuditEvent[] }) {
  return (
    <ol className="min-w-0">
      {events.map((event) => (
        <EventRow key={event.id} event={event} />
      ))}
    </ol>
  )
}

export function EventRow({ event }: { event: AuditEvent }) {
  const action = describeAction(event.action)
  const attention = needsAttention(event)

  return (
    <li className="border-b border-border-surface py-3 last:border-b-0">
      {/*
        The whole row is the disclosure: the design's "Details →" is the
        affordance, and the technical record — the raw action, the resource,
        the workflow id, the metadata — is what opens.
      */}
      <details className="group">
        <summary className="flex min-w-0 cursor-pointer list-none items-start gap-3 rounded-lg">
          <EventTime event={event} />
          <div className="min-w-0 flex-1 space-y-1">
            <div className="flex flex-wrap items-center gap-2">
              <ActorChip event={event} />
              <p className="text-sm font-semibold text-primary">
                {action.label}
              </p>
            </div>
            <p
              className={cn(
                "text-xs leading-[17px]",
                attention
                  ? "text-terracotta-foreground"
                  : "text-muted-foreground"
              )}
            >
              {attention
                ? `${describeOutcome(event.outcome)} — needs a human.`
                : "Completed cleanly."}
            </p>
          </div>
          <span
            aria-hidden
            className="inline-flex shrink-0 items-center gap-1 text-[13px] font-semibold text-primary transition-transform duration-200 group-open:rotate-90"
          >
            Details →
          </span>
        </summary>
        <div className="mt-3 space-y-4 rounded-xl border border-border-surface bg-muted/30 p-4">
          <dl className="grid gap-x-6 gap-y-2 text-xs sm:grid-cols-2">
            <Detail label="Action" value={event.action} mono />
            <Detail label="Outcome" value={event.outcome} />
            <Detail label="Actor" value={event.actor} mono />
            <Detail label="Resource" value={event.resource} mono />
            {event.workflow_id ? (
              <Detail label="Workflow" value={event.workflow_id} mono />
            ) : null}
            <Detail
              label="Recorded"
              value={formatDateTime(event.recorded_at)}
            />
          </dl>
          {Object.keys(event.metadata).length > 0 ? (
            <div>
              <p className="text-xs font-medium text-muted-foreground uppercase">
                Metadata
              </p>
              <pre className="mt-1 overflow-x-auto rounded-lg bg-muted/60 p-3 font-mono text-[11px] text-foreground">
                {JSON.stringify(event.metadata, null, 2)}
              </pre>
            </div>
          ) : null}
        </div>
      </details>
    </li>
  )
}

/** One labelled technical fact inside a row's Details disclosure. */
function Detail({
  label,
  value,
  mono,
}: {
  label: string
  value: string
  mono?: boolean
}) {
  return (
    <div className="min-w-0">
      <dt className="text-xs font-medium text-muted-foreground uppercase">
        {label}
      </dt>
      <dd className={cn("break-all text-foreground", mono && "font-mono")}>
        {value || "—"}
      </dd>
    </div>
  )
}

/**
 * One execution, reassembled from the audit rows that share a workflow —
 * rendered as the design's proof card (`16:242`'s right rail): a state
 * chip, the workflow, and the ordered steps as numbered evidence.
 *
 * The steps read top to bottom in the order the events happened — the
 * order the server recorded them, not the order a reader assumes they
 * occurred in. A run that hit a failure says so at the top, so it is not
 * buried under a long list of successful steps.
 */
export function RunTimeline({ run }: { run: AgentRun }) {
  return (
    <section className="flex min-w-0 flex-col gap-3.5 rounded-surface border border-border-surface bg-card p-5">
      <span
        className={cn(
          "inline-flex w-fit items-center rounded-[6px] px-2.5 py-1 text-[11px] leading-4 font-semibold uppercase",
          run.hasFailure
            ? "bg-terracotta-soft text-terracotta-foreground"
            : "bg-lime-soft text-lime-foreground"
        )}
      >
        {run.hasFailure ? "Needs attention" : "Accepted and queued"}
      </span>
      <h2 className="text-[20px] leading-[29px] font-semibold text-primary">
        Workflow <span className="font-mono text-base">{run.workflowId}</span>
      </h2>
      <p className="text-xs leading-[17px] text-muted-foreground">
        {run.events.length} step{run.events.length === 1 ? "" : "s"} · started{" "}
        <RelativeTime value={run.startedAt} />
      </p>
      <div className="h-px w-full shrink-0 bg-border-surface" aria-hidden />
      {/*
        The proof is open by default: the rail exists to show this run's
        steps, and hiding them behind a disclosure would make the rail a
        second feed.
      */}
      <ol className="space-y-3">
        {run.events.map((event, index) => {
          const action = describeAction(event.action)
          const attention = needsAttention(event)
          return (
            <li key={event.id} className="flex min-w-0 items-start gap-3">
              <span
                aria-hidden
                className={cn(
                  "mt-0.5 flex size-6 shrink-0 items-center justify-center rounded-[6px] text-[11px] font-semibold",
                  attention
                    ? "bg-terracotta-soft text-terracotta-foreground"
                    : "bg-forest-soft text-primary"
                )}
              >
                {index + 1}
              </span>
              <div className="min-w-0 space-y-0.5">
                <p className="text-sm font-semibold text-foreground">
                  {action.label}
                </p>
                <p className="text-xs leading-[17px] text-muted-foreground">
                  {describeOutcome(event.outcome)} ·{" "}
                  <RelativeTime value={event.recorded_at} />
                </p>
              </div>
            </li>
          )
        })}
      </ol>
    </section>
  )
}
