import { screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it } from "vitest"

import { NavDrawer } from "@/components/layout/nav-drawer"
import { renderScreen } from "@/test/render"

/**
 * The navigation drawer.
 *
 * The drawer is the narrow screen's navigation, so it has to hold every
 * destination the horizontal bar holds — including the maintenance cluster,
 * which is easy to forget when the bar is the only place it appears.
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
      "Resume",
      "Matches",
      "Tailor",
      "Approvals",
      "Tracker",
      "Operations",
    ]) {
      expect(drawer.queryByRole("link", { name: label })).not.toBeNull()
    }
  })

  it("marks the current page", async () => {
    const user = userEvent.setup()
    renderScreen(<NavDrawer />, { route: "/matches" })

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
})
