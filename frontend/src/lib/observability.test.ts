import { describe, expect, it } from "vitest"

import { auditEvent } from "@/test/factories"

import {
  describeAction,
  describeOutcome,
  eventTone,
  formatRelativeTime,
  groupRuns,
  needsAttention,
  summarizeEvents,
} from "./observability"

/**
 * The observability vocabulary.
 *
 * Two properties are load-bearing: a known action is translated, and an
 * **unknown** one is shown verbatim rather than dropped or guessed at. A
 * trail that hides what it does not understand is a trail that lies.
 */
describe("the observability vocabulary", () => {
  it("translates a known action", () => {
    expect(describeAction("job.search").label).toBe("Searched the job corpus")
  })

  it("shows an unknown action verbatim", () => {
    expect(describeAction("some.future.action").label).toBe("some.future.action")
  })

  it("does not fall for a prototype key", () => {
    // A server-supplied action of "constructor" must not resolve to a
    // function off Object.prototype.
    expect(describeAction("constructor").label).toBe("constructor")
  })

  it("labels an outcome", () => {
    expect(describeOutcome("blocked")).toBe("was blocked")
    expect(describeOutcome("weird")).toBe("weird")
  })

  it("calls out a blocked or failed event", () => {
    expect(needsAttention(auditEvent({ outcome: "blocked" }))).toBe(true)
    expect(needsAttention(auditEvent({ outcome: "error" }))).toBe(true)
    expect(needsAttention(auditEvent({ outcome: "success" }))).toBe(false)
    // A guard action is attention even when its outcome is "success".
    expect(
      needsAttention(auditEvent({ action: "allowlist.violation", outcome: "success" }))
    ).toBe(true)
  })

  it("tones by actor, and by outcome first", () => {
    expect(eventTone(auditEvent({ actor_kind: "agent" }))).toBe("agent")
    expect(eventTone(auditEvent({ actor_kind: "user" }))).toBe("human")
    expect(eventTone(auditEvent({ actor_kind: "system" }))).toBe("system")
    expect(eventTone(auditEvent({ outcome: "error" }))).toBe("failure")
  })

  it("summarises the feed", () => {
    const events = [
      auditEvent({ actor_kind: "agent", outcome: "success" }),
      auditEvent({ actor_kind: "user", outcome: "success" }),
      auditEvent({ actor_kind: "agent", outcome: "blocked" }),
    ]
    expect(summarizeEvents(events)).toEqual({
      total: 3,
      agent: 2,
      human: 1,
      attention: 1,
    })
  })
})

describe("grouping executions", () => {
  it("groups by workflow and reads oldest-first", () => {
    const events = [
      auditEvent({ id: 3, workflow_id: "wf-1", action: "application.verify" }),
      auditEvent({ id: 2, workflow_id: "wf-1", action: "application.submit" }),
      auditEvent({ id: 1, workflow_id: null, action: "resume.upload" }),
    ]
    const runs = groupRuns(events)
    expect(runs).toHaveLength(1)
    expect(runs[0]?.workflowId).toBe("wf-1")
    expect(runs[0]?.events.map((event) => event.id)).toEqual([2, 3])
  })

  it("marks a run that hit a failure", () => {
    const runs = groupRuns([
      auditEvent({ id: 2, workflow_id: "wf-2", outcome: "blocked" }),
      auditEvent({ id: 1, workflow_id: "wf-2", outcome: "success" }),
    ])
    expect(runs[0]?.hasFailure).toBe(true)
  })
})

describe("relative time", () => {
  it("says 'just now' for the present", () => {
    expect(formatRelativeTime(new Date().toISOString())).toBe("just now")
  })

  it("is honest about a missing timestamp", () => {
    expect(formatRelativeTime(null)).toBe("—")
  })
})
