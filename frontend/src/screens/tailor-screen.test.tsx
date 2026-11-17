import { screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { http, HttpResponse } from "msw"
import { describe, expect, it } from "vitest"

import { candidateProfile, jobListing, tailorResponse } from "@/test/factories"
import { setCurrentProfileId } from "@/lib/profile"
import { server } from "@/test/server"
import { renderApp } from "@/test/render"

const BASE = "http://api.test"
const ROUTE = `/app/tailor/${encodeURIComponent("greenhouse:1")}`

describe("the tailor index", () => {
  it("has a heading even when there is no profile to tailor", async () => {
    renderApp({ route: "/app/tailor" })

    // A screen that shows only an empty state, with no heading, reads as a
    // broken screen. The heading says what the screen is for; the empty
    // state says what to do next.
    expect(
      await screen.findByRole("heading", {
        name: /Tailor the résumé for a job/i,
        level: 1,
      })
    ).toBeInTheDocument()
    expect(
      screen.getByText("Tailoring needs a résumé first")
    ).toBeInTheDocument()
  })

  it("lists one row per job, best match first (WS-21)", async () => {
    setCurrentProfileId("profile-1")
    let requested = ""
    server.use(
      http.get(`${BASE}/api/profiles/:profileId/matches`, ({ request }) => {
        requested = new URL(request.url).search
        return HttpResponse.json({
          profile_id: "profile-1",
          matches: [
            {
              profile_id: "profile-1",
              job_id: "job-b",
              scores: { overall_score: 91 },
              explanation: "",
              created_at: "2026-11-08T12:00:00Z",
            },
            {
              profile_id: "profile-1",
              job_id: "job-d",
              scores: { overall_score: 84 },
              explanation: "",
              created_at: "2026-11-08T11:00:00Z",
            },
            {
              profile_id: "profile-1",
              job_id: "job-c",
              scores: { overall_score: 72 },
              explanation: "",
              created_at: "2026-11-08T10:00:00Z",
            },
            {
              profile_id: "profile-1",
              job_id: "job-a",
              scores: { overall_score: 45 },
              explanation: "",
              created_at: "2026-11-08T09:00:00Z",
            },
          ],
        })
      }),
      http.get(`${BASE}/api/jobs/:jobId`, ({ params }) =>
        HttpResponse.json({
          job: jobListing({
            id: String(params.jobId),
            title: `Role ${String(params.jobId)}`,
          }),
        })
      )
    )
    renderApp({ route: "/app/tailor" })

    const titles = await screen.findAllByText(/^Role job-/)
    // One row per job, in the order the server ranked them (best first) —
    // the screen never re-sorts or slices what it was given.
    expect(titles.map((element) => element.textContent)).toEqual([
      "Role job-b",
      "Role job-d",
      "Role job-c",
      "Role job-a",
    ])
    // The server was asked for the ranked view — not the raw history.
    expect(requested).toContain("ranked=true")
    expect(requested).toContain("limit=25")
  })
})

describe("the tailor screen", () => {
  it("tails the resume and shows the reports", async () => {
    setCurrentProfileId("profile-1")
    const user = userEvent.setup()
    renderApp({ route: ROUTE })

    await user.click(
      await screen.findByRole("button", { name: "Tailor this resume" })
    )

    expect(
      await screen.findByText("The tailored resume is ready")
    ).toBeInTheDocument()
    expect(screen.getByText("Factuality report")).toBeInTheDocument()
    expect(screen.getByText("ATS report")).toBeInTheDocument()
    expect(screen.getByText("Grounded job insights")).toBeInTheDocument()
    expect(
      screen.getByText(
        "AI Engineer with analytical and machine learning experience."
      )
    ).toBeInTheDocument()
  })

  it("offers the rendered DOCX for download", async () => {
    setCurrentProfileId("profile-1")
    const user = userEvent.setup()
    renderApp({ route: ROUTE })

    await user.click(
      await screen.findByRole("button", { name: "Tailor this resume" })
    )

    const link = await screen.findByRole("link", { name: "Download the DOCX" })
    expect(link).toHaveAttribute(
      "href",
      "http://api.test/api/tailored/tailoring-1/download"
    )
  })

  it("says the deliverable was edited in place, and counts the edits (WS-31)", async () => {
    setCurrentProfileId("profile-1")
    const user = userEvent.setup()
    renderApp({ route: ROUTE })

    await user.click(
      await screen.findByRole("button", { name: "Tailor this resume" })
    )

    expect(await screen.findByText("Your document")).toBeInTheDocument()
    expect(
      screen.getByText(
        "Your own file was edited: the wording changed, your formatting did not."
      )
    ).toBeInTheDocument()
    expect(screen.getByText(/4 passages rewritten/)).toBeInTheDocument()
    // A `.docx` deliverable keeps the DOCX link label.
    expect(
      screen.getByRole("link", { name: "Download the DOCX" })
    ).toBeInTheDocument()
  })

  it("reports a regenerated document as a rewrite, never as an edit (WS-31)", async () => {
    server.use(
      http.post(`${BASE}/api/tailor`, () =>
        HttpResponse.json(
          tailorResponse({
            render: {
              mode: "regenerated",
              source_format: "none",
              edits: 0,
              appended: 0,
              removed: 0,
              skipped: [],
              notes: [
                "The uploaded résumé is not available, so a freshly formatted document was generated instead of editing yours",
              ],
            },
          })
        )
      )
    )
    setCurrentProfileId("profile-1")
    const user = userEvent.setup()
    renderApp({ route: ROUTE })

    await user.click(
      await screen.findByRole("button", { name: "Tailor this resume" })
    )

    expect(
      await screen.findByText("A new document was generated")
    ).toBeInTheDocument()
    expect(
      screen.getByText(/not available, so a freshly formatted document/)
    ).toBeInTheDocument()
    // The counts are not shown for a rewrite — there is nothing to count.
    expect(screen.queryByText(/passages rewritten/)).not.toBeInTheDocument()
  })

  it("names a text deliverable for what it is (WS-31)", async () => {
    server.use(
      http.post(`${BASE}/api/tailor`, () =>
        HttpResponse.json(
          tailorResponse({
            render: {
              mode: "in_place",
              source_format: ".txt",
              edits: 3,
              appended: 0,
              removed: 1,
              skipped: [],
              notes: [],
            },
            docx_path: "./data/tailored/profile-1-greenhouse-1.txt",
          })
        )
      )
    )
    setCurrentProfileId("profile-1")
    const user = userEvent.setup()
    renderApp({ route: ROUTE })

    await user.click(
      await screen.findByRole("button", { name: "Tailor this resume" })
    )

    // The link says "text version", not "DOCX": the file really is text.
    expect(
      await screen.findByRole("link", { name: "Download the text version" })
    ).toBeInTheDocument()
  })

  it("lists what was left untouched when something could not be edited (WS-31)", async () => {
    server.use(
      http.post(`${BASE}/api/tailor`, () =>
        HttpResponse.json(
          tailorResponse({
            render: {
              mode: "in_place",
              source_format: ".docx",
              edits: 2,
              appended: 0,
              removed: 0,
              skipped: [
                "1 table(s) were left untouched; text inside a table is not edited in place",
              ],
              notes: [],
            },
          })
        )
      )
    )
    setCurrentProfileId("profile-1")
    const user = userEvent.setup()
    renderApp({ route: ROUTE })

    await user.click(
      await screen.findByRole("button", { name: "Tailor this resume" })
    )

    expect(await screen.findByText("Left untouched")).toBeInTheDocument()
    expect(
      screen.getByText(/1 table\(s\) were left untouched/)
    ).toBeInTheDocument()
  })

  it("renders a factuality failure as content, not as an error", async () => {
    server.use(
      http.post(`${BASE}/api/tailor`, () =>
        HttpResponse.json(
          tailorResponse({
            factuality: {
              passed: false,
              removed_skills: ["Kubernetes"],
              removed_experience: ["Chief Scientist"],
              removed_projects: [],
              violations: ["'Kubernetes' is not stated by the resume"],
            },
          })
        )
      )
    )
    setCurrentProfileId("profile-1")
    const user = userEvent.setup()
    renderApp({ route: ROUTE })

    await user.click(
      await screen.findByRole("button", { name: "Tailor this resume" })
    )

    expect(
      await screen.findByText(/unsupported item\(s\) were removed/)
    ).toBeInTheDocument()
    expect(screen.getByText("Kubernetes")).toBeInTheDocument()
    expect(screen.getByText("Chief Scientist")).toBeInTheDocument()
    expect(
      screen.getByText("'Kubernetes' is not stated by the resume")
    ).toBeInTheDocument()
    // A failed factuality report is not an error: no error banner.
    expect(
      screen.queryByText(/The server refused the request/)
    ).not.toBeInTheDocument()
  })

  it("says so when the language model is unavailable", async () => {
    server.use(
      http.post(`${BASE}/api/tailor`, () =>
        HttpResponse.json(
          { detail: "The language model is unavailable; try again later." },
          { status: 503 }
        )
      )
    )
    setCurrentProfileId("profile-1")
    const user = userEvent.setup()
    renderApp({ route: ROUTE })

    await user.click(
      await screen.findByRole("button", { name: "Tailor this resume" })
    )

    expect(
      await screen.findByText(
        "The language model is unavailable; try again later."
      )
    ).toBeInTheDocument()
  })

  it("asks for a profile before it can tailor", async () => {
    renderApp({ route: ROUTE })

    await waitFor(() => {
      expect(
        screen.getByText("Tailoring needs a résumé first")
      ).toBeInTheDocument()
    })
  })
})

/*
  WS-37: the Resume Studio contracts (master prompt §9.5, as far as the
  frontend contract reaches). These run against the real route tree with the
  mocked API answering in the backend's exact shapes.
*/
describe("the resume studio (WS-37)", () => {
  /** Run the tailoring and wait for the studio tabs. */
  async function runTailoring() {
    setCurrentProfileId("profile-1")
    const user = userEvent.setup()
    renderApp({ route: ROUTE })
    await user.click(
      await screen.findByRole("button", { name: "Tailor this resume" })
    )
    await screen.findByText("The tailored resume is ready")
    return user
  }

  it("renders the read-only diff with both sides verbatim, a legend, and no accept/reject controls", async () => {
    await runTailoring()

    // The comparison is labelled read-only, because it is: there is no
    // per-change revision model behind it.
    expect(screen.getByText("Read-only comparison")).toBeInTheDocument()

    // Both sides of the summary, exactly as the server sent them — the
    // original text survives the comparison untouched.
    expect(
      screen.getByText(
        "Engineer working on analytical engines and applied machine learning."
      )
    ).toBeInTheDocument()
    expect(
      screen.getByText(
        "AI Engineer with analytical and machine learning experience."
      )
    ).toBeInTheDocument()

    // The legend names every state with icon and label — colour is never
    // the only signal.
    expect(screen.getByText("Legend:")).toBeInTheDocument()
    expect(screen.getAllByText("Unchanged").length).toBeGreaterThan(0)
    expect(screen.getAllByText("Reworded").length).toBeGreaterThan(0)

    // No fake persistence: no accept/reject/edit controls anywhere.
    expect(
      screen.queryByRole("button", { name: /^accept/i })
    ).not.toBeInTheDocument()
    expect(
      screen.queryByRole("button", { name: /accept this change/i })
    ).not.toBeInTheDocument()
    expect(
      screen.queryByRole("button", { name: /^reject/i })
    ).not.toBeInTheDocument()
    expect(
      screen.queryByRole("button", { name: /^undo/i })
    ).not.toBeInTheDocument()
    expect(
      screen.queryByRole("button", { name: /^revert/i })
    ).not.toBeInTheDocument()
  })

  it("surfaces an unpaired original entry as not compared, untouched — never fuzzy-matched", async () => {
    // A second original entry the tailoring produced no counterpart for.
    server.use(
      http.get(`${BASE}/api/resumes/:profileId`, () =>
        HttpResponse.json({
          profile_id: "profile-1",
          profile: candidateProfile({
            experience: [
              {
                title: "Analyst",
                company: "Analytical Engine Project",
                dates: "1842-1843",
                bullets: ["Designed the first published algorithm."],
                years: 1,
              },
              {
                title: "Tutor",
                company: "Windermere House",
                dates: "1840-1841",
                bullets: ["Tutored mathematics."],
                years: 1,
              },
            ],
          }),
        })
      )
    )
    await runTailoring()

    expect(
      screen.getAllByText("Not compared — manual review required").length
    ).toBeGreaterThan(0)
    expect(
      screen.getByText(
        "The tailoring produced no entry with this company and title, so your original text was left untouched in the delivered file. Compare by hand."
      )
    ).toBeInTheDocument()
    // The unmatched original text is shown verbatim for the human review.
    expect(screen.getByText("Tutored mathematics.")).toBeInTheDocument()
  })

  it("keeps a factuality failure visible above the tabs, alongside the ATS report", async () => {
    server.use(
      http.post(`${BASE}/api/tailor`, () =>
        HttpResponse.json(
          tailorResponse({
            factuality: {
              passed: false,
              removed_skills: ["Kubernetes"],
              removed_experience: [],
              removed_projects: [],
              violations: ["'Kubernetes' is not stated by the resume"],
            },
          })
        )
      )
    )
    await runTailoring()

    // The verdict rides above the tabs — on every tab — never hidden
    // behind the green score.
    expect(
      screen.getByText(
        "The factuality check changed the resume before delivery"
      )
    ).toBeInTheDocument()
    // And the full findings sit next to the ATS report on Validation.
    expect(screen.getByText("Factuality report")).toBeInTheDocument()
    expect(screen.getByText("ATS report")).toBeInTheDocument()
    expect(
      screen.getByText("'Kubernetes' is not stated by the resume")
    ).toBeInTheDocument()
  })

  it("splits required from preferred keywords and marks a profile-supported miss as not emphasized", async () => {
    server.use(
      http.post(`${BASE}/api/tailor`, () =>
        HttpResponse.json(
          tailorResponse({
            ats_report: {
              keyword_coverage: {
                required_coverage: 0.5,
                required_hit: ["python"],
                required_missing: ["sql", "kubernetes"],
                preferred_coverage: 0,
                preferred_hit: [],
                preferred_missing: ["spark"],
              },
              section_completeness: { summary: true, experience: true },
              format_risks: [],
              title_alignment: 90,
              score: 85,
              notes: [],
            },
          })
        )
      )
    )
    const user = await runTailoring()

    // Required and preferred are separate groups with their real numbers.
    expect(screen.getByText("Required")).toBeInTheDocument()
    expect(screen.getByText("Preferred")).toBeInTheDocument()
    expect(screen.getByText("1 of 3 present")).toBeInTheDocument()
    expect(screen.getByText("0 of 1 present")).toBeInTheDocument()

    // The distinction is named in visible text, not colour alone.
    expect(screen.getByText("In the tailored resume")).toBeInTheDocument()
    expect(
      screen.getByText("In your profile, not emphasized")
    ).toBeInTheDocument()
    expect(screen.getByText("Not in your source evidence")).toBeInTheDocument()

    // Open the Resume tab — the keyword panel sits beside the diff there.
    await user.click(screen.getByRole("tab", { name: "Resume" }))

    // The three-way split, per term: present (python), supported-but-not-
    // emphasized (sql — the profile states "SQL"), and an honest gap
    // (kubernetes — nothing states it).
    expect(
      screen.getByRole("button", { name: "python — In the tailored resume" })
    ).toBeInTheDocument()
    expect(
      screen.getByRole("button", {
        name: "sql — In your profile, not emphasized",
      })
    ).toBeInTheDocument()
    expect(
      screen.getByRole("button", {
        name: "kubernetes — Not in your source evidence",
      })
    ).toBeInTheDocument()
    expect(
      screen.getByRole("button", {
        name: "spark — Not in your source evidence",
      })
    ).toBeInTheDocument()

    // Selecting a keyword shows the profile evidence.
    await user.click(
      screen.getByRole("button", {
        name: "sql — In your profile, not emphasized",
      })
    )
    expect(screen.getByText("Evidence for “sql”")).toBeInTheDocument()
    expect(screen.getByText(/Skills · SQL/)).toBeInTheDocument()
  })

  it("says coverage could not be measured when the listing has no structured skills", async () => {
    server.use(
      http.post(`${BASE}/api/tailor`, () =>
        HttpResponse.json(
          tailorResponse({
            ats_report: {
              keyword_coverage: {
                required_coverage: 0,
                required_hit: [],
                required_missing: [],
                preferred_coverage: 0,
                preferred_hit: [],
                preferred_missing: [],
              },
              section_completeness: {},
              format_risks: [],
              title_alignment: 50,
              score: 50,
              notes: [
                "Job listing declares no structured skills; keyword coverage could not be measured.",
              ],
            },
          })
        )
      )
    )
    await runTailoring()

    expect(
      screen.getByText("Coverage could not be measured")
    ).toBeInTheDocument()
    // Never a misleading 100% or 0% — no coverage percentages render at all.
    expect(screen.queryByText(/of 0 present/)).not.toBeInTheDocument()
  })

  it("edits the cover letter without touching the resume diff", async () => {
    const user = await runTailoring()

    await user.click(screen.getByRole("tab", { name: /cover letter/i }))

    const draft = await screen.findByLabelText(
      "Cover letter for AI Engineer at Acme"
    )
    // The honest persistence statement: the server does not store edits.
    expect(
      screen.getByText("This draft is not saved on the server")
    ).toBeInTheDocument()

    await user.type(draft, " A postscript the resume never sees.")

    // The edit stays in the letter's own state…
    expect(draft).toHaveValue(
      "Dear hiring team, I build analytical systems. A postscript the resume never sees."
    )
    // …and the resume diff is exactly as it was.
    expect(
      screen.getByText(
        "Engineer working on analytical engines and applied machine learning."
      )
    ).toBeInTheDocument()
    expect(
      screen.getByText(
        "AI Engineer with analytical and machine learning experience."
      )
    ).toBeInTheDocument()
  })

  it("shows the BYOK credential error with its recovery path, and no hopeless retry", async () => {
    server.use(
      http.post(`${BASE}/api/tailor`, () =>
        HttpResponse.json(
          {
            detail:
              "Your model credential was rejected by the provider. Register a working key under Profile → Model credentials.",
          },
          { status: 409 }
        )
      )
    )
    setCurrentProfileId("profile-1")
    const user = userEvent.setup()
    renderApp({ route: ROUTE })

    await user.click(
      await screen.findByRole("button", { name: "Tailor this resume" })
    )

    // The API's specific actionable error, verbatim.
    expect(
      await screen.findByText(
        "Your model credential was rejected by the provider. Register a working key under Profile → Model credentials."
      )
    ).toBeInTheDocument()
    // The recovery path the error names.
    expect(
      screen.getByRole("link", { name: "Open Profile → Model credentials" })
    ).toBeInTheDocument()
  })
})
