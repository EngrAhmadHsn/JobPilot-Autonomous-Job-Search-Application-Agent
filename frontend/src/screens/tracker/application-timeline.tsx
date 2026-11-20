import { cn } from "cn"

import { PlainText } from "@/components/common/plain-text"

import { formatDateTime } from "@/lib/format"
import { stagger } from "@/lib/stagger"
import { describeStatus } from "@/lib/status"
import type { ApplicationEvent } from "@/lib/api/types"

/*
  Who caused an event, as the console classifies actors.

  The backend's actor strings are exactly three shapes (`src/applications/
  tracking.py`): `agent`, `system`, and `human:<who>` — the prefix is what
  makes the distinction checkable. Anything else renders verbatim in a
  neutral chip: an actor the console does not recognise is shown, not
  interpreted.
*/
type ActorKind = "agent" | "human" | "system" | "unknown"

function actorKind(actor: string): {
  kind: ActorKind
  /** The display name — the `human:` prefix strips off. */
  name: string
} {
  if (actor === "agent") return { kind: "agent", name: "Agent" }
  if (actor === "system") return { kind: "system", name: "System" }
  if (actor.startsWith("human:") && actor.length > "human:".length) {
    return { kind: "human", name: actor.slice("human:".length) }
  }
  return { kind: "unknown", name: actor }
}

/*
  The tone law, applied to the actor (WS-39): **lime is the agent,
  terracotta is a human.** System actions are quiet paper. The classes are
  the badge tones of the same two colours, so the timeline and the status
  badges can never disagree about who did what.

  The design file draws both chips in one sage tint (node 49:1092's rows);
  the console keeps the two-colour law on purpose — flattening "Agent" and
  "You" into one tint would hide exactly the attribution this trail exists
  to prove. The chips keep the design's shape (24 px, 11/600).
*/
const ACTOR_CHIP_CLASSES: Record<ActorKind, string> = {
  agent: "border-lime/70 bg-lime-soft text-lime-foreground",
  human: "border-terracotta bg-terracotta-soft text-terracotta-foreground",
  system: "border-border bg-muted text-muted-foreground",
  unknown: "border-border bg-muted text-muted-foreground",
}

/**
 * One event, in the trail's human voice (design nodes 49:2152–49:2177):
 * a 14/600 title over a 12/400 explanation — never the raw `event_type`.
 *
 * The mapping is honest by construction: a known event type says what the
 * backend records it as meaning, a status transition names the status the
 * server moved to (in the console's vocabulary), and an event type the
 * console does not know renders verbatim rather than being paraphrased
 * into something it may not be.
 */
function eventPresentation(event: ApplicationEvent): {
  title: string
  detail: string | null
} {
  switch (event.event_type) {
    case "application_created":
      return {
        title: "Application created",
        detail: "The tracked row was created for this application.",
      }
    case "approval_granted":
      // The design's row (49:2159): the decision and the identity behind
      // it are both on the record.
      return {
        title: "Approval recorded",
        detail: "Identity and decision saved.",
      }
    case "approval_rejected":
      return {
        title: "Approval declined",
        detail: "Nothing was submitted.",
      }
    case "evidence_recorded":
      return {
        title: "Evidence recorded",
        detail: "The artifacts were saved to this record.",
      }
    case "verification_failed":
      return {
        title: "Verification failed",
        detail: "The submission is not confirmed.",
      }
    case "status_transition": {
      const to = event.to_status
        ? describeStatus(event.to_status).label
        : null
      const from = event.from_status
        ? describeStatus(event.from_status).label
        : null
      return {
        title: to ? `Moved to ${to}` : (event.event_type),
        detail:
          from && to
            ? `From ${from} to ${to}.`
            : to
              ? `The status is now ${to}.`
              : null,
      }
    }
    default:
      // An unknown event type is shown verbatim — paraphrasing a fact the
      // console does not understand would be inventing one.
      return { title: event.event_type, detail: null }
  }
}

/**
 * The trail's time voice: a compact date-and-clock stamp. The design's
 * rows show "09:42" — a clock alone, which would read as same-day even
 * when a trail spans days — so the stamp carries a short date too, and the
 * full timestamp rides in `title`.
 */
function formatTrailTime(iso: string): string {
  const parsed = new Date(iso)
  if (Number.isNaN(parsed.getTime())) return iso
  return parsed.toLocaleString([], {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  })
}

/**
 * The application's chronology (WS-39, restyled to the design's "Ordered
 * history" in WS-42).
 *
 * The events are the server's, already in append order (event id order, so
 * two events written in the same millisecond keep their real order); this
 * component renders them in the order given and does not re-sort. Every
 * event carries its actor chip (lime = the agent, terracotta = a person,
 * per the semantic law), the human-voiced title above, and the metadata the
 * server attached, sanitized before it was stored — the metadata stays
 * visible below the design's two lines because run ids and decision
 * records are provenance, not decoration.
 */
export function ApplicationTimeline({
  events,
}: {
  events: ApplicationEvent[]
}) {
  return (
    <ol aria-label="Application timeline" className="space-y-4">
      {events.map((event, index) => {
        const actor = actorKind(event.actor)
        const presentation = eventPresentation(event)
        const metadata = event.metadata ?? {}
        const entries = Object.entries(metadata).filter(
          ([, value]) => value !== null && value !== undefined
        )

        return (
          <li
            key={event.id}
            data-event-id={event.id}
            {...stagger(index, "relative")}
          >
            <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1.5">
              <span
                title={formatDateTime(event.recorded_at)}
                className="w-[86px] shrink-0 text-xs leading-[17px] text-muted-foreground tabular-nums"
              >
                {formatTrailTime(event.recorded_at)}
              </span>
              <span
                data-actor-kind={actor.kind}
                className={cn(
                  "inline-flex shrink-0 items-center rounded-md border px-[9px] py-1 text-[11px] font-semibold leading-4",
                  ACTOR_CHIP_CLASSES[actor.kind]
                )}
              >
                {actor.kind === "human" ? `Human · ${actor.name}` : actor.name}
              </span>
              <span className="min-w-0 flex-1 basis-48">
                <span className="block text-sm font-semibold leading-5 text-primary">
                  {presentation.title}
                </span>
                {presentation.detail ? (
                  <span className="mt-0.5 block text-xs leading-[17px] text-muted-foreground">
                    {presentation.detail}
                  </span>
                ) : null}
              </span>
            </div>
            {entries.length > 0 ? (
              <dl className="ml-[110px] mt-1.5 space-y-1 text-xs text-muted-foreground md:ml-[118px]">
                {entries.map(([key, value]) => (
                  <div key={key} className="flex gap-2">
                    <dt className="shrink-0">{key}:</dt>
                    <dd className="min-w-0 break-words">
                      <PlainText as="span">
                        {typeof value === "string"
                          ? value
                          : JSON.stringify(value)}
                      </PlainText>
                    </dd>
                  </div>
                ))}
              </dl>
            ) : null}
          </li>
        )
      })}
    </ol>
  )
}
