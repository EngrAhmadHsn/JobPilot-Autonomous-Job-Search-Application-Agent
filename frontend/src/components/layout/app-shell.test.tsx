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

    expect(await screen.findByText(/No profile selected/i)).toBeInTheDocument()
  })

  it("shows the profile the console is working with", async () => {
    setCurrentProfileId("profile-42")

    renderApp()

    expect(await screen.findByText("profile-42")).toBeInTheDocument()
  })

  it("reports that the API is reachable", async () => {
    renderApp()

    await waitFor(() => {
      expect(screen.getByText(/API ok/i)).toBeInTheDocument()
    })
  })
})
