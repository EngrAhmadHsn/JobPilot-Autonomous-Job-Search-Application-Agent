import { formatTimeOfDay } from "@/lib/format"

import { describeStatus, isHumanOutcomeStatus } from "@/lib/status"
import type { ApplicationSummary } from "@/lib/api/types"

/*
  The board card's per-stage presentation (WS-42, from the design file's
  screen 05, nodes 49:1157–49:1254).

  The design draws every card with the same five parts — a stage chip, a
  one-line helper, a divider, a CTA pill and a timestamp — and it words the
  chips in journey language ("Packet ready", "Employer handoff", "Accepted
  and queued"). Those words are the spec **where they are true of this
  backend**; where a phrase would misstate a status, the console's own
  vocabulary wins, because the legend under the board (node 49:1255) is the
  honesty contract: "Queued does not mean sent. Employer handoff does not
  mean submitted."

  The mapping below records, per status family, which sentences are the
  design's and which are the console's, and every timestamp is derived from
  a field the server actually holds — nothing is invented to look tidy.
*/

/** The stage tint a status family renders with (design chip fills). */
export type StageTone = "review" | "handoff" | "progress" | "outcome"

const CHIP_TONES: Record<StageTone, string> = {
  // The design's stage chips: #faeee6 (review), #eef9c4 (progress),
  // #e6ece8 (outcome). "handoff" shares the review tint.
  review: "bg-terracotta-soft",
  handoff: "bg-terracotta-soft",
  progress: "bg-lime-soft",
  outcome: "bg-forest-soft",
}

/**
 * The stage chip's text and tint.
 *
 * - `prepared`/`awaiting_approval` → the design's "Packet ready": true —
 *   the payload exists and waits for a decision.
 * - `verified` → the console's "Verified", **not** the design's "Employer
 *   handoff": the evidence already confirms a submission landed, so
 *   "Employer handoff" (which the legend itself disclaims as "not
 *   submitted") would present a done row as a pending handoff.
 * - `submitted` → the console's "Submitted, not yet verified", not the
 *   design's "Accepted and queued": nothing "accepted" it — the worker
 *   submitted the form and the confirmation is still pending.
 * - A human outcome → the design's "{Outcome} · recorded by you": every
 *   outcome in this backend was set by a person (the backend refuses
 *   agent-set outcomes), so "recorded by you" is true of the operator who
 *   recorded it in the console.
 * - Anything else → the raw status, verbatim, in a quiet tint.
 */
export function stageChip(status: string): { label: string; tone: string } {
  if (status === "prepared" || status === "awaiting_approval") {
    return { label: "Packet ready", tone: CHIP_TONES.review }
  }
  if (isHumanOutcomeStatus(status)) {
    return {
      label: `${describeStatus(status).label} · recorded by you`,
      tone: CHIP_TONES.outcome,
    }
  }
  if (status === "verified") {
    return { label: describeStatus(status).label, tone: CHIP_TONES.handoff }
  }
  if (status === "submitted") {
    return { label: describeStatus(status).label, tone: CHIP_TONES.progress }
  }
  // An unfamiliar status renders verbatim, in the quiet tint — the console
  // shows what the server sent rather than interpreting it.
  return { label: describeStatus(status).label, tone: CHIP_TONES.outcome }
}

/**
 * The card's helper line (the design's 12/400 sentence under the chip).
 *
 * The design's sentences are kept where they are true of this backend;
 * the "Needs you" and "In progress" columns get the console's own words,
 * because the design's ("You review and submit on the employer site.",
 * "Waiting for an available worker. Not submitted.") would describe rows
 * whose machine work is already done or already submitted.
 */
export function stageHelper(status: string): string {
  if (status === "prepared" || status === "awaiting_approval") {
    // The design's own helper (49:1165) — true here.
    return "Review the prepared packet before taking the next step."
  }
  if (status === "verified") {
    // The stage's meaning (stage-groups.ts), restated per card: the
    // submission is confirmed; the outcome is the human's to record.
    return "Confirmed by evidence. Nothing further happens until you record the outcome."
  }
  if (status === "submitted") {
    // The status's own next-step line (lib/status.ts): the form was
    // submitted; the confirmation still has to be verified.
    return "The form was submitted. The confirmation still has to be verified."
  }
  if (isHumanOutcomeStatus(status)) {
    // The design's helper (49:1250) — true here.
    return "Your human outcome is separate from agent execution."
  }
  return describeStatus(status).nextStep
}

/**
 * The card's CTA pill (the design's outline pill under the divider).
 *
 * The design's labels are kept where the action they name is the one the
 * detail screen actually offers. "Open handoff details →" (49:1205) is
 * replaced by "Record the outcome →": the verified row's next action is
 * recording what came of it, and the outcome editor lives on the detail.
 */
export function stageCta(status: string): string {
  if (status === "prepared" || status === "awaiting_approval") {
    // The design's ready-packet CTA (49:1181). The design also draws
    // "Confirm sponsorship answer →" for a packet with a missing answer —
    // a per-application fact the summary row does not carry, so the one
    // honest CTA is the review one.
    return "Review application →"
  }
  if (status === "verified") {
    return "Record the outcome →"
  }
  if (status === "submitted") {
    // The design's CTA (49:1229): the detail's ordered history carries the
    // execution events, so "execution progress" is where this points.
    return "View execution progress →"
  }
  if (isHumanOutcomeStatus(status)) {
    // The design's CTA (49:1253).
    return "Open application history →"
  }
  return "Open application details →"
}

/**
 * A server timestamp, in the card's timestamp voice: "today, 09:12" —
 * "yesterday" — "on 10/21/2026". Clock truth, in the design's shape.
 */
function when(iso: string): string {
  const parsed = new Date(iso)
  if (Number.isNaN(parsed.getTime())) return ""
  const now = new Date()
  const day = (date: Date) =>
    new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime()
  const diffDays = Math.round((day(now) - day(parsed)) / 86_400_000)
  if (diffDays === 0) return `today, ${formatTimeOfDay(iso)}`
  if (diffDays === 1) return "yesterday"
  return `on ${parsed.toLocaleDateString()}`
}

/**
 * The card's timestamp line (the design's 11/400 footer).
 *
 * Each stage names the fact the server actually holds: the row was
 * *prepared* (created_at — a tracked row is created `prepared`), the
 * submission was *confirmed* (verified_at), the form was *submitted*
 * (submitted_at), and for outcomes the row's last update — the console
 * does not claim "Outcome added" of a field that also moves on note edits.
 */
export function stageTimestamp(application: ApplicationSummary): string {
  const stamp = (iso: string | null | undefined, phrase: string) => {
    if (!iso) return null
    const rest = when(iso)
    return rest ? `${phrase} ${rest}` : null
  }
  switch (application.status) {
    case "prepared":
    case "awaiting_approval":
      return (
        stamp(application.created_at, "Prepared") ??
        stamp(application.updated_at, "Updated") ??
        ""
      )
    case "verified":
      return (
        stamp(application.verified_at, "Confirmed by evidence") ??
        stamp(application.updated_at, "Updated") ??
        ""
      )
    case "submitted":
      return (
        stamp(application.submitted_at, "Submitted") ??
        stamp(application.updated_at, "Updated") ??
        ""
      )
    default:
      return (
        stamp(application.updated_at, "Updated") ??
        stamp(application.created_at, "Prepared") ??
        ""
      )
  }
}
