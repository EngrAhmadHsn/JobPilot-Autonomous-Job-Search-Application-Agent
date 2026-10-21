import { screen, waitFor } from "@testing-library/react"
import { describe, expect, it } from "vitest"

import { setCurrentProfileId } from "@/lib/profile"
import { renderApp } from "@/test/render"

describe("the application shell", () => {
  it("offers the six screens", async () => {
    renderApp()

    for (const label of [
      "Resume",
      "Matches",
      "Tailor",
      "Approvals",
      "Tracker",
      "Operations",
    ]) {
      expect(
        await screen.findByRole("link", { name: label })
      ).toBeInTheDocument()
    }
  })

  it("says when no profile is selected", async () => {
    renderApp()

    expect(await screen.findByText(/no profile/i)).toBeInTheDocument()
  })

  it("shows the profile the console is working with", async () => {
    setCurrentProfileId("profile-42")

    renderApp()

    expect((await screen.findAllByText("profile-42")).length).toBeGreaterThan(0)
  })

  it("reports that the API is reachable", async () => {
    renderApp()

    await waitFor(() => {
      expect(screen.getByText(/API online/i)).toBeInTheDocument()
    })
  })
})
