import { describe, expect, it } from "vitest"

import { STATUS_ICONS } from "@/components/ui/status-badge"
import {
  APPLICATION_STATUS_NAMES,
  HUMAN_OUTCOME_STATUS_NAMES,
  KNOWN_STATUS_NAMES,
  describeStatus,
  isHumanOutcomeStatus,
} from "@/lib/status"

describe("the status vocabulary", () => {
  it("labels every status the backend can report", () => {
    const known = [
      "discovered",
      "matched",
      "shortlisted",
      "prepared",
      "awaiting_approval",
      "submitted",
      "verified",
      "rejected",
      "interview",
      "offer",
      "withdrawn",
      "needs_human",
      "form_error",
      "blocked_human_review",
      "verification_failed",
      "unsafe_navigation",
      "pending",
      "approved",
      "executed",
      "failed",
      // WS-32: the approve answer carries the run's own status.
      "QUEUED",
    ]
    for (const status of known) {
      const presentation = describeStatus(status)
      expect(presentation.label).not.toBe("")
      expect(presentation.nextStep.length).toBeGreaterThan(10)
    }
  })

  it("shows an unknown status verbatim instead of hiding it", () => {
    const presentation = describeStatus("something_new")
    expect(presentation.label).toBe("something_new")
    expect(presentation.tone).toBe("neutral")
  })

  it("names the next step for the statuses that need a human", () => {
    expect(describeStatus("needs_human").label).toBe("Needs a human answer")
    expect(describeStatus("needs_human").nextStep).toContain("answer")
    expect(describeStatus("awaiting_approval").nextStep).toContain("approve")
    expect(describeStatus("blocked_human_review").nextStep).toContain("CAPTCHA")
  })

  it("knows which statuses only a human may set", () => {
    expect(isHumanOutcomeStatus("interview")).toBe(true)
    expect(isHumanOutcomeStatus("offer")).toBe(true)
    expect(isHumanOutcomeStatus("rejected")).toBe(true)
    expect(isHumanOutcomeStatus("withdrawn")).toBe(true)
    expect(isHumanOutcomeStatus("submitted")).toBe(false)
    expect(isHumanOutcomeStatus("verified")).toBe(false)
  })
})

/**
 * WS-15: the status map is built with a null prototype, so a status named
 * after an `Object.prototype` member is an unknown status — shown
 * verbatim — and not a silent blank badge.
 */
describe("the status vocabulary and the prototype chain", () => {
  it("shows a prototype-named status verbatim", () => {
    for (const status of [
      "constructor",
      "toString",
      "valueOf",
      "hasOwnProperty",
    ]) {
      const presentation = describeStatus(status)
      expect(presentation.label).toBe(status)
      expect(presentation.tone).toBe("neutral")
    }
  })
})

/*
  WS-34: one backend state has one presentation. Every state the tracker,
  the approvals screen, the activity feed and Home render goes through
  `describeStatus`, so the table has to be complete (a label, a tone, an
  icon and a plain-language explanation for every state) and unambiguous
  (no two states sharing a label). The run vocabulary that
  `components/observability/run-progress.tsx` owns is deliberately not
  here — see the RUN_STATUSES note in `lib/status.ts`.
*/
describe("the status table (WS-34)", () => {
  it("covers every application status and every human outcome", () => {
    const names = new Set<string>([
      ...APPLICATION_STATUS_NAMES,
      ...HUMAN_OUTCOME_STATUS_NAMES,
    ])
    for (const status of names) {
      expect(KNOWN_STATUS_NAMES, status).toContain(status)
    }
  })

  it("gives every known state a complete presentation", () => {
    for (const status of KNOWN_STATUS_NAMES) {
      const presentation = describeStatus(status)
      expect(presentation.label.trim().length, status).toBeGreaterThan(0)
      expect(presentation.tone, status).toBeTruthy()
      expect(presentation.icon.trim().length, status).toBeGreaterThan(0)
      expect(presentation.nextStep.trim().length, status).toBeGreaterThan(10)
    }
  })

  it("gives the application vocabulary distinct labels", () => {
    /*
      The workstream contract scopes distinctness to the application
      statuses plus the human outcomes — the vocabulary one screen
      renders together. (The approval namespace's `rejected` shares the
      word "Rejected" with the application status of the same name by
      design: the two lists never co-render, and the approvals screen
      pins that label.)
    */
    const names = new Set<string>([
      ...APPLICATION_STATUS_NAMES,
      ...HUMAN_OUTCOME_STATUS_NAMES,
    ])
    const labels = new Map<string, string>()
    for (const status of names) {
      const presentation = describeStatus(status)
      const owner = labels.get(presentation.label)
      expect(
        owner ?? null,
        `${presentation.label} is shared by ${owner} and ${status}`
      ).toBeNull()
      labels.set(presentation.label, status)
    }
  })

  it("uses an icon name the badge can actually render", () => {
    for (const status of KNOWN_STATUS_NAMES) {
      const { icon } = describeStatus(status)
      expect(Object.hasOwn(STATUS_ICONS, icon), `${status}: ${icon}`).toBe(true)
    }
    // The unknown fallback and the missing-status fallback present too.
    expect(Object.hasOwn(STATUS_ICONS, describeStatus(null).icon)).toBe(true)
    expect(
      Object.hasOwn(STATUS_ICONS, describeStatus("something_new").icon)
    ).toBe(true)
  })

  it("marks the human outcomes as human, not agent", () => {
    for (const status of HUMAN_OUTCOME_STATUS_NAMES) {
      // Lime (success/progress) is the agent's mark; a human-recorded
      // outcome must not wear it.
      expect(
        ["success", "progress"],
        `${status} must not be presented in the agent's lime`
      ).not.toContain(describeStatus(status).tone)
    }
    // The agent's own milestones keep it.
    expect(describeStatus("verified").tone).toBe("success")
    expect(describeStatus("submitted").tone).toBe("progress")
    expect(describeStatus("RUNNING").tone).toBe("progress")
  })
})
