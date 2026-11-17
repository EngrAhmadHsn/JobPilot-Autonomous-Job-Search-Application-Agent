import { cn } from "cn"

import { PlainText } from "@/components/common/plain-text"
import { StatusBadge } from "@/components/ui/status-badge"

import { formatDateTime } from "@/lib/format"
import { stagger } from "@/lib/stagger"
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
*/
const ACTOR_CHIP_CLASSES: Record<ActorKind, string> = {
  agent: "border-lime/70 bg-lime-soft text-lime-foreground",
  human: "border-terracotta bg-terracotta-soft text-terracotta-foreground",
  system: "border-border bg-muted text-muted-foreground",
  unknown: "border-border bg-muted text-muted-foreground",
}

const ACTOR_DOT_CLASSES: Record<ActorKind, string> = {
  agent: "bg-lime",
  human: "bg-terracotta",
  system: "bg-border",
  unknown: "bg-border",
}

/**
 * The application's chronology (WS-39) — the detail view's Timeline.
 *
 * The events are the server's, already in append order (event id order, so
 * two events written in the same millisecond keep their real order); this
 * component renders them in the order given and does not re-sort. Every
 * event carries its actor chip (lime = the agent, terracotta = a person,
 * per the semantic law), the transition it records, the absolute timestamp
 * — a chronology is a record, so it shows clock time, not "2 hours ago" —
 * and the metadata the server attached, sanitized before it was stored.
 */
export function ApplicationTimeline({
  events,
}: {
  events: ApplicationEvent[]
}) {
  return (
    <ol aria-label="Application timeline" className="space-y-5">
      {events.map((event, index) => {
        const actor = actorKind(event.actor)
        const metadata = event.metadata ?? {}
        const entries = Object.entries(metadata).filter(
          ([, value]) => value !== null && value !== undefined
        )

        return (
          <li
            key={event.id}
            data-event-id={event.id}
            {...stagger(index, "relative border-l-2 border-border pl-5")}
          >
            {/*
              The marker dot: colour rides with the actor kind, and the
              chip spells the actor out — colour never carries the meaning
              alone.
            */}
            <span
              aria-hidden={true}
              className={cn(
                "absolute top-1.5 -left-[7px] size-3 rounded-full border-2 border-card",
                ACTOR_DOT_CLASSES[actor.kind]
              )}
            />
            <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
              <span className="font-mono text-sm font-medium text-foreground">
                {event.event_type}
              </span>
              <span
                data-actor-kind={actor.kind}
                className={cn(
                  "inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-medium",
                  ACTOR_CHIP_CLASSES[actor.kind]
                )}
              >
                {actor.kind === "human" ? `Human · ${actor.name}` : actor.name}
              </span>
              <span className="text-xs text-muted-foreground tabular-nums">
                {formatDateTime(event.recorded_at)}
              </span>
            </div>
            {event.from_status || event.to_status ? (
              <div className="mt-1.5 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                <span className="font-mono">{event.from_status ?? "—"}</span>
                <span aria-hidden={true}>→</span>
                <span className="font-mono">{event.to_status ?? "—"}</span>
                <StatusBadge status={event.to_status} withIcon={false} />
              </div>
            ) : null}
            {entries.length > 0 ? (
              <dl className="mt-2 space-y-1 text-xs text-muted-foreground">
                {entries.map(([key, value]) => (
                  <div key={key} className="flex gap-2">
                    <dt className="shrink-0 font-mono">{key}:</dt>
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
