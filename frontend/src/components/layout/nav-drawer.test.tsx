import { screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it } from "vitest"

import { NavDrawer } from "@/components/layout/nav-drawer"
import { renderScreen } from "@/test/render"

/**
 * The navigation drawer.
 *
 * The drawer is the phone's "more" surface, so it has to hold every
 * destination the sidebar holds — including the System group, which is
 * easy to forget when the sidebar is the only place it appears.
 *
 * WS-34: the destination covering `/app/resume` is now labelled
 * "Documents" (the document library under "Profile & Documents") per the
 * approved information architecture; the pinned list below was updated
 * deliberately for that rename, not silently.
 */
describe("the navigation drawer", () => {
  it("opens and lists every destination", async () => {
    const user = userEvent.setup()
    renderScreen(<NavDrawer />)

    await user.click(
      screen.getByRole("button", { name: "Open the navigation menu" })
    )

    const drawer = within(await screen.findByRole("dialog"))
    for (const label of [
      "Matches",
      "Tracker",
      "Approvals",
      "Tailor",
      "Documents",
      "Activity",
      "Operations",
    ]) {
      expect(drawer.queryByRole("link", { name: label })).not.toBeNull()
    }
  })

  it("marks the current page", async () => {
    const user = userEvent.setup()
    renderScreen(<NavDrawer />, { route: "/app/matches" })

    await user.click(
      screen.getByRole("button", { name: "Open the navigation menu" })
    )

    const drawer = within(await screen.findByRole("dialog"))
    expect(
      drawer
        .queryByRole("link", { name: "Matches" })
        ?.getAttribute("aria-current")
    ).toBe("page")
  })

  it("holds the phone's diagnostics in its footer", async () => {
    const user = userEvent.setup()
    renderScreen(<NavDrawer />)

    await user.click(
      screen.getByRole("button", { name: "Open the navigation menu" })
    )

    const drawer = within(await screen.findByRole("dialog"))
    // The API pulse and the profile handle move out of the compact top
    // bar and live at the foot of the drawer.
    expect(drawer.getByText(/API online/i)).toBeInTheDocument()
    expect(drawer.getByText(/no profile/i)).toBeInTheDocument()
  })
})
