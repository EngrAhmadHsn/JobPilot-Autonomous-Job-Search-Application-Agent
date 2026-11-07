import { describe, expect, it } from "vitest"

import {
  ACTIVITY_POLL_MS,
  ADMIN_RUNS_ACTIVE_POLL_MS,
  ADMIN_RUNS_IDLE_POLL_MS,
  OVERVIEW_POLL_MS,
  RUN_ACTIVE_POLL_MS,
  RUN_ACTIVE_WITH_CHILD_POLL_MS,
  RUNS_LIST_ACTIVE_POLL_MS,
  RUNS_LIST_IDLE_POLL_MS,
  WORKER_HEALTH_POLL_MS,
  adminRunsPollInterval,
  runPollInterval,
  runsListPollInterval,
} from "@/lib/polling"

describe("the polling budget", () => {
  it("stops polling a terminal run", () => {
    for (const status of ["COMPLETED", "PARTIAL", "FAILED", "CANCELLED"]) {
      expect(runPollInterval({ status })).toBe(false)
    }
  })

  it("polls an active run, and an unknown one, at the budgeted cadence", () => {
    expect(runPollInterval({ status: "RUNNING" })).toBe(RUN_ACTIVE_POLL_MS)
    expect(runPollInterval({ status: "QUEUED" })).toBe(RUN_ACTIVE_POLL_MS)
    expect(runPollInterval(undefined)).toBe(RUN_ACTIVE_POLL_MS)
  })

  it("slows a parent while its embedding child is the thing moving", () => {
    expect(
      runPollInterval({
        status: "RUNNING",
        metadata: { refresh: { embedding_run_id: "run-embed-1" } },
      })
    ).toBe(RUN_ACTIVE_WITH_CHILD_POLL_MS)
  })

  it("keeps the runs list prompt while something runs, quiet when settled", () => {
    expect(runsListPollInterval(undefined)).toBe(RUNS_LIST_ACTIVE_POLL_MS)
    expect(runsListPollInterval([{ status: "RUNNING" }])).toBe(
      RUNS_LIST_ACTIVE_POLL_MS
    )
    expect(
      runsListPollInterval([{ status: "COMPLETED" }, { status: "QUEUED" }])
    ).toBe(RUNS_LIST_ACTIVE_POLL_MS)
    expect(
      runsListPollInterval([{ status: "COMPLETED" }, { status: "FAILED" }])
    ).toBe(RUNS_LIST_IDLE_POLL_MS)
  })

  it("gives the admin table the same active/idle split", () => {
    expect(adminRunsPollInterval(undefined)).toBe(ADMIN_RUNS_ACTIVE_POLL_MS)
    expect(adminRunsPollInterval([{ status: "RECOVERABLE" }])).toBe(
      ADMIN_RUNS_ACTIVE_POLL_MS
    )
    expect(adminRunsPollInterval([{ status: "CANCELLED" }])).toBe(
      ADMIN_RUNS_IDLE_POLL_MS
    )
  })

  it("holds every cadence at or below ten requests a minute", () => {
    const cadences = {
      ACTIVITY_POLL_MS,
      OVERVIEW_POLL_MS,
      RUN_ACTIVE_POLL_MS,
      RUN_ACTIVE_WITH_CHILD_POLL_MS,
      RUNS_LIST_ACTIVE_POLL_MS,
      ADMIN_RUNS_ACTIVE_POLL_MS,
      WORKER_HEALTH_POLL_MS,
    }
    for (const [name, ms] of Object.entries(cadences)) {
      expect(
        60_000 / ms,
        `${name} exceeds 10 requests/minute`
      ).toBeLessThanOrEqual(10)
    }
    // The idle heartbeats are cheaper still.
    expect(60_000 / RUNS_LIST_IDLE_POLL_MS).toBeLessThanOrEqual(1)
    expect(60_000 / ADMIN_RUNS_IDLE_POLL_MS).toBeLessThanOrEqual(1)
  })
})
