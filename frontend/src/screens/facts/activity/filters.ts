import type { AuditEvent } from "@/lib/api/types"
import { needsAttention } from "@/lib/observability"

/*
  The Activity screen's filters (WS-40, rebuilt to the design file's screen
  `16:242` in WS-42).

  The design draws three chips — All activity · Needs you · Agent work. This
  module maps each chip onto a filter the audit data can actually answer,
  and **omits none of them as decoration**: every chip here is backed by a
  real field or a real derived predicate on `AuditEvent`.

  | chip        | the field it filters                   |
  |-------------|----------------------------------------|
  | All         | no filter                              |
  | Needs you   | `needsAttention(event)` — the derived   |
  |             | predicate: refused, blocked, or failed |
  | Agent work  | `actor_kind === "agent"`               |

  WS-40 carried "Needs attention" as a separate toggle beside four actor
  chips, because folding a derived predicate into an actor radio group would
  claim it is a fifth *source* of events. The design file settles the
  question differently: its own vocabulary puts "Needs you" and "Agent work"
  side by side as views of one trail, which is what they are — so the chips
  follow the design, and each still filters on something the data answers.
  The rows the design's three chips do not name (a person's decision, a
  system pass) stay visible under All activity.

  The reference also draws "Mark all as read". That is **not implemented**:
  the audit API has no read-state field and no mark-read route, so a button
  would change nothing on the server. The last-read timestamp is stated
  truthfully instead.
*/

/** The chips, in the design's order. */
export const ACTIVITY_FILTERS = [
  { value: "all", label: "All activity" },
  { value: "attention", label: "Needs you" },
  { value: "agent", label: "Agent work" },
] as const

export type ActivityFilter = (typeof ACTIVITY_FILTERS)[number]["value"]

/** Does the event belong to the chosen chip? */
export function matchesFilter(
  event: AuditEvent,
  filter: ActivityFilter
): boolean {
  switch (filter) {
    case "all":
      return true
    case "attention":
      return needsAttention(event)
    case "agent":
      return event.actor_kind === "agent"
  }
}
