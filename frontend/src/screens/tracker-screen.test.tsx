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

describe("the tracker list", () => {
  it("lists the tracked applications", async () => {
    renderScreen(<TrackerScreen />)

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
    renderScreen(<TrackerScreen />)

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
    renderScreen(<TrackerScreen />)

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
    renderScreen(<TrackerScreen />)

    expect(
      await screen.findByText("25 applications · showing 1–10")
    ).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "Next" })).toBeEnabled()
  })

  it("sends one status or none — never a filter the server ignores", async () => {
    // The backend answers a multi-status call with the *unfiltered* list
    // (tracking.py:220-221), so the chips are single-select by contract:
    // what the filter claims is what the server does.
    let seenStatus: string | null = null
    server.use(
      http.get(`${BASE}/api/applications`, ({ request }) => {
        seenStatus = new URL(request.url).searchParams.get("status")
        return HttpResponse.json({ items: [], total: 0, limit: 10, offset: 0 })
      })
    )
    const user = userEvent.setup()
    renderScreen(<TrackerScreen />)

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
    renderScreen(<TrackerScreen />)

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
    renderScreen(<TrackerScreen />)

    expect(await screen.findByText("Nothing tracked yet")).toBeInTheDocument()
  })

  it("keeps the column-dropping table below md", async () => {
    // The timestamps drop out of the table rather than the table scrolling
    // sideways — the pattern every future table follows. The detail screen
    // they link to shows the same timestamps in full.
    renderScreen(<TrackerScreen />)

    await screen.findByText("AI Engineer")
    for (const name of ["Created", "Submitted"]) {
      expect(screen.getByRole("columnheader", { name })).toHaveClass(
        "hidden",
        "md:table-cell"
      )
    }
  })
})

describe("the tracker board", () => {
  it("reads one status per column and carries the server's total", async () => {
    // The board is five single-status reads, made once on mount. Each
    // request carries exactly one `status` — the only filter the server
    // honours — and each column's count is that response's server `total`,
    // not the length of the page it loaded.
    const boardSeen: string[][] = []
    server.use(
      http.get(`${BASE}/api/applications`, ({ request }) => {
        const url = new URL(request.url)
        const statuses = url.searchParams.getAll("status")
        if (url.searchParams.get("limit") === "8") boardSeen.push(statuses)
        const status = statuses[0] ?? ""
        if (status === "shortlisted" || status === "submitted") {
          return boardPage([], 0)
        }
        if (status === "prepared") {
          return boardPage(
            [
              summary({
                id: "p-1",
                status: "prepared",
                job_title: "Prepared Job",
              }),
            ],
            1
          )
        }
        if (status === "awaiting_approval") {
          return boardPage(
            [1, 2, 3].map((index) =>
              summary({ id: `a-${index}`, status: "awaiting_approval" })
            ),
            5
          )
        }
        if (status === "verified") {
          return boardPage([summary({ id: "v-1", status: "verified" })], 12)
        }
        return boardPage([], 0)
      })
    )
    mockViewport(true)
    const user = userEvent.setup()
    renderScreen(<TrackerScreen />)

    await user.click(await screen.findByRole("tab", { name: "Board" }))

    // Five columns, named only from the real status vocabulary.
    await screen.findByRole("region", { name: "Shortlisted — 0 applications" })
    await screen.findByRole("region", { name: "Prepared — 1 application" })
    await screen.findByRole("region", {
      name: "Awaiting approval — 5 applications",
    })
    await screen.findByRole("region", {
      name: "Submitted, not yet verified — 0 applications",
    })
    const verified = await screen.findByRole("region", {
      name: "Verified — 12 applications",
    })

    expect(screen.queryByText("Saved")).not.toBeInTheDocument()
    expect(screen.queryByText("Preparing")).not.toBeInTheDocument()

    // Every request was a single-status request, and only real statuses went out.
    await waitFor(() => {
      expect(boardSeen).toHaveLength(5)
    })
    for (const statuses of boardSeen) {
      expect(statuses).toHaveLength(1)
      expect([
        "shortlisted",
        "prepared",
        "awaiting_approval",
        "submitted",
        "verified",
      ]).toContain(statuses[0] ?? "")
    }

    // The count is the server's total even though one card is on screen.
    expect(within(verified).getByText("12")).toBeInTheDocument()
    expect(
      within(verified).getByRole("button", { name: "Show all 12 in the list" })
    ).toBeInTheDocument()

    // The honesty note: what the columns are, and where the rest lives.
    expect(
      screen.getByText(/its own server query for exactly one status/)
    ).toBeInTheDocument()
  })

  it("keeps the card's job, company, status and next action", async () => {
    server.use(
      http.get(`${BASE}/api/applications`, ({ request }) => {
        const status = new URL(request.url).searchParams.get("status") ?? ""
        if (status === "prepared") {
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
    const user = userEvent.setup()
    renderScreen(<TrackerScreen />)

    await user.click(await screen.findByRole("tab", { name: "Board" }))

    const prepared = await screen.findByRole("region", {
      name: "Prepared — 1 application",
    })
    const card = within(prepared).getByRole("link", { name: /Prepared Job/ })
    expect(within(card).getByText("Acme")).toBeInTheDocument()
    expect(within(card).getByText("Prepared")).toBeInTheDocument()
    expect(
      within(card).getByText(/waiting for an approval decision/)
    ).toBeInTheDocument()
  })

  it("labels an empty stage with the server's own zero", async () => {
    server.use(http.get(`${BASE}/api/applications`, () => boardPage([], 0)))
    mockViewport(true)
    const user = userEvent.setup()
    renderScreen(<TrackerScreen />)

    await user.click(await screen.findByRole("tab", { name: "Board" }))

    const shortlisted = await screen.findByRole("region", {
      name: "Shortlisted — 0 applications",
    })
    expect(
      within(shortlisted).getByText("No applications with this status.")
    ).toBeInTheDocument()
  })

  it("hands a stage off to the list, filtered to that status", async () => {
    const listStatuses: (string | null)[] = []
    server.use(
      http.get(`${BASE}/api/applications`, ({ request }) => {
        const url = new URL(request.url)
        const status = url.searchParams.get("status")
        if (url.searchParams.get("limit") === "8") {
          if (status === "verified") {
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

    await user.click(await screen.findByRole("tab", { name: "Board" }))

    const verified = await screen.findByRole("region", {
      name: "Verified — 3 applications",
    })
    await user.click(
      within(verified).getByRole("button", { name: "Show all 3 in the list" })
    )

    // The list is showing again, and the server was asked for that one status.
    await waitFor(() => {
      expect(listStatuses[listStatuses.length - 1]).toBe("verified")
    })
    expect(await screen.findByText(/with the status/)).toBeInTheDocument()
    expect(screen.getByRole("tab", { name: "List" })).toHaveAttribute(
      "data-active"
    )
  })

  it("falls back to the list on a phone — no sideways columns", async () => {
    mockViewport(false)
    const user = userEvent.setup()
    renderScreen(<TrackerScreen />)

    await user.click(await screen.findByRole("tab", { name: "Board" }))

    expect(
      await screen.findByText(/The board needs more width than this screen has/)
    ).toBeInTheDocument()
    // The list is the fallback: a table, not stage columns.
    expect(screen.queryByRole("region")).not.toBeInTheDocument()
    expect(screen.getByRole("table")).toBeInTheDocument()
  })
})

describe("the tracker detail", () => {
  it("brings the rows in one after another", async () => {
    renderScreen(<TrackerScreen />)

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

    expect(await screen.findByText("Timeline (2)")).toBeInTheDocument()
    const timeline = within(
      screen.getByRole("list", { name: "Application timeline" })
    )
    const rows = timeline.getAllByRole("listitem")
    // The order is the server's append order, untouched by the console.
    expect(rows.map((row) => row.getAttribute("data-event-id"))).toEqual([
      "1",
      "2",
    ])

    // Lime is the agent's mark; terracotta is the human's.
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

  it("shows the history and the evidence", async () => {
    renderApp({ route: "/app/tracker/application-1" })

    expect(await screen.findByText("Timeline (2)")).toBeInTheDocument()
    expect(screen.getByText("application_created")).toBeInTheDocument()
    expect(screen.getByText("approval_granted")).toBeInTheDocument()
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
