import { screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { HttpResponse, http } from "msw"
import { describe, expect, it } from "vitest"

import { setCurrentProfileId } from "@/lib/profile"
import { server } from "@/test/server"
import { renderApp } from "@/test/render"

const BASE = "http://api.test"

/*
  The application shell (WS-34).

  The shell's navigation moved from a horizontal header into the deep
  forest sidebar of the approved reference (and, below `lg`, into a top
  bar + bottom bar + drawer). What the tests still hold it to: every
  destination reachable, one selected destination at a time, the account
  menu opening, and — above all — the identity gate, which must keep the
  console chrome invisible to a caller with no session.
*/
describe("the application shell", () => {
  it("offers the console screens", async () => {
    renderApp({ route: "/app/resume" })

    /*
      WS-34 renamed and regrouped the destinations per the approved
      information architecture: the journey group (Home, Discover,
      Applications, Resume Studio, Profile & Documents, Activity) with
      its indented pages, and the System group beneath it. The drawer is
      closed, so the sidebar's nav is the only "Screens" navigation in
      the tree.
    */
    const nav = await screen.findByRole("navigation", { name: "Screens" })
    const sidebar = within(nav)
    for (const label of [
      "Home",
      "Discover",
      "Matches",
      "Applications",
      "Tracker",
      "Approvals",
      "Resume Studio",
      "Tailor",
      "Profile & Documents",
      "Profile",
      "Documents",
      "Activity",
    ]) {
      expect(sidebar.getByRole("link", { name: label })).toBeInTheDocument()
    }

    // Operations and Administration are their own labelled System group.
    const system = await screen.findByRole("navigation", { name: "System" })
    expect(
      within(system).getByRole("link", { name: "Operations" })
    ).toBeInTheDocument()
  })

  it("shows each destination exactly once", async () => {
    renderApp({ route: "/app/resume" })

    /*
      The old test pinned "Overview" appearing once — the group label
      must not repeat the item beneath it. WS-34 renamed the destination
      "Home", and the phone chrome (the bottom bar) renders its own
      subset of the same destinations at other widths, so uniqueness is
      asserted inside the sidebar's own navigations, where it belongs.
    */
    const nav = await screen.findByRole("navigation", { name: "Screens" })
    const sidebar = within(nav)
    await sidebar.findByRole("link", { name: "Home" })
    for (const label of [
      "Home",
      "Discover",
      "Matches",
      "Applications",
      "Tracker",
      "Approvals",
      "Resume Studio",
      "Tailor",
      "Profile & Documents",
      "Profile",
      "Documents",
      "Activity",
    ]) {
      expect(sidebar.getAllByRole("link", { name: label })).toHaveLength(1)
    }

    const system = await screen.findByRole("navigation", { name: "System" })
    expect(
      within(system).getAllByRole("link", { name: "Operations" })
    ).toHaveLength(1)
  })

  it("marks exactly one destination as the current page", async () => {
    renderApp({ route: "/app/tracker" })

    const nav = await screen.findByRole("navigation", { name: "Screens" })
    const sidebar = within(nav)

    // The page in view is the Tracker page of the Applications
    // destination: the child carries aria-current, the parent brightens
    // without claiming the page.
    expect(sidebar.getByRole("link", { name: "Tracker" })).toHaveAttribute(
      "aria-current",
      "page"
    )
    const applications = sidebar.getByRole("link", { name: "Applications" })
    expect(applications).toHaveAttribute("data-active")
    expect(applications).not.toHaveAttribute("aria-current")
  })

  it("marks a detail route as its destination", async () => {
    renderApp({ route: "/app/matches/job-1" })

    const nav = await screen.findByRole("navigation", { name: "Screens" })
    // The job detail route has no child of its own; Discover, which
    // covers both matches routes, is the current destination.
    expect(within(nav).getByRole("link", { name: "Discover" })).toHaveAttribute(
      "aria-current",
      "page"
    )
  })

  it("marks a tracker detail route as its destination", async () => {
    renderApp({ route: "/app/tracker/app-1" })

    const nav = await screen.findByRole("navigation", { name: "Screens" })
    // The application detail route has no child of its own; Applications,
    // which covers the tracker's index and detail routes, is the current
    // destination — and still the only one claiming the page.
    expect(
      within(nav).getByRole("link", { name: "Applications" })
    ).toHaveAttribute("aria-current", "page")
    expect(
      within(nav)
        .getAllByRole("link")
        .filter((link) => link.getAttribute("aria-current") === "page")
    ).toHaveLength(1)
  })

  it("marks a tailor detail route as its destination", async () => {
    renderApp({ route: "/app/tailor/job-1" })

    const nav = await screen.findByRole("navigation", { name: "Screens" })
    // The same rule as the tracker's detail route: Resume Studio covers
    // both tailor routes, so the destination — not any child — is current.
    expect(
      within(nav).getByRole("link", { name: "Resume Studio" })
    ).toHaveAttribute("aria-current", "page")
    expect(
      within(nav)
        .getAllByRole("link")
        .filter((link) => link.getAttribute("aria-current") === "page")
    ).toHaveLength(1)
  })

  it("hides Administration from an ordinary account", async () => {
    renderApp({ route: "/app/resume" })

    const system = await screen.findByRole("navigation", { name: "System" })
    await within(system).findByRole("link", { name: "Operations" })
    expect(
      within(system).queryByRole("link", { name: "Administration" })
    ).toBeNull()
  })

  it("opens the account menu from the shell", async () => {
    const user = userEvent.setup()
    renderApp({ route: "/app/resume" })

    // Both account triggers (sidebar footer and phone top bar) are in
    // the DOM at this viewport in jsdom; either opens the same menu.
    const trigger = screen
      .getAllByRole("button", {
        name: "Account and display settings",
      })
      .at(0)
    expect(trigger).toBeDefined()
    await user.click(trigger!)

    expect(await screen.findByText("Operator console")).toBeInTheDocument()
    expect(screen.getByText("Sign out")).toBeInTheDocument()
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
      // The marker renders once per chrome — the phone bar and the desktop
      // bar each carry it, and CSS shows exactly one at any real width
      // (jsdom computes neither) — so the assertion is on existence.
      expect(screen.getAllByText(/API online/i).length).toBeGreaterThanOrEqual(
        1
      )
    })
  })

  it("hides the console chrome from an unauthenticated caller", async () => {
    // WS-14: every protected route refuses a caller with no session, so
    // the shell asks the server who it is. With no identity, the shell
    // renders the sign-in screen and none of the console chrome — the
    // restyle must not have moved the gate.
    server.use(
      http.get(`${BASE}/api/auth/me`, () =>
        HttpResponse.json({ detail: "Unauthorized" }, { status: 401 })
      )
    )
    renderApp({ route: "/app/resume" })

    // The sign-in surface, in the design's own voice (WS-42, node 47:602) —
    // the fail-closed gate's shape is what this pins, not the string.
    expect(
      await screen.findByRole("heading", { name: "Welcome back." })
    ).toBeInTheDocument()
    expect(screen.queryByRole("navigation", { name: "Screens" })).toBeNull()
    expect(screen.queryByRole("navigation", { name: "Primary" })).toBeNull()
    expect(screen.queryByRole("complementary")).toBeNull()
  })

  it("does not read a failed identity request as a sign-out", async () => {
    /*
      WS-41. Only a refusal (401/403) means "you are signed out". A 429 from
      the per-identity request budget, a 500, or a dropped connection is the
      console failing to ask the question — and rendering the sign-in form
      for those told a signed-in operator their session was over and invited
      them to retype a password that was never the problem. The live sweep hit
      this for real: a rate-limited screen photographed as a sign-in page.

      The gate stays fail-closed — no console chrome until the server
      confirms the identity. What changes is the sentence and the recovery.
    */
    server.use(
      http.get(`${BASE}/api/auth/me`, () =>
        HttpResponse.json(
          { detail: "Too many requests" },
          { status: 429, headers: { "Retry-After": "30" } }
        )
      )
    )
    renderApp({ route: "/app/resume" })

    expect(
      await screen.findByText(/your session has not ended/i)
    ).toBeInTheDocument()
    // A transient failure must NOT show the sign-in form.
    expect(screen.queryByRole("heading", { name: "Welcome back." })).toBeNull()
    expect(screen.queryByLabelText("Password")).toBeNull()
    // Still fail-closed: the console chrome stays hidden.
    expect(screen.queryByRole("navigation", { name: "Screens" })).toBeNull()
    expect(screen.queryByRole("complementary")).toBeNull()
  })
})
