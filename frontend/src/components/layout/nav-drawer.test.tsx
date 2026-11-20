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

  it("carries the account block in its footer, as the design draws it", async () => {
    const user = userEvent.setup()
    renderScreen(<NavDrawer />)

    await user.click(
      screen.getByRole("button", { name: "Open the navigation menu" })
    )

    const drawer = within(await screen.findByRole("dialog"))
    // The design's drawer footer (node 49:11961) is the account block —
    // avatar, name, preferences — the same account control the chrome
    // carries elsewhere. The environment marker lives in the top bar, so
    // it does not appear here.
    expect(
      drawer.getByRole("button", { name: "Account and display settings" })
    ).toBeInTheDocument()
    expect(drawer.queryByText(/API online/i)).not.toBeInTheDocument()
  })

  it("takes the WS-43 geometry: wide panel, rail-aligned rows and footer", async () => {
    const user = userEvent.setup()
    renderScreen(<NavDrawer />, { route: "/app/matches" })

    await user.click(
      screen.getByRole("button", { name: "Open the navigation menu" })
    )

    const panel = await screen.findByRole("dialog")
    const drawer = within(panel)
    // The panel is wide — min(26rem, 88vw) is roughly half the frame at
    // ≥768 and near-full on a phone — not the old fixed 290 px.
    expect(panel).toHaveClass("w-[min(26rem,88vw)]")

    // The current page takes the design's lime pill at the radius scale's
    // `rounded-2xl` — the same pill the rail's current row carries; the
    // destination above it brightens on the hover ground at the rail's
    // row height.
    const matches = drawer.getByRole("link", { name: "Matches" })
    expect(matches).toHaveClass(
      "rounded-2xl",
      "bg-sidebar-primary",
      "text-sidebar-primary-foreground"
    )
    const discover = drawer.getByRole("link", { name: "Discover" })
    expect(discover).toHaveClass("h-11", "rounded-2xl", "bg-sidebar-hover")

    // The footer sits on the rail footer's structure (`px-3.5` container,
    // `px-3` row), so the avatar lines up under the rows' icon column.
    expect(
      drawer.getByRole("button", { name: "Account and display settings" })
    ).toHaveClass("px-3", "gap-3")
  })
})
