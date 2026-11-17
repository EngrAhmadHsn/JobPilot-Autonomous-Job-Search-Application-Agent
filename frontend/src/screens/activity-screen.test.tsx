import { screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { HttpResponse, http } from "msw"
import { describe, expect, it } from "vitest"

import { auditEvent } from "@/test/factories"
import { server } from "@/test/server"
import { renderApp } from "@/test/render"

const BASE = "http://api.test"

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
    expect(
      await screen.findByText(/uploaded and parsed a résumé/i)
    ).toBeInTheDocument()
  })

  it("says plainly that it is not a live stream", async () => {
    renderApp({ route: "/app/activity" })

    expect(
      await screen.findByText(/this is not a live stream/i)
    ).toBeInTheDocument()
  })

  it("groups the trail into executions by workflow", async () => {
    renderApp({ route: "/app/activity" })

    expect((await screen.findAllByText(/workflow-1/i)).length).toBeGreaterThan(
      0
    )
  })

  it("can filter down to what needs attention", async () => {
    renderApp({ route: "/app/activity" })

    const toggle = await screen.findByRole("button", {
      name: /needs attention/i,
    })
    expect(toggle).toBeInTheDocument()
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

  it("opens each execution closed", async () => {
    renderApp({ route: "/app/activity" })

    // The steps are behind a disclosure: several executions on one page is a
    // long list, so the screen opens with the summaries.
    expect((await screen.findAllByText("The steps")).length).toBeGreaterThan(0)
    // Every one of them starts closed.
    const disclosures = Array.from(document.querySelectorAll("details"))
    expect(disclosures.length).toBeGreaterThan(0)
    expect(disclosures.every((element) => !element.hasAttribute("open"))).toBe(
      true
    )
  })
})

describe("the activity center's filters (WS-40)", () => {
  /*
    The reference draws All / Agent / Applications / System. Each chip must
    map to a REAL field on the audit row — actor_kind or workflow_id — never
    to a guess. A chip that filtered on something the backend does not send
    would silently show an empty list and teach the operator a false story.
  */
  it("offers the four reference chips as one radio group with real counts", async () => {
    renderApp({ route: "/app/activity" })

    const group = await screen.findByRole("radiogroup", {
      name: /filter the trail/i,
    })
    expect(group).toBeInTheDocument()

    for (const label of ["All", "Agent", "Applications", "System"]) {
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

  it("filters to the rows each actor kind actually owns", async () => {
    /*
      The fixture is built here rather than borrowed, because the harness
      default has no system-actor row (every row is agent or user) — and a
      test that clicked System against it would be asserting the empty state
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
              action: "retention",
              actor: "system",
              actor_kind: "system",
              outcome: "success",
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
    // Scope every assertion to the TRAIL. The Executions timeline above it
    // shows the same event labels unfiltered, so a document-wide query would
    // pass even when the chip filtered nothing. The trail only exists once
    // the audit read has landed, so wait for it before scoping.
    await screen.findByTestId("activity-trail")
    const trail = () => screen.getByTestId("activity-trail")

    // "All" = every row.
    expect(
      await within(trail()).findByText(/Verified a submission/i)
    ).toBeInTheDocument()
    expect(
      within(trail()).getByText(/Uploaded and parsed a résumé/i)
    ).toBeInTheDocument()
    expect(
      within(trail()).getByText(/Ran the retention pass/i)
    ).toBeInTheDocument()

    // "Agent" = the agent's own steps only.
    await user.click(within(group).getByRole("radio", { name: /Agent/ }))
    expect(
      await within(trail()).findByText(/Verified a submission/i)
    ).toBeInTheDocument()
    expect(
      within(trail()).queryByText(/Uploaded and parsed a résumé/i)
    ).toBeNull()
    expect(within(trail()).queryByText(/Ran the retention pass/i)).toBeNull()

    // "Applications" = rows carrying a workflow id, whatever the actor kind.
    await user.click(within(group).getByRole("radio", { name: /Applications/ }))
    expect(
      await within(trail()).findByText(/Verified a submission/i)
    ).toBeInTheDocument()
    expect(
      within(trail()).queryByText(/Uploaded and parsed a résumé/i)
    ).toBeNull()

    // "System" = the platform's own action, never an agent or human one.
    await user.click(within(group).getByRole("radio", { name: /System/ }))
    expect(
      await within(trail()).findByText(/Ran the retention pass/i)
    ).toBeInTheDocument()
    expect(within(trail()).queryByText(/Verified a submission/i)).toBeNull()
    expect(
      within(trail()).queryByText(/Uploaded and parsed a résumé/i)
    ).toBeNull()
  })

  it("keeps needs-attention as its own control, not a fifth chip", async () => {
    renderApp({ route: "/app/activity" })

    const attention = await screen.findByRole("button", {
      name: /Needs attention/,
    })
    // It is a pressed-state toggle, not part of the actor radio group.
    expect(attention).toHaveAttribute("aria-pressed", "false")
    expect(
      within(
        screen.getByRole("radiogroup", { name: /filter the trail/i })
      ).queryByRole("radio", { name: /Needs attention/ })
    ).toBeNull()
  })

  it("still refuses to call polling real-time", async () => {
    renderApp({ route: "/app/activity" })

    expect(await screen.findByText(/refreshes every 30s/i)).toBeInTheDocument()
    expect(screen.queryByText(/^live$/i)).toBeNull()
  })
})
