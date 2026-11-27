import { screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { http, HttpResponse } from "msw"
import { describe, expect, it } from "vitest"

import {
  candidateProfile,
  jobListing,
  profileResponse,
  tailorResponse,
  tailoredResponse,
} from "@/test/factories"
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
        name: /Your experience\. Better told\./i,
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

describe("optional tailoring", () => {
  it("offers a way to apply with the original when tailoring fails", async () => {
    setCurrentProfileId("profile-1")
    server.use(
      http.post(`${BASE}/api/tailor`, () =>
        HttpResponse.json(
          { detail: "Tailoring is temporarily unavailable" },
          { status: 503 }
        )
      )
    )
    const user = userEvent.setup()
    renderApp({ route: ROUTE })
    await user.click(
      await screen.findByRole("button", { name: "Tailor this resume" })
    )
    expect(
      await screen.findByText(/tailoring is temporarily unavailable/i)
    ).toBeVisible()
    expect(
      screen.getByRole("link", { name: /use your original résumé/i })
    ).toHaveAttribute("href", "/app/matches/greenhouse%3A1/prepare")
  })
})

describe("opening a saved Studio draft", () => {
  it("loads the exact draft and compares it with its own source résumé", async () => {
    setCurrentProfileId("profile-1")
    const user = userEvent.setup()
    server.use(
      http.get(`${BASE}/api/tailored/saved-draft`, () =>
        HttpResponse.json({
          ...tailoredResponse(),
          tailoring_id: "saved-draft",
          profile_id: "archived-profile",
          edited_at: "2026-11-22T10:05:00Z",
        })
      ),
      http.get(`${BASE}/api/resumes/archived-profile`, () =>
        HttpResponse.json({
          ...profileResponse(),
          profile_id: "archived-profile",
          profile: candidateProfile({
            summary: "Source from the archived résumé.",
          }),
        })
      )
    )
    renderApp({ route: `${ROUTE}?draft=saved-draft` })

    expect(await screen.findByText("Diff review · edited by you")).toBeVisible()
    expect(
      await screen.findByText("Source from the archived résumé.", {
        selector: "del",
      })
    ).toBeVisible()
    await user.click(screen.getByRole("tab", { name: "Original" }))
    expect(
      screen.getByText("Source from the archived résumé.", { selector: "p" })
    ).toBeVisible()
    expect(
      screen.getByRole("link", { name: /Download.*DOCX/ })
    ).toHaveAttribute("href", `${BASE}/api/tailored/saved-draft/download`)
  })

  it.each([404, 200])(
    "does not open an unavailable draft (%s)",
    async (status) => {
      setCurrentProfileId("profile-1")
      server.use(
        http.get(`${BASE}/api/tailored/unavailable`, () =>
          HttpResponse.json(
            status === 404
              ? { detail: "Tailoring not found" }
              : {
                  ...tailoredResponse(),
                  tailoring_id: "unavailable",
                  job_id: "greenhouse:another-job",
                },
            { status }
          )
        )
      )
      renderApp({ route: `${ROUTE}?draft=unavailable` })

      expect(await screen.findByText("Draft not available")).toBeVisible()
      expect(
        screen.getByRole("link", { name: "Open your documents" })
      ).toBeVisible()
      expect(
        screen.queryByRole("button", { name: "Tailor this resume" })
      ).not.toBeInTheDocument()
      expect(
        screen.queryByRole("link", { name: /Download.*DOCX/ })
      ).not.toBeInTheDocument()
    }
  )

  it("keeps the last draft and its address if a rerun fails", async () => {
    setCurrentProfileId("profile-1")
    const user = userEvent.setup()
    const { router } = renderApp({ route: ROUTE })
    await user.click(
      await screen.findByRole("button", { name: "Tailor this resume" })
    )
    await screen.findByRole("heading", { name: "Make every claim count." })
    server.use(
      http.post(`${BASE}/api/tailor`, () =>
        HttpResponse.json(
          { detail: "The language model is unavailable; try again later." },
          { status: 503 }
        )
      )
    )

    await user.click(screen.getByRole("button", { name: "Tailor again" }))
    expect(
      await screen.findByText(
        "The language model is unavailable; try again later."
      )
    ).toBeVisible()
    expect(
      screen.getByRole("heading", { name: "Make every claim count." })
    ).toBeVisible()
    expect(screen.getByText("Diff review · proposed")).toBeVisible()
    expect(router.state.location.search).toBe("?draft=tailoring-1")
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

  it("renders the design's composition: the paper canvas and the evidence rail (WS-42)", async () => {
    setCurrentProfileId("profile-1")
    const user = userEvent.setup()
    renderApp({ route: ROUTE })

    await user.click(
      await screen.findByRole("button", { name: "Tailor this resume" })
    )

    // The header is the design's headline, not the job title — the job
    // lives on the paper.
    expect(
      screen.getByRole("heading", { name: "Your experience. Better told." })
    ).toBeInTheDocument()

    // The document canvas: the job title, and the meta line that says what
    // this paper is (node 49:979).
    expect(
      screen.getByRole("heading", { name: "AI Engineer", level: 2 })
    ).toBeInTheDocument()
    expect(
      await screen.findByText("Acme · tailored draft · source preserved")
    ).toBeVisible()

    const sourceSummary = screen.getByText(candidateProfile().summary!, {
      selector: "del",
    })
    expect(sourceSummary).toBeVisible()

    // The design's status chip beside the pills: the tailored wording is a
    // proposal until the candidate authorizes it on Review.
    expect(screen.getByText("Diff review · proposed")).toBeInTheDocument()

    // The evidence rail (node 49:997) with its real headline and meters.
    expect(
      screen.getByRole("heading", { name: "Make every claim count." })
    ).toBeInTheDocument()
    expect(screen.getByText("Required keywords · 1 of 2")).toBeInTheDocument()

    // The factuality chip is the validator's own finding, derived — the
    // design's example just asserts "0".
    expect(screen.getByText("0 unsupported claims")).toBeInTheDocument()

    // Review is navigation to the exact draft for the posting.
    expect(
      screen.getByRole("link", { name: "Continue to review →" })
    ).toHaveAttribute(
      "href",
      "/app/matches/greenhouse%3A1/prepare?draft=tailoring-1"
    )

    // Every changed passage carries a provenance line, and a passed
    // factuality check is what licenses "no new claims added" (node 49:996).
    expect(
      screen.getByText(
        "Source: summary · wording changed, no new claims added."
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

    const link = await screen.findByRole("link", { name: "Download DOCX" })
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
    // A `.docx` deliverable keeps the DOCX pill label.
    expect(
      screen.getByRole("link", { name: "Download DOCX" })
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

    // The pill says "text version", not "DOCX": the file really is text.
    expect(
      await screen.findByRole("link", { name: "Download the text version" })
    ).toBeInTheDocument()
    // …and the preview pill says it too.
    expect(
      screen.getByRole("tab", { name: "Preview text version" })
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
    // And the rail's chip names the strip instead of claiming zero.
    expect(
      screen.getByText("2 unsupported claims stripped")
    ).toBeInTheDocument()
  })

  it("reports a factuality correction even when no entire entry was removed", async () => {
    const violation = "Removed an unsupported claim of 9 years of experience."
    server.use(
      http.post(`${BASE}/api/tailor`, () =>
        HttpResponse.json(
          tailorResponse({
            factuality: {
              passed: false,
              removed_skills: [],
              removed_experience: [],
              removed_projects: [],
              violations: [violation],
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
      await screen.findByText("Wording corrected · see Validation")
    ).toBeVisible()
    expect(screen.queryByText(/0 unsupported/)).not.toBeInTheDocument()
    await user.click(screen.getByRole("tab", { name: "Validation" }))
    expect(screen.getByText(violation)).toBeVisible()
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
  mocked API answering in the backend's exact shapes. WS-42 rebuilt the
  composition to design node `16:82`; the contracts below are the same
  honesty assertions re-pointed at the new structure.
*/
describe("the resume studio (WS-37, composition from WS-42)", () => {
  /** Run the tailoring and wait for the studio pills. */
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

  it("renders the read-only diff with both sides verbatim, the design's legend, and no accept/reject controls", async () => {
    await runTailoring()

    // The comparison is labelled read-only, because it is: there is no
    // per-change revision model behind it.
    expect(screen.getByText(/Read-only comparison/)).toBeInTheDocument()

    // Both sides of the summary, exactly as the server sent them — the
    // original text survives the comparison untouched. (The original also
    // appears on the mounted Original tab, so "at least one" is the
    // assertion's scope; the wording itself is the point.)
    expect(
      screen.getAllByText(
        "Engineer working on analytical engines and applied machine learning."
      ).length
    ).toBeGreaterThan(0)
    expect(
      screen.getByText(
        "AI Engineer with analytical and machine learning experience."
      )
    ).toBeInTheDocument()

    // The design's two-chip legend (node 49:981) names the washes…
    expect(screen.getByText(/Original wording/)).toBeInTheDocument()
    expect(screen.getByText(/Tailored wording/)).toBeInTheDocument()

    // …and every state still carries its own words — colour is never the
    // only signal.
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
    // And no editor toolbar either: formatting controls that change
    // nothing would be a lie about what this read-only surface can do.
    expect(
      screen.queryByRole("button", { name: /^Body · 11 pt/ })
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
    expect(screen.getAllByText("Tutored mathematics.").length).toBeGreaterThan(
      0
    )
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

    // The verdict rides above the pills — on every tab — never hidden
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
    // The provenance lines lose the "no new claims added" clause, because
    // the validator's own finding is what licenses it.
    expect(
      screen.getByText("Source: summary · wording changed.")
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

    // Required and preferred are separate meters with their real numbers —
    // the design's "Required keywords · n of m" format (node 49:999).
    expect(screen.getByText("Required keywords · 1 of 3")).toBeInTheDocument()
    expect(screen.getByText("Preferred keywords · 0 of 1")).toBeInTheDocument()

    // The group labels distinguish the states without relying on the washes.
    expect(screen.getByText("Matched in your source")).toBeVisible()
    expect(screen.getByText("In your profile, not emphasized")).toBeVisible()
    expect(screen.getByText("Not evidenced")).toBeVisible()

    // The three-way split, per term: present (python), supported-but-not-
    // emphasized (sql — the profile states "SQL"), and an honest gap
    // (kubernetes — nothing states it). The washes live in the rail on the
    // default tab.
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
    // Never a misleading 100% or 0% — no coverage meters render at all.
    expect(screen.queryByText(/keywords · \d+ of/)).not.toBeInTheDocument()
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
      screen.getAllByText(
        "Engineer working on analytical engines and applied machine learning."
      ).length
    ).toBeGreaterThan(0)
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
              "Your model key is missing or unusable. Add or update it under Account → Model credentials.",
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
        "Your model key is missing or unusable. Add or update it under Account → Model credentials."
      )
    ).toBeInTheDocument()
    // The recovery path the error names — the account screen now hosts the
    // model credentials (WS-46), so that is where the link goes (WS-47).
    const recovery = screen.getByRole("link", {
      name: "Open Account → Model credentials",
    })
    expect(recovery).toHaveAttribute("href", "/app/account?tab=credentials")
    expect(
      screen.queryByRole("button", { name: "Try again" })
    ).not.toBeInTheDocument()
  })
})

/*
  WS-47: the studio's edit flow. The studio can now edit the draft's sections
  and save them: the server revalidates factuality against the profile, re-runs
  the ATS analysis, regenerates the deliverable, and answers with the updated
  record — which is what the screen then shows.
*/
describe("the studio editor (ws-47)", () => {
  /** Run the tailoring and wait for the studio pills. */
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

  /** A stored record shaped like the PUT answers, with an edit stamp. */
  function editedRecord() {
    return {
      ...tailorResponse({
        tailored: {
          ...tailorResponse().tailored,
          summary: "Edited summary in the studio.",
        },
      }),
      created_at: "2026-10-21T10:00:00Z",
      edited_at: "2026-11-21T10:05:00Z",
    }
  }

  it("renders the real deliverable format in the toolbar row, and no fake formatting controls", async () => {
    await runTailoring()

    // The render report says what the deliverable really is: the caller's own
    // DOCX, edited in place. That is the toolbar row's format truth — not a
    // "Body · 11 pt" control pretending to edit runs the editor never touches.
    expect(screen.getByText("Body · DOCX")).toBeInTheDocument()
    expect(
      screen.queryByRole("button", { name: /^Body ·/ })
    ).not.toBeInTheDocument()
    expect(
      screen.queryByRole("button", { name: /^Bold$/i })
    ).not.toBeInTheDocument()
  })

  it("edits the sections, saves them, and shows the edited record", async () => {
    let putBody: unknown = null
    let putCount = 0
    server.use(
      http.put(`${BASE}/api/tailored/tailoring-1`, async ({ request }) => {
        putCount += 1
        putBody = await request.json()
        return HttpResponse.json(editedRecord())
      })
    )
    const user = await runTailoring()

    await user.click(screen.getByRole("button", { name: "Edit draft" }))

    // The editor opens with the record's own content, labelled and editable.
    const summary = await screen.findByLabelText("Professional summary")
    expect(summary).toHaveValue(
      "AI Engineer with analytical and machine learning experience."
    )
    // One bullet per line — the mapping the server re-chunks onto the entries.
    expect(screen.getByLabelText("Experience bullets")).toHaveValue(
      "Designed the first published algorithm."
    )
    expect(
      screen.getByLabelText("Cover letter", { selector: "textarea" })
    ).toHaveValue("Dear hiring team, I build analytical systems.")

    await user.clear(summary)
    await user.type(summary, "Edited summary in the studio.")

    await user.click(screen.getByRole("button", { name: "Save changes" }))

    // The save sends the edited sections as the contract carries them.
    expect(putCount).toBe(1)
    expect(putBody).toEqual({
      summary: "Edited summary in the studio.",
    })

    // The chip tells the truth about whose words these now are.
    expect(
      await screen.findByText("Diff review · edited by you")
    ).toBeInTheDocument()
    expect(screen.queryByText("Diff review · proposed")).not.toBeInTheDocument()

    // The comparison shows the saved wording (server-authoritative), and the
    // editor is closed again — the canvas is back to read-only.
    expect(
      await screen.findByText("Edited summary in the studio.")
    ).toBeInTheDocument()
    expect(
      screen.queryByLabelText("Professional summary")
    ).not.toBeInTheDocument()
  })

  it("saves a summary when the draft has no experience entries", async () => {
    const withoutExperience = tailorResponse({
      tailored: { ...tailorResponse().tailored, experience: [] },
    })
    server.use(
      http.post(`${BASE}/api/tailor`, () =>
        HttpResponse.json(withoutExperience)
      ),
      http.put(`${BASE}/api/tailored/tailoring-1`, async ({ request }) => {
        const body = (await request.json()) as Record<string, unknown>
        if (body.experience != null) {
          return HttpResponse.json(
            {
              detail: "The tailored resume has no experience entries to edit.",
            },
            { status: 422 }
          )
        }
        return HttpResponse.json({
          ...editedRecord(),
          tailored: {
            ...withoutExperience.tailored,
            summary: String(body.summary),
          },
        })
      })
    )
    const user = await runTailoring()
    await user.click(screen.getByRole("button", { name: "Edit draft" }))
    const summary = await screen.findByLabelText("Professional summary")
    await user.clear(summary)
    await user.type(summary, "Updated summary without a work history.")
    await user.click(screen.getByRole("button", { name: "Save changes" }))

    expect(await screen.findByText("Diff review · edited by you")).toBeVisible()
    expect(
      screen.getByText("Updated summary without a work history.")
    ).toBeVisible()
  })

  it("shows the saved cover letter after editing it on Inline diff", async () => {
    const savedLetter = "Dear hiring team, I write tested software."
    server.use(
      http.put(`${BASE}/api/tailored/tailoring-1`, () =>
        HttpResponse.json({
          ...editedRecord(),
          tailored: { ...editedRecord().tailored, cover_letter: savedLetter },
        })
      )
    )
    const user = await runTailoring()
    const letterTab = () => screen.getByRole("tab", { name: "Cover letter" })
    await user.click(letterTab())
    expect(
      screen.getByRole("textbox", { name: /Cover letter for/ })
    ).toHaveValue("Dear hiring team, I build analytical systems.")
    await user.click(screen.getByRole("tab", { name: "Inline diff" }))
    await user.click(screen.getByRole("button", { name: "Edit draft" }))
    const letter = await screen.findByLabelText("Cover letter", {
      selector: "textarea",
    })
    await user.clear(letter)
    await user.type(letter, savedLetter)
    await user.click(screen.getByRole("button", { name: "Save changes" }))
    await screen.findByText("Diff review · edited by you")
    await user.click(letterTab())
    expect(
      screen.getByRole("textbox", { name: /Cover letter for/ })
    ).toHaveValue(savedLetter)
  })

  it("discards an edit without saving anything", async () => {
    let putCount = 0
    server.use(
      http.put(`${BASE}/api/tailored/tailoring-1`, async () => {
        putCount += 1
        return HttpResponse.json(editedRecord())
      })
    )
    const user = await runTailoring()

    await user.click(screen.getByRole("button", { name: "Edit draft" }))
    const summary = await screen.findByLabelText("Professional summary")
    await user.clear(summary)
    await user.type(summary, "A draft that will be thrown away.")

    await user.click(screen.getByRole("button", { name: "Discard changes" }))

    // Nothing was sent, nothing changed: the record is still the proposal.
    expect(putCount).toBe(0)
    expect(screen.getByText("Diff review · proposed")).toBeInTheDocument()
    expect(
      screen.getByText(
        "AI Engineer with analytical and machine learning experience."
      )
    ).toBeInTheDocument()
    expect(
      screen.queryByLabelText("Professional summary")
    ).not.toBeInTheDocument()
  })

  it("reports a post-save factuality violation as content, never as an error", async () => {
    server.use(
      http.put(`${BASE}/api/tailored/tailoring-1`, async () =>
        HttpResponse.json({
          ...tailorResponse({
            factuality: {
              passed: false,
              removed_skills: ["Kubernetes"],
              removed_experience: [],
              removed_projects: [],
              violations: ["'Kubernetes' is not stated by the resume"],
            },
          }),
          created_at: "2026-10-21T10:00:00Z",
          edited_at: "2026-11-21T10:05:00Z",
        })
      )
    )
    const user = await runTailoring()

    await user.click(screen.getByRole("button", { name: "Edit draft" }))
    await user.type(
      await screen.findByLabelText("Professional summary"),
      " Kubernetes."
    )
    await user.click(screen.getByRole("button", { name: "Save changes" }))

    // The verdict rides above the tabs, exactly as it does after a run…
    expect(
      await screen.findByText(
        "The factuality check changed the resume before delivery"
      )
    ).toBeInTheDocument()
    // …the editor is closed…
    expect(
      screen.queryByLabelText("Professional summary")
    ).not.toBeInTheDocument()
    // …the chip says the edit was saved…
    expect(screen.getByText("Diff review · edited by you")).toBeInTheDocument()
    // …and nothing is an error: no refusal banner.
    expect(
      screen.queryByText("The save did not go through")
    ).not.toBeInTheDocument()
  })

  it("keeps the editor open with the server's own error when a save fails", async () => {
    server.use(
      http.put(`${BASE}/api/tailored/tailoring-1`, async () =>
        HttpResponse.json(
          {
            detail:
              "The profile this tailoring was built from no longer exists, so the edit cannot be validated against it. Re-tailor the resume instead.",
          },
          { status: 409 }
        )
      )
    )
    const user = await runTailoring()

    await user.click(screen.getByRole("button", { name: "Edit draft" }))
    const summary = await screen.findByLabelText("Professional summary")
    await user.clear(summary)
    await user.type(summary, "Work the server refused to accept.")

    await user.click(screen.getByRole("button", { name: "Save changes" }))

    // The server's actionable detail, verbatim…
    expect(
      await screen.findByText(/no longer exists, so the edit cannot be/)
    ).toBeInTheDocument()
    // …and the work is not lost: the editor is still open with the draft.
    expect(summary).toHaveValue("Work the server refused to accept.")
    expect(screen.getByText("Diff review · proposed")).toBeInTheDocument()
  })
})

/*
  WS-47: the rail's deliverable caption adapts to how the file was actually
  produced — an in-place edit has no regenerated layout to check, and a
  rewrite must say so. Pinned per case, from the render report's real data.
*/
describe("the evidence rail's deliverable caption (ws-47)", () => {
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

  it("says the delivered layout is the one to check after an in-place edit", async () => {
    await runTailoring()
    expect(
      screen.getByText(
        "Original preserved. Your own file was edited in place — check the delivered layout before export."
      )
    ).toBeInTheDocument()
  })

  it("says the regenerated layout is the one to check after a rewrite", async () => {
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
              notes: [],
            },
          })
        )
      )
    )
    await runTailoring()
    expect(
      screen.getByText(
        "Original preserved. Check the regenerated DOCX layout before export."
      )
    ).toBeInTheDocument()
  })
})
