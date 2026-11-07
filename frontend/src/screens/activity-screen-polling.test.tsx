import { screen, waitFor } from "@testing-library/react"
import { http, HttpResponse } from "msw"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { ActivityScreen } from "@/screens/activity-screen"
import { auditEvent, auditResponse } from "@/test/factories"
import { server } from "@/test/server"
import { renderScreen } from "@/test/render"

// Production cadences compressed to milliseconds — see `test/polling-cadence.ts`.
vi.mock("@/lib/polling", async () => await import("@/test/polling-cadence"))

const BASE = "http://api.test"

const hold = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms))

describe("the activity screen's polling", () => {
  let visibilityDescriptor: PropertyDescriptor | undefined

  beforeEach(() => {
    visibilityDescriptor = Object.getOwnPropertyDescriptor(
      document,
      "visibilityState"
    )
  })

  afterEach(() => {
    if (visibilityDescriptor) {
      Object.defineProperty(document, "visibilityState", visibilityDescriptor)
    }
  })

  it("reads the trail and nothing else on each cycle", async () => {
    const paths: string[] = []
    server.use(
      http.get(`${BASE}/api/audit`, ({ request }) => {
        paths.push(new URL(request.url).pathname)
        return HttpResponse.json(auditResponse())
      })
    )
    renderScreen(<ActivityScreen />)

    await waitFor(() => expect(paths.length).toBeGreaterThanOrEqual(3), {
      timeout: 2_000,
    })
    // Every fetched URL is the trail's own; a poll never touches anything else.
    expect(new Set(paths)).toEqual(new Set(["/api/audit"]))
  })

  it("appends new events without dropping or duplicating the existing ones", async () => {
    let polls = 0
    server.use(
      http.get(`${BASE}/api/audit`, () => {
        polls += 1
        const events = auditResponse().events
        if (polls === 1) {
          return HttpResponse.json({ events, count: events.length })
        }
        const fresh = auditEvent({
          id: 99,
          action: "job.search",
          actor: "agent",
          actor_kind: "agent",
          recorded_at: new Date().toISOString(),
        })
        return HttpResponse.json({
          events: [fresh, ...events],
          count: events.length + 1,
        })
      })
    )
    renderScreen(<ActivityScreen />)

    expect(
      await screen.findByText(/uploaded and parsed a résumé/i)
    ).toBeInTheDocument()
    expect(
      await screen.findByText(/searched the job corpus/i)
    ).toBeInTheDocument()

    expect(screen.getAllByText(/searched the job corpus/i)).toHaveLength(1)
    expect(screen.getAllByText(/uploaded and parsed a résumé/i)).toHaveLength(1)
  })

  it("does not fetch while the tab is hidden, and resumes when it returns", async () => {
    let calls = 0
    let hidden = true
    Object.defineProperty(document, "visibilityState", {
      configurable: true,
      get: () => (hidden ? "hidden" : "visible"),
    })
    server.use(
      http.get(`${BASE}/api/audit`, () => {
        calls += 1
        return HttpResponse.json(auditResponse())
      })
    )
    renderScreen(<ActivityScreen />)

    // The mount fetch happens; the interval behind it must not.
    await waitFor(() => expect(calls).toBe(1))
    await hold(300)
    expect(calls).toBe(1)

    hidden = false
    window.dispatchEvent(new Event("visibilitychange"))
    await waitFor(() => expect(calls).toBeGreaterThanOrEqual(2), {
      timeout: 1_000,
    })
  })
})
