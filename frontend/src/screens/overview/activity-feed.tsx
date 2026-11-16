import { cn } from "cn"
import type { CSSProperties } from "react"
import { Link } from "react-router-dom"

import { RelativeTime } from "@/components/common/relative-time"
import { formatDateTime } from "@/lib/format"
import type { AuditEvent } from "@/lib/api/types"
import {
  describeAction,
  describeOutcome,
  eventTone,
  needsAttention,
  type EventTone,
} from "@/lib/observability"

/*
  The Home activity column (WS-35) — the reference's "Agent Activity",
  grounded in the account's own audit trail.

  The colour law is the trail's own: **lime is the agent, terracotta is a
  person**, and a blocked or failed step is called out. Each row names its
  actor ("The agent searched…", "A person approved…") — attribution is the
  point of the column — and where a real destination exists, the row links
  to the screen that can resolve what it describes.

  There is no "Live" badge: the trail is a polled page, and the section
  under this component says so with its interval. The window is honest too —
  the feed is the **first page of the trail** (the newest 100 events the
  endpoint returns), never presented as the account's whole history.
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

/**
 * The screen that can resolve one event, when one exists.
 *
 * The mapping is by the trail's own closed vocabulary (`lib/observability`):
 * approval work is reviewed on Approvals, submission and verification work
 * is tracked in the Tracker, refusals live in the full trail, and profile
 * and search steps lead back to their surfaces. An unknown action links
 * nowhere rather than to a guessed destination. (The trail's `resource` is
 * not the application id — prepare and approve record the **approval** id —
 * so a deep link to a specific application cannot be built from a trail row
 * without guessing.)
 */
export function eventLink(
  event: AuditEvent
): { to: string; label: string } | null {
  switch (event.action) {
    case "application.prepare":
    case "application.approve":
    case "application.reject":
      return { to: "/app/approvals", label: "Review" }
    case "application.submit":
    case "application.verify":
    case "application.transition":
    case "application.event":
      return { to: "/app/tracker", label: "Track" }
    case "application.permission_denied":
    case "application.unsafe_navigation":
    case "application.blocked_challenge":
    case "allowlist.violation":
      return { to: "/app/activity", label: "Trail" }
    case "resume.upload":
      return { to: "/app/resume", label: "Resume" }
    case "job.search":
    case "match.compute":
      return { to: "/app/matches", label: "Matches" }
    default:
      return null
  }
}

function ActivityRow({ event, index }: { event: AuditEvent; index: number }) {
  const tone = eventTone(event)
  const action = describeAction(event.action)
  const attention = needsAttention(event)
  const link = eventLink(event)

  return (
    <li
      className="enter-up relative py-2.5 ps-6"
      style={{ "--i": Math.min(index, 12) } as CSSProperties}
    >
      <span
        aria-hidden="true"
        className={cn(
          "absolute start-[-4.5px] top-4 size-2 rounded-full ring-4 ring-background",
          DOT[tone]
        )}
      />
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5">
        <p className="text-sm text-foreground">
          <span className="font-medium">{WHO[tone]}</span>{" "}
          {action.label.toLowerCase()}{" "}
          <span
            className={cn(
              "text-muted-foreground",
              attention && "text-destructive"
            )}
          >
            — {describeOutcome(event.outcome)}
          </span>
        </p>
        <time
          className="text-xs text-muted-foreground tabular-nums"
          dateTime={event.recorded_at ?? undefined}
          title={formatDateTime(event.recorded_at)}
        >
          <RelativeTime value={event.recorded_at} />
        </time>
      </div>
      {link ? (
        <Link
          to={link.to}
          viewTransition
          className="mt-0.5 inline-flex items-center gap-1 text-xs font-medium text-muted-foreground underline-offset-4 hover:text-foreground hover:underline"
        >
          {link.label} <span aria-hidden="true">→</span>
          <span className="sr-only">
            — {describeAction(event.action).label.toLowerCase()}
          </span>
        </Link>
      ) : null}
    </li>
  )
}

/** The newest few audit rows, attributed and linked. */
export function ActivityFeed({ events }: { events: AuditEvent[] }) {
  return (
    <ol className="relative space-y-1 border-s border-border ps-0">
      {events.map((event, index) => (
        <ActivityRow key={event.id} event={event} index={index} />
      ))}
    </ol>
  )
}
