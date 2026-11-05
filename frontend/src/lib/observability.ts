import type { AuditEvent } from "@/lib/api/types"

/**
 * The observability vocabulary.
 *
 * The rule is the console's rule everywhere: it **never invents** an
 * event. Each label here is keyed by the exact action string the server
 * writes (see `src/security/audit.py`'s `ACTION_*` constants), and an
 * action this file does not know is shown **verbatim** in a neutral tone.
 * A timeline that quietly dropped an unrecognised row would be a timeline
 * that lies about what happened.
 */

/** Whether an event is a normal step or something that needs a human eye. */
export type EventTone = "agent" | "human" | "system" | "attention" | "failure"

/** A human label for one action, and whether it is an attention/failure one. */
export interface ActionPresentation {
  label: string
  attention: boolean
}

const ACTIONS: Record<string, ActionPresentation> = {
  "resume.upload": { label: "Uploaded and parsed a résumé", attention: false },
  "job.search": { label: "Searched the job corpus", attention: false },
  "match.compute": { label: "Scored listings against the profile", attention: false },
  "application.prepare": { label: "Prepared an application", attention: false },
  "application.approve": { label: "Approved an application", attention: false },
  "application.reject": { label: "Rejected an application", attention: false },
  "application.submit": { label: "Submitted an application", attention: false },
  "application.verify": { label: "Verified a submission", attention: false },
  "application.transition": { label: "Changed an application's status", attention: false },
  "application.event": { label: "Recorded an application event", attention: false },
  "application.permission_denied": {
    label: "Refused a permission request",
    attention: true,
  },
  "application.unsafe_navigation": {
    label: "Blocked a redirect to an unapproved host",
    attention: true,
  },
  "application.blocked_challenge": {
    label: "Stopped at a CAPTCHA or multi-factor prompt",
    attention: true,
  },
  "allowlist.violation": { label: "Blocked a domain not on the allowlist", attention: true },
  "llm.usage": { label: "Used the model provider", attention: false },
  auth: { label: "Authenticated", attention: false },
  retention: { label: "Ran the retention pass", attention: false },
}

/** A human label for an action. Unknown actions are shown verbatim. */
export function describeAction(action: string): ActionPresentation {
  return (
    (Object.hasOwn(ACTIONS, action) ? ACTIONS[action] : undefined) ?? {
      label: action,
      attention: false,
    }
  )
}

const OUTCOMES: Record<string, string> = {
  success: "succeeded",
  blocked: "was blocked",
  denied: "was denied",
  error: "failed",
}

/** A human label for an outcome. Unknown outcomes are shown verbatim. */
export function describeOutcome(outcome: string): string {
  return (Object.hasOwn(OUTCOMES, outcome) ? OUTCOMES[outcome] : undefined) ?? outcome
}

/** The tone of an event, from its actor and its outcome. */
export function eventTone(event: AuditEvent): EventTone {
  if (event.outcome === "error") return "failure"
  if (event.outcome === "blocked" || event.outcome === "denied") return "attention"
  if (event.actor_kind === "agent") return "agent"
  if (event.actor_kind === "user") return "human"
  return "system"
}

/** True when the event is not a clean success — the ones a human cares about. */
export function needsAttention(event: AuditEvent): boolean {
  const tone = eventTone(event)
  return tone === "failure" || tone === "attention" || describeAction(event.action).attention
}

/**
 * One workflow execution, reassembled from the audit rows that share its
 * `workflow_id`.
 *
 * There is no "run" table — the correlation id on the audit rows is the
 * only thing that ties an execution together, and this groups by it. Rows
 * with no workflow (an upload, a search) are not a "run" and are kept in
 * the plain chronological feed instead.
 */
export interface AgentRun {
  workflowId: string
  events: AuditEvent[]
  startedAt: string | null
  endedAt: string | null
  /** True when any event in the run needs a human eye. */
  hasFailure: boolean
  /** The most recent event, for the one-line summary. */
  latest: AuditEvent
}

/** Group workflow-bearing events into runs, newest run first. */
export function groupRuns(events: AuditEvent[]): AgentRun[] {
  const byWorkflow = new Map<string, AuditEvent[]>()
  for (const event of events) {
    if (!event.workflow_id) continue
    const list = byWorkflow.get(event.workflow_id)
    if (list) list.push(event)
    else byWorkflow.set(event.workflow_id, [event])
  }

  const runs: AgentRun[] = []
  for (const [workflowId, list] of byWorkflow) {
    // The feed is newest-first; a run reads oldest-first, so reverse it.
    const ordered = [...list].reverse()
    const first = ordered[0]
    const last = ordered[ordered.length - 1]
    if (!first || !last) continue
    runs.push({
      workflowId,
      events: ordered,
      startedAt: first.recorded_at,
      endedAt: last.recorded_at,
      hasFailure: ordered.some(needsAttention),
      latest: last,
    })
  }

  runs.sort((a, b) => (b.endedAt ?? "").localeCompare(a.endedAt ?? ""))
  return runs
}

/** A compact count of the feed, for the overview's stat tiles. */
export interface AuditSummary {
  total: number
  agent: number
  human: number
  attention: number
}

export function summarizeEvents(events: AuditEvent[]): AuditSummary {
  let agent = 0
  let human = 0
  let attention = 0
  for (const event of events) {
    if (event.actor_kind === "agent") agent += 1
    if (event.actor_kind === "user") human += 1
    if (needsAttention(event)) attention += 1
  }
  return { total: events.length, agent, human, attention }
}

/**
 * A short "how long ago" for a timestamp.
 *
 * A fresh timestamp is the difference between a live-looking screen and a
 * stale one, so the console shows when its data was read rather than
 * implying it is streaming.
 */
export function formatRelativeTime(
  value: string | null | undefined,
  now: number = Date.now()
): string {
  if (!value) return "—"
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return value
  const seconds = Math.round((now - parsed.getTime()) / 1000)
  if (seconds < 5) return "just now"
  if (seconds < 60) return `${seconds}s ago`
  const minutes = Math.round(seconds / 60)
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.round(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  const days = Math.round(hours / 24)
  return `${days}d ago`
}
