import { screen, waitFor, within } from "@testing-library/react"
import { http, HttpResponse } from "msw"
import { describe, expect, it, vi } from "vitest"

import { OverviewScreen } from "@/screens/overview-screen"
import {
  applicationSummary,
  auditEvent,
  auditResponse,
  jobListing,
  matchesHistory,
} from "@/test/factories"
import { renderScreen } from "@/test/render"
import { server } from "@/test/server"
import { setCurrentProfileId } from "@/lib/profile"

import type { ApplicationList, AuditPage } from "@/lib/api/types"

// Production cadences compressed to milliseconds — see `test/polling-cadence.ts`.
vi.mock("@/lib/polling", async () => await import("@/test/polling-cadence"))

const BASE = "http://api.test"

const hold = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms))

/** A page shape exactly like `GET /api/applications` sends. */
function listPage(
  items: ApplicationList["items"],
  total: number,
  limit = 50
): ApplicationList {
  return { items, total, limit, offset: 0 }
}

/** One tracked application, shaped like the API sends, with overrides. */
function applicationWith(
  overrides: Partial<ApplicationList["items"][number]>
): ApplicationList["items"][number] {
  return { ...applicationSummary(), ...overrides }
}

/**
 * A tile of the stat strip, found by its label. The tile is a link once its
 * first read lands; before that it is a plain panel — both carry the
 * `data-stat-card` mark, so the helper finds either.
 */
function tileFor(label: string): HTMLElement {
  const tile = screen.getByText(label).closest("[data-stat-card]")
  if (!tile) throw new Error(`No stat tile found for "${label}"`)
  return tile as HTMLElement
}

/**
 * The applications list, answering each of the reads the screen polls: the
 * unfiltered totals read, the awaiting-approval page, the prepared page and
 * the submitted page — each with its own server `total`, deliberately
 * **larger than the page it returns**, so a screen that counted loaded rows
 * instead of the server's total fails here visibly. A resting `prepared`
 * application is a real backend state (the row is created PREPARED and only
 * then moved to AWAITING_APPROVAL), so it counts toward "need your
 * attention" exactly like an awaiting one.
 */
function useSplitApplicationTotals() {
  server.use(
    http.get(`${BASE}/api/applications`, ({ request }) => {
      const status = new URL(request.url).searchParams.get("status")
      if (status === "awaiting_approval") {
        return HttpResponse.json(
          listPage(
            [
              applicationWith({
                id: "application-a1",
                job_title: "Backend Engineer",
                company_name: "TechFlow",
                status: "awaiting_approval",
                verified_at: null,
                submitted_at: null,
              }),
            ],
            1,
            10
          )
        )
      }
      if (status === "prepared") {
        return HttpResponse.json(
          listPage(
            [
              applicationWith({
                id: "application-p1",
                job_title: "Platform Engineer",
                company_name: "Helios",
                status: "prepared",
                verified_at: null,
                submitted_at: null,
              }),
              applicationWith({
                id: "application-p2",
                job_title: "Data Engineer",
                company_name: "DataForge",
                status: "prepared",
                verified_at: null,
                submitted_at: null,
              }),
            ],
            2,
            10
          )
        )
      }
      if (status === "submitted") {
        return HttpResponse.json(listPage([applicationSummary()], 3, 1))
      }
      // The unfiltered totals read: a one-row page carrying the server's
      // total of seven.
      return HttpResponse.json(listPage([applicationSummary()], 7, 1))
    })
  )
}

describe("the Home dashboard", () => {
  it("counts from the server's totals, not from the loaded page", async () => {
    setCurrentProfileId("profile-1")
    useSplitApplicationTotals()
    renderScreen(<OverviewScreen />)

    // The screen names itself "Overview" (the tab-title contract every
    // console screen shares), and the greeting names the profile without an
    // emoji — the time of day is not pinned, because the test must pass at
    // any hour it runs.
    expect(
      await screen.findByRole("heading", { name: "Overview" })
    ).toBeInTheDocument()
    // The profile's name rides in with the profile read.
    await waitFor(() => {
      expect(
        screen.getByText(/Good (morning|afternoon|evening), Ada\./)
      ).toBeInTheDocument()
    })

    // The unfiltered read returns one row; the server says seven.
    await waitFor(() => {
      expect(
        within(tileFor("Tracked applications")).getByText("7")
      ).toBeInTheDocument()
    })
    // The awaiting page returns one row and the prepared page two; the
    // server says 1 + 2 = 3 applications await a decision — and the
    // attention tile aggregates those server totals with the trail's count.
    expect(
      within(tileFor("Need your attention")).getByText("4")
    ).toBeInTheDocument()
    expect(tileFor("Need your attention")).toHaveTextContent(
      "3 awaiting a decision"
    )
    // The attention summary row also speaks the server total, not the rows
    // that happen to be loaded.
    expect(
      await screen.findByText("3 applications awaiting your approval")
    ).toBeInTheDocument()
    // The submitted page returns one row; the server says three.
    expect(
      within(tileFor("Submitted, unverified")).getByText("3")
    ).toBeInTheDocument()
    // One ranked match in the mocked history.
    expect(within(tileFor("Top matches")).getByText("1")).toBeInTheDocument()
  })

  it("aggregates need-your-attention from real statuses and links each row to its resolver", async () => {
    setCurrentProfileId("profile-1")
    useSplitApplicationTotals()
    renderScreen(<OverviewScreen />)

    // The awaiting applications render as their own rows, through the one
    // status presentation — the badge shows `describeStatus`'s label, and
    // each row links to the application's tracker page. A resting
    // `prepared` application renders the same way, alongside them.
    const rowA1 = (await screen.findByText("Backend Engineer")).closest("a")
    expect(rowA1).toHaveAttribute("href", "/app/tracker/application-a1")
    const badge = within(rowA1 as HTMLElement).getByText("Awaiting approval")
    expect(
      (badge.closest("[data-status]") as HTMLElement).hasAttribute(
        "data-status"
      )
    ).toBe(true)
    expect(badge.closest("[data-status]")?.getAttribute("data-status")).toBe(
      "awaiting_approval"
    )
    const rowP2 = screen.getByText("Data Engineer").closest("a")
    expect(rowP2).toHaveAttribute("href", "/app/tracker/application-p2")
    const preparedBadge = within(rowP2 as HTMLElement).getByText("Prepared")
    expect(
      preparedBadge.closest("[data-status]")?.getAttribute("data-status")
    ).toBe("prepared")
    const rowP1 = screen.getByText("Platform Engineer").closest("a")
    expect(rowP1).toHaveAttribute("href", "/app/tracker/application-p1")

    // The summary rows lead to the screens that resolve them.
    const approvalsLink = screen.getByRole("link", {
      name: /Review approvals/,
    })
    expect(approvalsLink).toHaveAttribute("href", "/app/approvals")
    const activityLink = screen.getByRole("link", { name: /Open activity/ })
    expect(activityLink).toHaveAttribute("href", "/app/activity")
    // The mocked trail holds one blocked challenge; the row says so, scoped
    // to the window the audit endpoint actually returns.
    expect(
      screen.getByText("1 trail event needs attention")
    ).toBeInTheDocument()
    // And the measured question gaps the profile does not answer.
    expect(
      await screen.findByText(
        /3 employer questions the profile does not answer/
      )
    ).toBeInTheDocument()
    expect(screen.getByRole("link", { name: /Open Profile/ })).toHaveAttribute(
      "href",
      "/app/profile"
    )
  })

  it("never claims all-clear while an attention source is unreadable", async () => {
    // Every clean source answers zero; the measured question gaps fail.
    setCurrentProfileId("profile-1")
    server.use(
      http.get(`${BASE}/api/applications`, () =>
        HttpResponse.json(listPage([], 0))
      ),
      http.get(`${BASE}/api/audit`, () =>
        HttpResponse.json({ events: [], count: 0 })
      ),
      http.get(`${BASE}/api/profiles/:profileId/question-gaps`, () =>
        HttpResponse.json(
          { detail: "The server failed to handle the request." },
          { status: 500 }
        )
      ),
      http.get(`${BASE}/api/profiles/:profileId/matches`, () =>
        HttpResponse.json({ profile_id: "profile-1", matches: [] })
      )
    )
    renderScreen(<OverviewScreen />)

    // The failure is named, with the way back…
    expect(
      await screen.findByText("Employer questions couldn't be read")
    ).toBeInTheDocument()
    expect(
      screen.getByRole("button", { name: /Try again/ })
    ).toBeInTheDocument()
    // …and the empty state never claims a clean bill of health while a
    // source is unknown.
    expect(
      screen.queryByText("Nothing needs you right now")
    ).not.toBeInTheDocument()
  })

  it("renders every section honestly when the account is empty", async () => {
    // No profile chosen, no applications, no matches, no trail rows.
    server.use(
      http.get(`${BASE}/api/applications`, () =>
        HttpResponse.json(listPage([], 0))
      ),
      http.get(`${BASE}/api/audit`, () =>
        HttpResponse.json({ events: [], count: 0 })
      ),
      http.get(`${BASE}/api/profiles/:profileId/matches`, () =>
        HttpResponse.json({ profile_id: "profile-1", matches: [] })
      ),
      http.get(`${BASE}/api/profiles/:profileId/question-gaps`, () =>
        HttpResponse.json({
          profile_id: "profile-1",
          total_observed: 0,
          questions: [],
        })
      ),
      http.get(`${BASE}/api/documents`, () =>
        HttpResponse.json({ documents: [], count: 0 })
      )
    )
    renderScreen(<OverviewScreen />)

    // The attention section is the honest empty state, with the one real
    // ask (a résumé) as a row, because a profile is genuinely missing.
    expect(await screen.findByText("Upload a résumé")).toBeInTheDocument()
    expect(screen.getByRole("link", { name: /Go to Resume/ })).toHaveAttribute(
      "href",
      "/app/resume"
    )

    // Real server zeros on the strip — never a stand-in number.
    await waitFor(() => {
      expect(
        within(tileFor("Need your attention")).getByText("0")
      ).toBeInTheDocument()
    })
    expect(
      within(tileFor("Tracked applications")).getByText("0")
    ).toBeInTheDocument()

    // The featured slot and the feed are honest empties, not placeholder cards.
    expect(await screen.findByText("No matches yet")).toBeInTheDocument()
    expect(screen.getByText("No recorded activity yet")).toBeInTheDocument()

    // Nothing from the reference's illustrative set may appear.
    expect(screen.queryByText(/Live/)).not.toBeInTheDocument()
    expect(screen.queryByText(/\+2/)).not.toBeInTheDocument()
    expect(screen.queryByText(/Pro Plan/)).not.toBeInTheDocument()
    expect(screen.queryByText(/Company Fit/)).not.toBeInTheDocument()
    expect(screen.queryByText(/96%/)).not.toBeInTheDocument()
  })

  it("attributes the trail's actors and links the rows that have a real destination", async () => {
    setCurrentProfileId("profile-1")
    server.use(
      http.get(`${BASE}/api/audit`, () => {
        const page: AuditPage = {
          events: [
            // An action the console has no label for: shown verbatim, and
            // linked nowhere rather than to a guessed destination.
            auditEvent({
              id: 60,
              action: "something.unheard",
              actor: "agent",
              actor_kind: "agent",
              outcome: "success",
            }),
            ...auditResponse().events,
          ],
          count: 6,
        }
        return HttpResponse.json(page)
      })
    )
    renderScreen(<OverviewScreen />)

    // Attribution: the agent's steps and the person's are named. The row's
    // actor word and its action are separate text nodes, so both sides of
    // the pair are asserted: four agent rows, two person rows. (Each row's
    // link repeats the action for screen readers, so the action text can
    // appear more than once.)
    await waitFor(() => {
      expect(
        screen.getAllByText(/verified a submission/).length
      ).toBeGreaterThanOrEqual(1)
    })
    // Three agent rows (verify, submit, the unknown action), two person
    // rows (the approval, the upload), and the blocked challenge reads as
    // the system's call-out, not the agent's — a blocked step is a
    // platform stop, which is how the shared trail presents it too.
    expect(screen.getAllByText("The agent")).toHaveLength(3)
    expect(screen.getAllByText("A person")).toHaveLength(2)
    expect(
      screen.getAllByText(/stopped at a captcha or multi-factor prompt/i).length
    ).toBeGreaterThanOrEqual(1)
    expect(
      screen.getAllByText(/approved an application/).length
    ).toBeGreaterThanOrEqual(1)
    expect(
      screen.getAllByText(/uploaded and parsed a résumé/).length
    ).toBeGreaterThanOrEqual(1)
    // The unknown action is not hidden and not invented into a label, and
    // it carries no link at all.
    expect(screen.getByText(/something\.unheard/)).toBeInTheDocument()

    // Links: submission work leads to the Tracker, approval work to the
    // Review surface, the blocked challenge to the full trail, the upload
    // back to Resume.
    const trackLinks = screen.getAllByRole("link", { name: /Track/ })
    expect(trackLinks.length).toBeGreaterThanOrEqual(1)
    expect(trackLinks[0]).toHaveAttribute("href", "/app/tracker")
    const reviewLinks = screen.getAllByRole("link", { name: /Review/ })
    expect(reviewLinks[0]).toHaveAttribute("href", "/app/approvals")
    const trailLinks = screen.getAllByRole("link", { name: /Trail/ })
    expect(trailLinks[0]).toHaveAttribute("href", "/app/activity")
    const resumeLinks = screen.getAllByRole("link", { name: /Resume/ })
    expect(resumeLinks[0]).toHaveAttribute("href", "/app/resume")
    // The unknown action row carries no link at all.
    expect(
      screen
        .getAllByRole("link")
        .filter((link) => link.textContent?.includes("something.unheard"))
    ).toHaveLength(0)
  })

  it("renders unknown match components as unknown, never as their zero score", async () => {
    setCurrentProfileId("profile-1")
    server.use(
      http.get(`${BASE}/api/profiles/:profileId/matches`, () =>
        HttpResponse.json({
          profile_id: "profile-1",
          matches: [
            {
              profile_id: "profile-1",
              job_id: "greenhouse:1",
              scores: {
                overall_score: 82.5,
                semantic_score: 80,
                skill_score: 90,
                experience_score: 75,
                location_score: 0,
                evidence_coverage: 100,
                component_states: {
                  semantic: "MATCHED",
                  skill: "MATCHED",
                  experience: "MATCHED",
                  // The candidate never said where they want to work: the
                  // component rests on nothing, and must not read as a 0.
                  location: "CANDIDATE_DATA_MISSING",
                },
                matched_requirements: ["Python", "SQL"],
                missing_requirements: ["Kubernetes"],
              },
              explanation:
                "The profile states Python and SQL, which the listing asks for.",
              created_at: "2026-10-21T10:00:00Z",
            },
          ],
        })
      )
    )
    renderScreen(<OverviewScreen />)

    // The featured card renders with the real listing and the real score.
    expect(
      await screen.findByRole("heading", { name: "AI Engineer" })
    ).toBeInTheDocument()
    expect(screen.getByText(/82\.5/)).toBeInTheDocument()

    // The unknown component states its reason…
    expect(screen.getByText("unknown — you haven't said")).toBeInTheDocument()
    // …and the zero the raw score carries for it never renders as a value.
    expect(screen.queryByText("0.0")).not.toBeInTheDocument()
    // The measured components render their real numbers.
    expect(screen.getByText("90.0")).toBeInTheDocument()
    expect(screen.getByText("75.0")).toBeInTheDocument()

    // The reference card's actions, at their real destinations.
    expect(
      screen.getByRole("link", { name: /Tailor for this job/ })
    ).toHaveAttribute("href", "/app/tailor/greenhouse%3A1")
    expect(screen.getByRole("link", { name: /View details/ })).toHaveAttribute(
      "href",
      "/app/matches/greenhouse%3A1"
    )
  })

  it("polls only the applications and audit reads, on the shared interval, and pauses when hidden", async () => {
    const applicationPaths: string[] = []
    const auditPaths: string[] = []
    server.use(
      http.get(`${BASE}/api/applications`, ({ request }) => {
        applicationPaths.push(new URL(request.url).pathname)
        return HttpResponse.json(listPage([applicationSummary()], 1, 50))
      }),
      http.get(`${BASE}/api/audit`, ({ request }) => {
        auditPaths.push(new URL(request.url).pathname)
        return HttpResponse.json(auditResponse())
      })
    )
    renderScreen(<OverviewScreen />)

    // The mount reads fire, then the interval refetches only the same two
    // endpoints — the ranked matches, the listings, the profile and the
    // question gaps are per-mount reads, not part of any cycle.
    await waitFor(() => expect(auditPaths.length).toBeGreaterThanOrEqual(3), {
      timeout: 2_000,
    })
    expect(applicationPaths.length).toBeGreaterThanOrEqual(3)
    for (const path of applicationPaths) expect(path).toBe("/api/applications")
    for (const path of auditPaths) expect(path).toBe("/api/audit")
  })

  it("does not poll while the tab is hidden, and resumes when it returns", async () => {
    let hidden = true
    Object.defineProperty(document, "visibilityState", {
      configurable: true,
      get: () => (hidden ? "hidden" : "visible"),
    })
    let auditCalls = 0
    server.use(
      http.get(`${BASE}/api/audit`, () => {
        auditCalls += 1
        return HttpResponse.json(auditResponse())
      })
    )
    renderScreen(<OverviewScreen />)

    // The mount fetch happens; the interval behind it must not.
    await waitFor(() => expect(auditCalls).toBe(1))
    await hold(300)
    expect(auditCalls).toBe(1)

    hidden = false
    window.dispatchEvent(new Event("visibilitychange"))
    await waitFor(() => expect(auditCalls).toBeGreaterThanOrEqual(2), {
      timeout: 1_000,
    })
  })

  it("keeps the matched listing's honest fallback when the listing cannot be read", async () => {
    setCurrentProfileId("profile-1")
    server.use(
      http.get(`${BASE}/api/jobs/greenhouse%3A1`, () =>
        HttpResponse.json(
          { detail: "Job 'greenhouse:1' not found" },
          { status: 404 }
        )
      )
    )
    renderScreen(<OverviewScreen />)

    // The ranked match exists but its listing did not answer: the card says
    // so and points at the screen that re-runs the search — no fabricated
    // card, no broken frame.
    expect(
      await screen.findByText(/The top match's listing can't be shown/)
    ).toBeInTheDocument()
    expect(screen.getByRole("link", { name: /Open Matches/ })).toHaveAttribute(
      "href",
      "/app/matches"
    )
  })

  it("names the poll, not a stream: the feed says its window and interval", async () => {
    setCurrentProfileId("profile-1")
    renderScreen(<OverviewScreen />)

    // The feed's label states its interval and its window. (The interval's
    // number comes from `OVERVIEW_POLL_MS`, which this file compresses to
    // milliseconds — the real 30-second cadence is pinned in
    // `lib/polling.test.ts`.)
    expect(await screen.findByText(/updated every/i)).toBeInTheDocument()
    expect(screen.getByText(/newest 100 events/i)).toBeInTheDocument()
    // The strip's provenance line speaks the same way.
    expect(screen.getByText(/Reads every/)).toBeInTheDocument()
    await waitFor(() => {
      expect(
        within(tileFor("Need your attention")).getByText(/newest 100/)
      ).toBeInTheDocument()
    })
    // And no "Live" badge, anywhere.
    expect(screen.queryByText("Live")).not.toBeInTheDocument()
  })

  it("shows the profile's matches' honest shortlist only when more matches exist", async () => {
    setCurrentProfileId("profile-1")
    server.use(
      http.get(`${BASE}/api/profiles/:profileId/matches`, () => {
        const history = matchesHistory()
        return HttpResponse.json({
          profile_id: "profile-1",
          matches: [
            history.matches[0],
            {
              profile_id: "profile-1",
              job_id: "lever:2",
              scores: {
                overall_score: 74.5,
                semantic_score: 70,
                skill_score: 80,
                experience_score: 70,
                location_score: 100,
                evidence_coverage: 90,
                component_states: { semantic: "MATCHED", skill: "MATCHED" },
                matched_requirements: ["Python"],
              },
              explanation: "A reasonable second match.",
              created_at: "2026-10-21T09:00:00Z",
            },
          ],
        })
      }),
      // The listing read echoes the requested id, so each shortlist card's
      // link carries its own job's destination.
      http.get(`${BASE}/api/jobs/:jobId`, ({ params }) =>
        HttpResponse.json({ job: jobListing({ id: String(params.jobId) }) })
      )
    )
    renderScreen(<OverviewScreen />)

    // The shortlist row renders the additional real match…
    const section = await screen.findByText("Also strong")
    expect(section).toBeInTheDocument()
    expect(screen.getByText(/74\.5/)).toBeInTheDocument()
    // …linked to the job's own screen.
    const card = screen
      .getAllByRole("link", { name: /View details/ })
      .find((link) => link.getAttribute("href") === "/app/matches/lever%3A2")
    expect(card).toBeInTheDocument()
  })
})
