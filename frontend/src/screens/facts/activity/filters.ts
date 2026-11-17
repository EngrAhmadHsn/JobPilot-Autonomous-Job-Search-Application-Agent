import type { AuditEvent } from "@/lib/api/types"
import { needsAttention } from "@/lib/observability"

/*
  The Activity Center's filters (WS-40).

  The reference panel 7 draws four chips — All / Agent / Applications /
  System — and the temptation is to draw four chips whatever the backend
  returns. This module maps each chip onto a filter the audit data can
  actually answer, and **omits none of them as decoration**: every chip here
  is backed by a real field on `AuditEvent`.

  | chip         | the field it filters                      |
  |--------------|-------------------------------------------|
  | All          | no filter                                 |
  | Agent        | `actor_kind === "agent"`                   |
  | Applications | `workflow_id != null` (a workflow of ours) |
  | System       | `actor_kind === "system"`                  |

  "Applications" is the one worth explaining: there is no `application_id`
  on an audit row and no separate application event stream. What legitimately
  ties an action to an application workflow is `workflow_id` — the same
  correlation id `groupRuns` uses — so the chip selects exactly the rows that
  belong to an execution. Rows with no workflow (a corpus refresh, an upload)
  stay in All and in System.

  The reference also draws "Mark all as read". That is **not implemented**:
  the audit API has no read-state field and no mark-read route, so a button
  would change nothing on the server. The last-read timestamp is stated
  truthfully instead.
*/

/** The chips, in the reference's order. */
export const ACTIVITY_FILTERS = [
  { value: "all", label: "All" },
  { value: "agent", label: "Agent" },
  { value: "applications", label: "Applications" },
  { value: "system", label: "System" },
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
    case "agent":
      return event.actor_kind === "agent"
    case "applications":
      // A workflow row: the same correlation id `groupRuns` groups on.
      return Boolean(event.workflow_id)
    case "system":
      return event.actor_kind === "system"
  }
}

/**
 * The one line of the compact feed: what happened, in the server's own
 * vocabulary. `describeAction` supplies the human label; this picks the
 * sentence shape.
 */
export interface FeedRow {
  event: AuditEvent
  /** True when the row is not a clean success — it gets the attention mark. */
  attention: boolean
}

/** The rows for one chip, newest first (the API already orders them so). */
export function filterEvents(
  events: AuditEvent[],
  filter: ActivityFilter
): FeedRow[] {
  return events
    .filter((event) => matchesFilter(event, filter))
    .map((event) => ({ event, attention: needsAttention(event) }))
}
