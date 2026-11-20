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

/*
  The chip's own word (the design's chips read AGENT / YOU — node 49:811,
  49:820): first-person for a human act, named for the machine actors.
*/
const CHIP_LABEL: Record<EventTone, string> = {
  agent: "Agent",
  human: "You",
  system: "System",
  attention: "System",
  failure: "System",
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

/*
  The chip washes, by tone (the design's node 49:811): the agent's lime-soft,
  a person's clay wash, the system's sage. Failure keeps its destructive
  detail text — the chip names the actor, the detail line names the problem.
*/
const CHIP: Record<EventTone, string> = {
  agent: "bg-lime-soft text-forest",
  human: "bg-terracotta-soft text-terracotta-foreground",
  system: "bg-forest-soft text-forest",
  attention: "bg-forest-soft text-forest",
  failure: "bg-forest-soft text-forest",
}

function ActivityRow({ event, index }: { event: AuditEvent; index: number }) {
  const tone = eventTone(event)
  const action = describeAction(event.action)
  const attention = needsAttention(event)
  const link = eventLink(event)

  return (
    <li
      className="enter-up border-b border-border-surface py-3 first:pt-0 last:border-b-0 last:pb-0"
      style={{ "--i": Math.min(index, 12) } as CSSProperties}
    >
      {/*
        The design's digest row (node 49:810): actor chip and time on one
        line, then the title, the detail, and the quiet action. The chip
        still names the actor for the screen reader — attribution survives
        the restyle verbatim ("Agent", "You", "System").
      */}
      <div className="flex items-center gap-2.5">
        <span
          className={cn(
            "type-eyebrow rounded-md px-2 py-1 uppercase",
            CHIP[tone]
          )}
        >
          {CHIP_LABEL[tone]}
        </span>
        <time
          className="type-caption"
          dateTime={event.recorded_at ?? undefined}
          title={formatDateTime(event.recorded_at)}
        >
          <RelativeTime value={event.recorded_at} />
        </time>
      </div>
      <p className="mt-1.5 text-[15px] leading-[22px] font-semibold text-forest">
        {action.label}
      </p>
      <p
        className={cn(
          "type-caption mt-1.5",
          attention && "text-destructive"
        )}
      >
        {describeOutcome(event.outcome)}
      </p>
      {link ? (
        <Link
          to={link.to}
          viewTransition
          className="mt-1.5 inline-flex items-center gap-1 rounded text-[13px] font-semibold text-forest outline-none hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
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
    <ol className="space-y-0">
      {events.map((event, index) => (
        <ActivityRow key={event.id} event={event} index={index} />
      ))}
    </ol>
  )
}
