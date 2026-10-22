import { describe, expect, it } from "vitest"

import { describeStatus, isHumanOutcomeStatus } from "@/lib/status"

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
