import { screen, waitFor } from "@testing-library/react"
import { describe, expect, it } from "vitest"

import { setCurrentProfileId } from "@/lib/profile"
import { renderApp } from "@/test/render"

describe("the application shell", () => {
  it("offers the console screens", async () => {
    renderApp({ route: "/app/resume" })

    for (const label of [
      "Overview",
      "Resume",
      "Matches",
      "Tailor",
      "Approvals",
      "Tracker",
      "Activity",
      "Operations",
    ]) {
      expect(
        await screen.findByRole("link", { name: label })
      ).toBeInTheDocument()
    }
  })

  it("shows each destination exactly once", async () => {
    renderApp({ route: "/app/resume" })

    await screen.findByRole("link", { name: "Overview" })
    // The Overview group has no heading, precisely so "Overview" is not
    // rendered twice (once as a group label, once as the link).
    expect(screen.getAllByRole("link", { name: "Overview" })).toHaveLength(1)
  })

  it("hides Administration from an ordinary account", async () => {
    renderApp({ route: "/app/resume" })

    await screen.findByRole("link", { name: "Operations" })
    expect(screen.queryByRole("link", { name: "Administration" })).toBeNull()
  })

  it("says when no profile is selected", async () => {
    renderApp({ route: "/app/resume" })

    expect(await screen.findByText(/no profile/i)).toBeInTheDocument()
  })

  it("shows the profile the console is working with", async () => {
    setCurrentProfileId("profile-42")

    renderApp({ route: "/app/resume" })

    expect((await screen.findAllByText("profile-42")).length).toBeGreaterThan(0)
  })

  it("reports that the API is reachable", async () => {
    renderApp({ route: "/app/resume" })

    await waitFor(() => {
      expect(screen.getByText(/API online/i)).toBeInTheDocument()
    })
  })
})
