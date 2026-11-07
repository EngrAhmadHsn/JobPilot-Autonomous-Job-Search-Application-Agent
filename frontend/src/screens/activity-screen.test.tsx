import { screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { HttpResponse, http } from "msw"
import { describe, expect, it } from "vitest"

import { auditEvent } from "@/test/factories"
import { server } from "@/test/server"
import { renderApp } from "@/test/render"

const BASE = "http://api.test"

/**
 * Agent activity.
 *
 * The screen's honesty is the thing under test: it shows the trail the
 * server wrote, and it refuses to call polling "real-time".
 */
describe("the agent activity screen", () => {
  it("shows the trail in the server's own vocabulary, translated", async () => {
    renderApp({ route: "/app/activity" })

    expect(
      await screen.findByRole("heading", { name: "Agent activity" })
    ).toBeInTheDocument()
    expect(await screen.findByText(/uploaded and parsed a résumé/i)).toBeInTheDocument()
  })

  it("says plainly that it is not a live stream", async () => {
    renderApp({ route: "/app/activity" })

    expect(
      await screen.findByText(/this is not a live stream/i)
    ).toBeInTheDocument()
  })

  it("groups the trail into executions by workflow", async () => {
    renderApp({ route: "/app/activity" })

    expect(
      (await screen.findAllByText(/workflow-1/i)).length
    ).toBeGreaterThan(0)
  })

  it("can filter down to what needs attention", async () => {
    renderApp({ route: "/app/activity" })

    const toggle = await screen.findByRole("button", { name: /needs attention/i })
    expect(toggle).toBeInTheDocument()
  })

  it("pages the trail ten at a time", async () => {
    const events = Array.from({ length: 12 }, (_, index) =>
      auditEvent({
        id: 100 - index,
        action: "job.search",
        actor: "agent",
        actor_kind: "agent",
        outcome: "success",
        resource: `search-${index + 1}`,
        recorded_at: `2026-11-0${(index % 5) + 3}T09:${String(index).padStart(2, "0")}:00Z`,
      })
    )
    server.use(
      http.get(`${BASE}/api/audit`, () =>
        HttpResponse.json({ events, count: events.length })
      )
    )

    const user = userEvent.setup()
    renderApp({ route: "/app/activity" })

    // Ten rows on the first page, two on the second.
    expect(
      await screen.findByText("1–10 of 12 recorded actions")
    ).toBeInTheDocument()
    await user.click(screen.getByRole("button", { name: "Next" }))
    expect(
      await screen.findByText("11–12 of 12 recorded actions")
    ).toBeInTheDocument()
  })

  it("opens each execution closed", async () => {
    renderApp({ route: "/app/activity" })

    // The steps are behind a disclosure: several executions on one page is a
    // long list, so the screen opens with the summaries.
    expect((await screen.findAllByText("The steps")).length).toBeGreaterThan(0)
    // Every one of them starts closed.
    const disclosures = Array.from(document.querySelectorAll("details"))
    expect(disclosures.length).toBeGreaterThan(0)
    expect(disclosures.every((element) => !element.hasAttribute("open"))).toBe(true)
  })
})
