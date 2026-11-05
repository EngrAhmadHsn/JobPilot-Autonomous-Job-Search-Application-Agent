import { screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"

import { renderApp } from "@/test/render"

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
})
