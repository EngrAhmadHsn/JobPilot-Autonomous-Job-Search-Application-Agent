import { cn } from "cn"
import type { CSSProperties } from "react"

import { Disclosure } from "@/components/common/disclosure"
import type { AuditEvent } from "@/lib/api/types"
import { formatDateTime } from "@/lib/format"
import {
  describeAction,
  describeOutcome,
  eventTone,
  formatRelativeTime,
  needsAttention,
  type AgentRun,
  type EventTone,
} from "@/lib/observability"

/*
  The colour rule, applied to the trail: **lime is the agent, terracotta is
  a person.** A system row is neutral, and a row the platform blocked or
  refused is called out — it is the one kind of row a human must read.
*/
const DOT: Record<EventTone, string> = {
  agent: "bg-lime",
  human: "bg-terracotta",
  system: "bg-border",
  attention: "bg-terracotta",
  failure: "bg-destructive",
}

const WHO: Record<EventTone, string> = {
  agent: "The agent",
  human: "A person",
  system: "The system",
  attention: "The system",
  failure: "The system",
}

/** The word for the actor, from the row's kind — never invented. */
function actorWord(event: AuditEvent): string {
  if (event.actor_kind === "agent") return "the agent"
  if (event.actor_kind === "user") return "a person"
  return "the system"
}

/**
 * The chronological feed.
 *
 * Every row is one audit record: what happened, who did it, whether it
 * succeeded, and — when it did not — why the platform stopped it. The
 * technical detail (the raw action, the resource, the workflow id, the
 * metadata) is behind a disclosure, so the feed reads as sentences first
 * and as a trace when a human asks for it.
 */
export function EventList({ events }: { events: AuditEvent[] }) {
  return (
    <ol className="relative space-y-1 border-l border-border pl-0">
      {events.map((event, index) => (
        <EventRow key={event.id} event={event} index={index} />
      ))}
    </ol>
  )
}

export function EventRow({ event, index }: { event: AuditEvent; index: number }) {
  const tone = eventTone(event)
  const action = describeAction(event.action)
  const attention = needsAttention(event)

  return (
    <li
      className="enter-up relative py-2.5 pl-6"
      style={{ "--i": Math.min(index, 12) } as CSSProperties}
    >
      <span
        aria-hidden="true"
        className={cn(
          "absolute top-4 left-[-4.5px] size-2 rounded-full ring-4 ring-background",
          DOT[tone]
        )}
      />
      <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
        <p className="text-sm text-foreground">
          <span className="font-medium">{WHO[tone]}</span>{" "}
          {action.label.toLowerCase()}{" "}
          <span
            className={cn(
              attention ? "text-destructive" : "text-muted-foreground"
            )}
          >
            — {describeOutcome(event.outcome)}
          </span>
        </p>
        <time
          className="text-xs text-muted-foreground"
          dateTime={event.recorded_at ?? undefined}
          title={formatDateTime(event.recorded_at)}
        >
          {formatRelativeTime(event.recorded_at)}
        </time>
      </div>

      <Disclosure summary="Technical detail">
        <dl className="grid gap-x-6 gap-y-2 text-xs sm:grid-cols-2">
          <Detail label="Action" value={event.action} mono />
          <Detail label="Outcome" value={event.outcome} />
          <Detail label="Actor" value={`${event.actor} (${actorWord(event)})`} />
          <Detail label="Resource" value={event.resource} mono />
          {event.workflow_id ? (
            <Detail label="Workflow" value={event.workflow_id} mono />
          ) : null}
          <Detail label="Recorded" value={formatDateTime(event.recorded_at)} />
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
      </Disclosure>
    </li>
  )
}

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
 * One execution, reassembled from the audit rows that share a workflow.
 *
 * The timeline reads top to bottom in the order the events happened — the
 * order the server recorded them, not the order a reader assumes they
 * occurred in. A run that hit a failure says so at the top, so it is not
 * buried under a long list of successful steps.
 */
export function RunTimeline({ run }: { run: AgentRun }) {
  return (
    <div className="rounded-xl border border-border bg-card p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="min-w-0">
          <p className="font-heading text-sm font-semibold text-foreground">
            Workflow{" "}
            <code className="font-mono text-xs text-muted-foreground">
              {run.workflowId}
            </code>
          </p>
          <p className="mt-0.5 text-xs text-muted-foreground">
            {run.events.length} step{run.events.length === 1 ? "" : "s"} ·{" "}
            started {formatRelativeTime(run.startedAt)}
          </p>
        </div>
        <span
          className={cn(
            "rounded-full border px-2.5 py-0.5 text-[11px] font-medium",
            run.hasFailure
              ? "border-destructive/40 bg-destructive/10 text-destructive"
              : "border-lime/70 bg-lime-soft text-lime-foreground"
          )}
        >
          {run.hasFailure ? "Needs attention" : "Completed cleanly"}
        </span>
      </div>
      {/*
        The steps are closed by default. An execution is a long list, and the
        screen lists several of them; opening the one you care about keeps the
        page readable.
      */}
      <div className="mt-3">
        <Disclosure summary="The steps" hint={`${run.events.length} recorded`}>
          <EventList events={run.events} />
        </Disclosure>
      </div>
    </div>
  )
}
