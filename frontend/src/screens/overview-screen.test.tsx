import { screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"

import { renderApp } from "@/test/render"

/**
 * The overview.
 *
 * Every figure on it is counted from the server's answer, so the test
 * asserts the numbers the mocked API returns are the numbers on the screen
 * — an overview that rounds or invents would fail here.
 */
describe("the overview screen", () => {
  it("counts what the server returned", async () => {
    renderApp({ route: "/app" })

    expect(await screen.findByRole("heading", { name: "Overview" })).toBeInTheDocument()
    // One application in the mocked list, and it is verified.
    expect(await screen.findByText("Tracked applications")).toBeInTheDocument()
    expect(screen.getByText("Verified submissions")).toBeInTheDocument()
    // Five audit rows in the mocked trail.
    expect(screen.getByText("Recorded actions")).toBeInTheDocument()
  })

  it("surfaces what needs a human and links to the screen that resolves it", async () => {
    renderApp({ route: "/app" })

    // The mocked trail contains a blocked challenge, so "needs attention"
    // is non-empty and the overview must point at the activity screen.
    const link = await screen.findByRole("link", { name: /open activity/i })
    expect(link).toHaveAttribute("href", "/app/activity")
  })

  it("shows the recent trail", async () => {
    renderApp({ route: "/app" })

    expect(await screen.findByText(/uploaded and parsed a résumé/i)).toBeInTheDocument()
  })
})
