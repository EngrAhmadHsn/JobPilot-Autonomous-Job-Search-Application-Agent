import { screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { http, HttpResponse } from "msw"
import { afterEach, describe, expect, it, vi } from "vitest"

import { TrackerScreen } from "@/screens/tracker-screen"
import {
  applicationDetail,
  applicationList,
  applicationSummary,
} from "@/test/factories"
import { server } from "@/test/server"
import { renderApp, renderScreen } from "@/test/render"
import type { ApplicationList } from "@/lib/api/types"

const BASE = "http://api.test"

/**
 * One application summary, with overrides.
 *
 * The shared factory builds the backend's shape but takes no overrides, so
 * a test that needs a specific status or title spreads over it here —
 * keeping the base shape the generated contract defines.
 */
function summary(
  overrides: Partial<ApplicationList["items"][number]> = {}
): ApplicationList["items"][number] {
  return { ...applicationSummary(), ...overrides }
}

/*
  The board is desktop-first: below `md` it falls back to the list. jsdom's
  matchMedia stub (the test setup's) answers `false` for everything, so a
  board test has to pin the viewport explicitly, and every test restores the
  setup's stub afterwards.
*/
const SETUP_MATCH_MEDIA = window.matchMedia

function mockViewport(matches: boolean) {
  window.matchMedia = ((query: string) => ({
    matches,
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })) as unknown as typeof window.matchMedia
}

afterEach(() => {
  window.matchMedia = SETUP_MATCH_MEDIA
})

/** A board-column page: the column's own limit is 8, so the answer says 8. */
function boardPage(
  items: ReturnType<typeof applicationSummary>[],
  total: number
) {
  return HttpResponse.json({ items, total, limit: 8, offset: 0 })
}

/*
  The list is no longer the default view — the board is (the design's screen
  05 opens on it) — so every list test opens the screen with `?view=list`,
  the same linkable state a column's "Show all" hand-off produces.
*/
const LIST_ROUTE = "/?view=list"

describe("the tracker list", () => {
  it("lists the tracked applications", async () => {
    renderScreen(<TrackerScreen />, { route: LIST_ROUTE })

    expect(await screen.findByText("AI Engineer")).toBeInTheDocument()
    expect(screen.getByText(/1 application · showing 1–1/)).toBeInTheDocument()
    expect(screen.getAllByText("Verified").length).toBeGreaterThan(0)
  })

  it("filters by status through the server", async () => {
    let seenStatuses: string | null = null
    server.use(
      http.get(`${BASE}/api/applications`, ({ request }) => {
        seenStatuses = new URL(request.url).searchParams.get("status")
        return HttpResponse.json({ items: [], total: 0, limit: 20, offset: 0 })
      })
    )
    const user = userEvent.setup()
    renderScreen(<TrackerScreen />, { route: LIST_ROUTE })

    await user.click(
      await screen.findByRole("button", { name: "Awaiting approval" })
    )

    await waitFor(() => {
      expect(seenStatuses).toBe("awaiting_approval")
    })
  })

  it("asks the server for ten applications a page", async () => {
    // The list is the server's: the console must not ask for a page it then
    // has to trim, and ten keeps the page readable on a laptop.
    let seenLimit: string | null = null
    server.use(
      http.get(`${BASE}/api/applications`, ({ request }) => {
        seenLimit = new URL(request.url).searchParams.get("limit")
        return HttpResponse.json({ items: [], total: 0, limit: 10, offset: 0 })
      })
    )
    renderScreen(<TrackerScreen />, { route: LIST_ROUTE })

    await waitFor(() => {
      expect(seenLimit).toBe("10")
    })
  })

  it("states the server's total even when the page holds less", async () => {
    // WS-33's rule: the counter is the server's `total`, never the length
    // of the loaded page. Ten rows on the page, twenty-five on the server.
    server.use(
      http.get(`${BASE}/api/applications`, () =>
        HttpResponse.json({
          items: Array.from({ length: 10 }, (_, index) =>
            summary({
              id: `application-${index}`,
              job_title: `Job ${index}`,
            })
          ),
          total: 25,
          limit: 10,
          offset: 0,
        })
      )
    )
    renderScreen(<TrackerScreen />, { route: LIST_ROUTE })

    expect(
      await screen.findByText("25 applications · showing 1–10")
    ).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "Next" })).toBeEnabled()
  })

  it("sends one status or none — the chips stay single-select", async () => {
    // The board's columns send the grouped multi-status reads (the backend
    // applies every requested status since 2026-11-19), but the list's own
    // chips remain one status each — a chip is a single named state, and
    // selecting a second replaces the first instead of quietly widening
    // the filter. What the chip claims is what the server is asked.
    let seenStatus: string | null = null
    server.use(
      http.get(`${BASE}/api/applications`, ({ request }) => {
        seenStatus = new URL(request.url).searchParams.get("status")
        return HttpResponse.json({ items: [], total: 0, limit: 10, offset: 0 })
      })
    )
    const user = userEvent.setup()
    renderScreen(<TrackerScreen />, { route: LIST_ROUTE })

    await user.click(await screen.findByRole("button", { name: "Verified" }))
    await waitFor(() => {
      expect(seenStatus).toBe("verified")
    })

    // Selecting a second status replaces the first instead of sending both.
    await user.click(await screen.findByRole("button", { name: "Prepared" }))
    await waitFor(() => {
      expect(seenStatus).toBe("prepared")
    })
    const verifiedChip = screen.getByRole("button", { name: "Verified" })
    expect(verifiedChip).toHaveAttribute("aria-pressed", "false")
  })

  it("shows the server's refusal of an unknown status", async () => {
    server.use(
      http.get(`${BASE}/api/applications`, () =>
        HttpResponse.json(
          {
            detail:
              "Unknown status 'nope'. Known statuses: discovered, matched.",
          },
          { status: 400 }
        )
      )
    )
    renderScreen(<TrackerScreen />, { route: LIST_ROUTE })

    expect(
      await screen.findByText(
        "Unknown status 'nope'. Known statuses: discovered, matched."
      )
    ).toBeInTheDocument()
  })

  it("says when nothing is tracked yet", async () => {
    server.use(
      http.get(`${BASE}/api/applications`, () =>
        HttpResponse.json({ items: [], total: 0, limit: 10, offset: 0 })
      )
    )
    renderScreen(<TrackerScreen />, { route: LIST_ROUTE })

    expect(await screen.findByText("Nothing tracked yet")).toBeInTheDocument()
  })

  it("keeps the column-dropping table below md", async () => {
    // The timestamps drop out of the table rather than the table scrolling
    // sideways — the pattern every future table follows. The detail screen
    // they link to shows the same timestamps in full.
    renderScreen(<TrackerScreen />, { route: LIST_ROUTE })

    await screen.findByText("AI Engineer")
    for (const name of ["Created", "Submitted"]) {
      expect(screen.getByRole("columnheader", { name })).toHaveClass(
        "hidden",
        "md:table-cell"
      )
    }
  })

  it("always offers the way back to the board", async () => {
    // The Board/List pair is the screen's, not the board's: a List view
    // with no way back would be a dead end the design does not draw.
    renderScreen(<TrackerScreen />, { route: LIST_ROUTE })

    const tabs = await screen.findByRole("tablist", {
      name: "Applications view",
    })
    expect(within(tabs).getByRole("tab", { name: "List" })).toHaveAttribute(
      "data-active"
    )
    await screen.findByText("AI Engineer")
  })
})

describe("the tracker board", () => {
  it("reads one grouped filter per column and carries the server's total", async () => {
    /*
      WS-42: the board is now **four** columns over the design's stages, each
      one a *multi-status* request — Awaiting review is
      `awaiting_approval,prepared`, Outcome recorded is the four human
      outcomes. That is only correct because the API applies every requested
      status (before 2026-11-19 it silently dropped all but one and answered
      with the unfiltered list, which is why the old board had to use one
      status per column).

      The honesty assertions are unchanged and still the point of the test:
      every request names only **real** statuses, and every column's count is
      that response's server `total` — not the length of the page it loaded.
    */
    const boardSeen: string[][] = []
    server.use(
      http.get(`${BASE}/api/applications`, ({ request }) => {
        const url = new URL(request.url)
        const statuses = url.searchParams
          .getAll("status")
          .flatMap((value) => value.split(","))
          .filter(Boolean)
        if (url.searchParams.get("limit") === "8") boardSeen.push(statuses)
        const wants = (status: string) => statuses.includes(status)
        if (wants("awaiting_approval") || wants("prepared")) {
          return boardPage(
            [
              summary({
                id: "p-1",
                status: "prepared",
                job_title: "Prepared Job",
              }),
              ...[1, 2, 3].map((index) =>
                summary({ id: `a-${index}`, status: "awaiting_approval" })
              ),
            ],
            5
          )
        }
        if (wants("verified")) {
          return boardPage([summary({ id: "v-1", status: "verified" })], 12)
        }
        if (wants("submitted")) {
          return boardPage([summary({ id: "s-1", status: "submitted" })], 2)
        }
        return boardPage([], 0)
      })
    )
    mockViewport(true)
    renderScreen(<TrackerScreen />)

    // The board is the default view now, so no tab click is needed — but the
    // tab still names it, which is what makes the other view reachable.
    await screen.findByRole("tab", { name: "Board" })

    // Four columns, named in the design's own stage words.
    await screen.findByRole("region", {
      name: "Awaiting review — 5 applications",
    })
    await screen.findByRole("region", { name: "Needs you — 12 applications" })
    await screen.findByRole("region", { name: "In progress — 2 applications" })
    await screen.findByRole("region", {
      name: "Outcome recorded — 0 applications",
    })

    // No stage name the backend does not have.
    expect(screen.queryByText("Saved")).not.toBeInTheDocument()
    expect(screen.queryByText("Preparing")).not.toBeInTheDocument()

    // Four grouped reads, and every status named is a real one.
    const REAL_STATUSES = new Set([
      "discovered",
      "matched",
      "shortlisted",
      "prepared",
      "awaiting_approval",
      "submitted",
      "verified",
      "rejected",
      "interview",
      "offer",
      "withdrawn",
    ])
    await waitFor(() => {
      expect(boardSeen).toHaveLength(4)
    })
    for (const statuses of boardSeen) {
      expect(statuses.length).toBeGreaterThan(0)
      for (const status of statuses) {
        expect(REAL_STATUSES.has(status)).toBe(true)
      }
    }
    // The groups are exactly the declared ones, so a change to the mapping
    // has to be a deliberate change to this list too.
    const sorted = (group: string[]) => [...group].sort()
    expect(boardSeen.map(sorted)).toEqual(
      [
        ["awaiting_approval", "prepared"],
        ["verified"],
        ["submitted"],
        ["interview", "offer", "rejected", "withdrawn"],
      ].map(sorted)
    )

    // The count is the server's total even though one card is on screen.
    const needsYou = screen.getByRole("region", {
      name: "Needs you — 12 applications",
    })
    expect(within(needsYou).getByText("12")).toBeInTheDocument()
    expect(
      within(needsYou).getByRole("button", {
        name: "Show all 12 in the list →",
      })
    ).toBeInTheDocument()
  })

  it("keeps the card's job, company, stage words and next action", async () => {
    /*
      The design's card (49:1157–49:1182) is five parts: company, title,
      stage chip, helper, then a divider over a CTA pill and a timestamp.
      The chip's words are the design's where they are true of the backend —
      a `prepared` row really is a packet waiting for a decision — and the
      CTA names the action the detail screen actually offers. Every value
      derives from the server's row; the test pins that mapping.
    */
    server.use(
      http.get(`${BASE}/api/applications`, ({ request }) => {
        const statuses = new URL(request.url).searchParams
          .getAll("status")
          .flatMap((value) => value.split(","))
        if (statuses.includes("prepared")) {
          return boardPage(
            [
              summary({
                id: "p-1",
                status: "prepared",
                job_title: "Prepared Job",
                company_name: "Acme",
              }),
            ],
            1
          )
        }
        return boardPage([], 0)
      })
    )
    mockViewport(true)
    renderScreen(<TrackerScreen />)

    const review = await screen.findByRole("region", {
      name: "Awaiting review — 1 application",
    })
    const titleLink = within(review).getByRole("link", {
      name: /Prepared Job/,
    })
    const card = titleLink.closest("div") as HTMLElement
    expect(within(card).getByText("Acme")).toBeInTheDocument()
    // The design's chip word, true of this status.
    expect(within(card).getByText("Packet ready")).toBeInTheDocument()
    // The design's helper sentence (49:1165).
    expect(
      within(card).getByText(
        "Review the prepared packet before taking the next step."
      )
    ).toBeInTheDocument()
    // The CTA pill is its own explicit link to the same detail screen.
    const cta = within(card).getByRole("link", {
      name: "Review application →",
    })
    expect(cta).toHaveAttribute("href", "/app/tracker/p-1")
    // The timestamp is derived from a real field, never invented.
    expect(
      within(card).getByText(/^Prepared (on|today|yesterday)/)
    ).toBeInTheDocument()
  })

  it("labels an empty stage with the server's own zero", async () => {
    server.use(http.get(`${BASE}/api/applications`, () => boardPage([], 0)))
    mockViewport(true)
    renderScreen(<TrackerScreen />)

    const outcome = await screen.findByRole("region", {
      name: "Outcome recorded — 0 applications",
    })
    expect(
      within(outcome).getByText("Nothing in this stage.")
    ).toBeInTheDocument()
  })

  it("hands a stage off to the list, filtered to the whole group", async () => {
    /*
      The hand-off must ask for the **group**, not one status: clicking "Show
      all 3" beside a column that counted 3 has to show those 3. A
      single-status filter here would silently show a subset — the column
      would say 3, the list would show 1, and nothing would explain the gap.
    */
    const listStatuses: (string | null)[] = []
    server.use(
      http.get(`${BASE}/api/applications`, ({ request }) => {
        const url = new URL(request.url)
        const status = url.searchParams.get("status")
        const grouped = (status ?? "").split(",")
        if (url.searchParams.get("limit") === "8") {
          if (grouped.includes("verified")) {
            return boardPage([summary({ id: "v-1", status: "verified" })], 3)
          }
          return boardPage([], 0)
        }
        listStatuses.push(status)
        return HttpResponse.json(applicationList())
      })
    )
    mockViewport(true)
    const user = userEvent.setup()
    renderScreen(<TrackerScreen />)

    const needsYou = await screen.findByRole("region", {
      name: "Needs you — 3 applications",
    })
    await user.click(
      within(needsYou).getByRole("button", {
        name: "Show all 3 in the list →",
      })
    )

    // The list is showing again, and the server was asked for the group.
    await waitFor(() => {
      expect(listStatuses[listStatuses.length - 1]).toBe("verified")
    })
    expect(await screen.findByText(/with the status/)).toBeInTheDocument()
    expect(screen.getByRole("tab", { name: "List" })).toHaveAttribute(
      "data-active"
    )
  })

  it("keeps one board at every width — columns, never a different surface", async () => {
    /*
      The design draws the Kanban at 1440 *and* at 390 (16:162 and 49:10846):
      narrow widths swipe the same columns sideways under their sticky
      headers, they do not swap in a squeezed grid or the list. With no
      viewport mock (jsdom's matchMedia answers `false` for everything) the
      board still renders all four stage columns — there is no branch that
      turns it into another surface.
    */
    renderScreen(<TrackerScreen />)

    await screen.findByRole("region", { name: /Awaiting review/ })
    expect(
      screen.getByRole("region", { name: /Needs you/ })
    ).toBeInTheDocument()
    expect(
      screen.getByRole("region", { name: /In progress/ })
    ).toBeInTheDocument()
    expect(
      screen.getByRole("region", { name: /Outcome recorded/ })
    ).toBeInTheDocument()
    // No fallback surface: no table and no width apology on the board.
    expect(screen.queryByRole("table")).not.toBeInTheDocument()
    expect(
      screen.queryByText(/The board needs more width than this screen has/)
    ).not.toBeInTheDocument()
  })

  it("carries the design's toolbar and the board's integrity note", async () => {
    /*
      The toolbar is the design's row (49:1133–49:1143): Board/List pills,
      a Filters pill, the total count and "Find another role →". The count
      is the sum of the four columns' server totals — shown only when every
      column answered. The legend under the board is the design's own copy
      verbatim (49:1255) — it is also the honesty contract, so the test
      pins it word for word.
    */
    server.use(
      http.get(`${BASE}/api/applications`, ({ request }) => {
        const statuses = new URL(request.url).searchParams
          .getAll("status")
          .flatMap((value) => value.split(","))
        if (statuses.includes("awaiting_approval") || statuses.includes("prepared")) {
          return boardPage([summary({ id: "p-1", status: "prepared" })], 5)
        }
        if (statuses.includes("verified")) {
          return boardPage([summary({ id: "v-1", status: "verified" })], 12)
        }
        if (statuses.includes("submitted")) {
          return boardPage([summary({ id: "s-1", status: "submitted" })], 2)
        }
        return boardPage([], 0)
      })
    )
    const user = userEvent.setup()
    mockViewport(true)
    renderScreen(<TrackerScreen />)

    // The toolbar's pills and actions, in the design's words.
    expect(
      await screen.findByRole("tab", { name: "Board" })
    ).toBeInTheDocument()
    expect(screen.getByRole("tab", { name: "List" })).toBeInTheDocument()
    const filters = screen.getByRole("button", { name: /Filters/ })
    expect(filters).toHaveTextContent("F")
    // 5 + 12 + 2 + 0 — the server's totals, only when every column answered.
    expect(await screen.findByText("19 applications")).toBeInTheDocument()
    const findAnother = screen.getByRole("link", {
      name: "Find another role →",
    })
    expect(findAnother).toHaveAttribute("href", "/app/matches")

    // The legend (49:1255) — the design's copy, verbatim.
    const legend = screen.getByRole("note", { name: "What a stage means" })
    expect(
      within(legend).getByText("A stage is a fact, not a guess.")
    ).toBeInTheDocument()
    expect(
      within(legend).getByText(
        "Queued does not mean sent. Employer handoff does not mean submitted. Each column scrolls independently; its header stays in place."
      )
    ).toBeInTheDocument()

    // The Filters pill is a hand-off to the list's real filter, not a fake
    // panel: clicking it opens the List view.
    await user.click(filters)
    expect(
      await screen.findByRole("group", { name: "Filter by status" })
    ).toBeInTheDocument()
  })
})

describe("the tracker detail", () => {
  it("brings the rows in one after another", async () => {
    renderScreen(<TrackerScreen />, { route: LIST_ROUTE })

    const rows = await screen.findAllByRole("row")
    // The rows carry the entrance class, and each one carries its own
    // index so the delay grows down the list.
    const withEntrance = rows.filter((row) =>
      row.className.includes("enter-up")
    )
    expect(withEntrance.length).toBeGreaterThan(0)
    expect(withEntrance[0]?.style.getPropertyValue("--i")).toBe("0")
  })

  it("renders the timeline in the server's order with each actor's colour", async () => {
    renderApp({ route: "/app/tracker/application-1" })

    // The design's card title (49:2152): "Ordered history".
    expect(await screen.findByText("Ordered history")).toBeInTheDocument()
    const timeline = within(
      screen.getByRole("list", { name: "Application timeline" })
    )
    const rows = timeline.getAllByRole("listitem")
    // The order is the server's append order, untouched by the console.
    expect(rows.map((row) => row.getAttribute("data-event-id"))).toEqual([
      "1",
      "2",
    ])

    // Lime is the agent's mark; terracotta is the human's — the two-colour
    // attribution law survives the restyle (the design draws one sage tint
    // for both chips; flattening Agent and You would hide exactly the
    // attribution this trail exists to prove).
    const [firstRow, secondRow] = rows
    expect(firstRow).toBeDefined()
    expect(secondRow).toBeDefined()
    const agentChip = within(firstRow as HTMLElement).getByText("Agent")
    expect(agentChip).toHaveAttribute("data-actor-kind", "agent")
    expect(agentChip).toHaveClass("bg-lime-soft")
    const humanChip = within(secondRow as HTMLElement).getByText("Human · ada")
    expect(humanChip).toHaveAttribute("data-actor-kind", "human")
    expect(humanChip).toHaveClass("bg-terracotta-soft")
  })

  it("tells the history in the trail's human voice, not the server's enum", async () => {
    /*
      The design's rows (49:2152–49:2177) are a 14/600 title over a 12/400
      explanation — "Approval recorded / Identity and decision saved." —
      never the raw `event_type`. A known event type is phrased as what the
      backend records it as meaning; the server's own metadata stays below
      the two lines, because run ids are provenance.
    */
    renderApp({ route: "/app/tracker/application-1" })

    expect(await screen.findByText("Ordered history")).toBeInTheDocument()
    expect(screen.getByText("Application created")).toBeInTheDocument()
    expect(screen.getByText("Approval recorded")).toBeInTheDocument()
    expect(screen.getByText("Identity and decision saved.")).toBeInTheDocument()
    // The raw enum never renders for a type the console knows.
    expect(screen.queryByText("application_created")).not.toBeInTheDocument()
    expect(screen.queryByText("approval_granted")).not.toBeInTheDocument()
    // The evidence's own confirmation text, from the record.
    expect(await screen.findByText("Application submitted")).toBeInTheDocument()
  })

  it("renders evidence through the safe endpoint, never a server path", async () => {
    renderApp({ route: "/app/tracker/application-1" })

    const image = await screen.findByRole("img", {
      name: "The screenshot captured as evidence of the submission",
    })
    // The image comes from the authorized evidence route, not from the
    // filesystem path the record carries.
    expect(image).toHaveAttribute(
      "src",
      "http://api.test/api/applications/application-1/evidence/workflow-1.png"
    )

    // No browser-facing element points at a server-side path.
    const unsafe = Array.from(
      document.querySelectorAll("a[href], img[src]")
    ).filter((element) => {
      const target =
        element.getAttribute("href") ?? element.getAttribute("src") ?? ""
      return target.includes("/data/")
    })
    expect(unsafe).toEqual([])
  })

  it("records a human outcome with a human actor", async () => {
    let sentBody: unknown = null
    server.use(
      http.patch(
        `${BASE}/api/applications/:applicationId/status`,
        async ({ request }) => {
          sentBody = await request.json()
          return HttpResponse.json({
            ...(await import("@/test/factories")).applicationDetail(),
            status: "interview",
          })
        }
      )
    )
    const user = userEvent.setup()
    renderApp({ route: "/app/tracker/application-1" })

    await user.selectOptions(
      await screen.findByLabelText("Outcome"),
      "interview"
    )
    await user.click(
      await screen.findByRole("button", { name: "Record the outcome" })
    )

    // WS-14: the actor is the authenticated principal, so the console
    // does not collect one and does not send one.
    await waitFor(() => {
      expect(sentBody).toEqual({ status: "interview" })
    })
  })

  it("offers no outcome editor on a closed application", async () => {
    // `rejected` and `withdrawn` have no outgoing transitions in the
    // backend's matrix — a form here could only collect a 409.
    server.use(
      http.get(`${BASE}/api/applications/:applicationId`, () =>
        HttpResponse.json({ ...applicationDetail(), status: "rejected" })
      )
    )
    renderApp({ route: "/app/tracker/application-1" })

    expect(await screen.findByText("The outcome is final")).toBeInTheDocument()
    expect(
      screen.queryByRole("button", { name: "Record the outcome" })
    ).not.toBeInTheDocument()
  })

  it("states the application as the design's five fact rows", async () => {
    /*
      The execution card (49:2120–49:2143) is the design's five state facts —
      Approval, Execution, Form interaction, Submission, Evidence — each
      derived from a field or event the server sent, never from the status's
      name alone. This record is a verified application with a recorded
      approval, so the rows say what that history says: decided by a person,
      executed, filled, submitted, one artifact. The raw ids the audit trail
      and the uncertain-outcome path refer to stay on the page too, in the
      quieter "Record" card — provenance is not decoration, but it is also
      not the headline.
    */
    renderApp({ route: "/app/tracker/application-1" })

    expect(
      await screen.findByText("Every step, with evidence.")
    ).toBeInTheDocument()
    // The card's heading is the application itself (the design's
    // "Orbit · Backend Developer" slot).
    expect(screen.getByText("Acme · AI Engineer")).toBeInTheDocument()
    const executionCard = screen
      .getByText("Acme · AI Engineer")
      .closest('[data-slot="card"]') as HTMLElement
    const facts = [
      ["Approval", /^Recorded by you /],
      ["Execution", "Executed"],
      ["Form interaction", "Form filled"],
      ["Submission", /^Submitted /],
      ["Evidence", "1 artifact captured"],
    ] as const
    for (const [label, value] of facts) {
      expect(within(executionCard).getByText(label)).toBeInTheDocument()
      expect(within(executionCard).getByText(value)).toBeInTheDocument()
    }
    // A pending queue row would never read "Executed" — the value follows
    // the record, not the column it sits in.
    expect(
      screen.queryByText("Queued · waiting for a worker")
    ).not.toBeInTheDocument()
    // The audit ids stay on the page, in the Record card.
    expect(screen.getByText("Job URL")).toBeInTheDocument()
    expect(screen.getByText("Workflow id")).toBeInTheDocument()
  })

  it("shows the conflict when the move is not legal", async () => {
    server.use(
      http.patch(`${BASE}/api/applications/:applicationId/status`, () =>
        HttpResponse.json(
          {
            detail: "Illegal transition: verified -> interview is not allowed",
          },
          { status: 409 }
        )
      )
    )
    const user = userEvent.setup()
    renderApp({ route: "/app/tracker/application-1" })

    await user.click(
      await screen.findByRole("button", { name: "Record the outcome" })
    )

    expect(
      await screen.findByText(
        "Illegal transition: verified -> interview is not allowed"
      )
    ).toBeInTheDocument()
  })

  it("says that the actor may not set the status", async () => {
    server.use(
      http.patch(`${BASE}/api/applications/:applicationId/status`, () =>
        HttpResponse.json(
          { detail: "A human outcome must be recorded by a human actor" },
          { status: 403 }
        )
      )
    )
    const user = userEvent.setup()
    renderApp({ route: "/app/tracker/application-1" })

    await user.click(
      await screen.findByRole("button", { name: "Record the outcome" })
    )

    expect(
      await screen.findByText(
        "A human outcome must be recorded by a human actor"
      )
    ).toBeInTheDocument()
  })
})
