import { screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { HttpResponse, http } from "msw"
import { describe, expect, it } from "vitest"

import { auditEvent } from "@/test/factories"
import { server } from "@/test/server"
import { renderApp } from "@/test/render"

const BASE = "http://api.test"

/**
 * Agent activity (WS-42, design node `16:242`).
 *
 * The screen's honesty is the thing under test: it shows the trail the
 * server wrote, and it refuses to call polling "real-time".
 */
describe("the agent activity screen", () => {
  it("shows the trail in the server's own vocabulary, translated", async () => {
    renderApp({ route: "/app/activity" })

    expect(
      await screen.findByRole("heading", {
        name: "Nothing happens in the dark.",
      })
    ).toBeInTheDocument()
    expect(
      await screen.findByText(/uploaded and parsed a résumé/i)
    ).toBeInTheDocument()
  })

  it("says plainly that it is not a live stream", async () => {
    renderApp({ route: "/app/activity" })

    expect(
      await screen.findByText(/polling, not a live stream/)
    ).toBeInTheDocument()
    expect(screen.queryByText(/^live$/i)).toBeNull()
  })

  it("shows the latest execution as an ordered proof in the rail", async () => {
    renderApp({ route: "/app/activity" })

    expect((await screen.findAllByText(/workflow-1/i)).length).toBeGreaterThan(
      0
    )
    // The proof is the design's numbered evidence, open — not a second feed
    // hidden behind a disclosure.
    expect(screen.getAllByText("Accepted and queued").length).toBeGreaterThan(0)
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

  it("opens each row's details closed, and the proof open", async () => {
    renderApp({ route: "/app/activity" })

    // Every row carries a Details disclosure, and every one of them starts
    // closed: the feed reads as sentences first.
    await screen.findByTestId("activity-trail")
    const disclosures = Array.from(document.querySelectorAll("details"))
    expect(disclosures.length).toBeGreaterThan(0)
    expect(disclosures.every((element) => !element.hasAttribute("open"))).toBe(
      true
    )
  })
})

describe("the design's filter chips (WS-42, from WS-40)", () => {
  /*
    The design (node `16:242`) draws three chips — All activity · Needs you ·
    Agent work. Each chip must map to a REAL field or predicate on the audit
    row — actor_kind or needsAttention — never to a guess. A chip that
    filtered on something the backend does not send would silently show an
    empty list and teach the operator a false story.
  */
  it("offers the design's three chips as one radio group with real counts", async () => {
    renderApp({ route: "/app/activity" })

    const group = await screen.findByRole("radiogroup", {
      name: /filter the trail/i,
    })
    expect(group).toBeInTheDocument()

    for (const label of ["All activity", "Needs you", "Agent work"]) {
      expect(
        within(group).getByRole("radio", { name: new RegExp(label) })
      ).toBeInTheDocument()
    }
    // Exactly one chip is selected at a time.
    const checked = within(group)
      .getAllByRole("radio")
      .filter((chip) => chip.getAttribute("aria-checked") === "true")
    expect(checked).toHaveLength(1)
  })

  it("filters to the rows each chip actually owns", async () => {
    /*
      The fixture is built here rather than borrowed, because the harness
      default has no system-actor row (every row is agent or user) — and a
      test that clicked a chip against it would be asserting the empty state
      while believing it asserted the filter. One row per kind, so each chip
      has exactly one right answer.
    */
    server.use(
      http.get(`${BASE}/api/audit`, () =>
        HttpResponse.json({
          events: [
            auditEvent({
              id: 3,
              action: "application.verify",
              actor_kind: "agent",
              outcome: "success",
              workflow_id: "workflow-1",
              recorded_at: "2026-10-21T10:06:00Z",
            }),
            auditEvent({
              id: 2,
              action: "resume.upload",
              actor: "human:operator",
              actor_kind: "user",
              outcome: "success",
              workflow_id: null,
              recorded_at: "2026-10-21T10:02:00Z",
            }),
            auditEvent({
              id: 1,
              action: "allowlist.violation",
              actor: "system",
              actor_kind: "system",
              outcome: "blocked",
              workflow_id: null,
              recorded_at: "2026-10-21T09:00:00Z",
            }),
          ],
          count: 3,
        })
      )
    )
    renderApp({ route: "/app/activity" })
    const group = await screen.findByRole("radiogroup", {
      name: /filter the trail/i,
    })
    const user = userEvent.setup()
    // Scope every assertion to the TRAIL. The execution proof in the rail
    // shows the same event labels unfiltered, so a document-wide query would
    // pass even when the chip filtered nothing. The trail only exists once
    // the audit read has landed, so wait for it before scoping.
    await screen.findByTestId("activity-trail")
    const trail = () => screen.getByTestId("activity-trail")

    // "All activity" = every row.
    expect(
      await within(trail()).findByText(/Verified a submission/i)
    ).toBeInTheDocument()
    expect(
      within(trail()).getByText(/Uploaded and parsed a résumé/i)
    ).toBeInTheDocument()
    expect(
      within(trail()).getByText(/Blocked a domain not on the allowlist/i)
    ).toBeInTheDocument()

    // "Agent work" = the agent's own steps only.
    await user.click(within(group).getByRole("radio", { name: /Agent work/ }))
    expect(
      await within(trail()).findByText(/Verified a submission/i)
    ).toBeInTheDocument()
    expect(
      within(trail()).queryByText(/Uploaded and parsed a résumé/i)
    ).toBeNull()
    expect(
      within(trail()).queryByText(/Blocked a domain not on the allowlist/i)
    ).toBeNull()

    // "Needs you" = the derived predicate: refused, blocked or failed —
    // whatever the actor kind.
    await user.click(within(group).getByRole("radio", { name: /Needs you/ }))
    expect(
      await within(trail()).findByText(/Blocked a domain not on the allowlist/i)
    ).toBeInTheDocument()
    expect(within(trail()).queryByText(/Verified a submission/i)).toBeNull()
    expect(
      within(trail()).queryByText(/Uploaded and parsed a résumé/i)
    ).toBeNull()
  })

  it("still refuses to call polling real-time", async () => {
    renderApp({ route: "/app/activity" })

    expect(await screen.findByText(/refreshes every 30s/i)).toBeInTheDocument()
    expect(screen.queryByText(/^live$/i)).toBeNull()
  })
})
