import { screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { http, HttpResponse } from "msw"
import { describe, expect, it } from "vitest"

import { renderApp } from "@/test/render"
import { server } from "@/test/server"

const BASE = "http://api.test"

/**
 * WS-25b · The approval must show the form the board actually publishes.
 *
 * `prepared_summary.field_names` is our internal field map — sorted
 * alphabetically at `src/api/routes/applications.py:549`. The board's own
 * **measured** question order has been returned in `form_questions` since
 * WS-25b and the panel never read it, so the operator approved a payload
 * without seeing the form it fills. §10.4 records this as the second half of
 * the same open item as the profile screen's guessed order.
 *
 * Two properties, and both have a real failure behind them:
 *
 * 1. the board's order is rendered as sent, not re-sorted;
 * 2. a blocking question is **named**, not counted — "1 question needs a
 *    human" tells the operator there is a problem and not which one.
 */
function setupUser() {
  return userEvent.setup({ delay: null })
}

async function prepare(user: ReturnType<typeof userEvent.setup>) {
  renderApp({ route: "/app/approvals" })
  await user.type(await screen.findByLabelText("Job title"), "AI Engineer")
  await user.type(screen.getByLabelText("Company"), "Figma")
  await user.type(
    screen.getByLabelText("Job URL"),
    "https://boards.greenhouse.io/figma/jobs/1"
  )
  await user.type(screen.getByLabelText("Candidate name"), "Ada Lovelace")
  await user.type(screen.getByLabelText("Email"), "ada@example.com")
  await user.type(screen.getByLabelText("Phone"), "+44 20 7946 0000")
  await user.click(screen.getByRole("button", { name: "Prepare application" }))
}

function stubPrepareWithForm() {
  server.use(
    http.post(`${BASE}/api/applications/prepare`, () =>
      HttpResponse.json({
        approval_id: "approval-1",
        workflow_id: "workflow-1",
        adapter_name: "greenhouse",
        status: "blocked_human_review",
        // The board's own order: identity first, then the custom question.
        // Deliberately not alphabetical, so a re-sort in the console fails.
        form_questions: [
          {
            label: "First Name",
            required: true,
            block: "questions",
            verdict: "answerable",
            category: "candidate_first_name",
            answer_from: "candidate_name",
            fields: ["first_name"],
          },
          {
            label: "Latitude",
            required: true,
            block: "questions",
            verdict: "needs_human",
            category: "location_latitude",
            answer_from: null,
            fields: ["latitude"],
          },
          {
            label: "Why do you want to join Figma?",
            required: true,
            block: "questions",
            verdict: "needs_human",
            category: "unknown",
            answer_from: null,
            fields: ["question_42"],
          },
        ],
        blocking_questions: ["Latitude", "Why do you want to join Figma?"],
        prepared_summary: {
          job_title: "AI Engineer",
          company_name: "Figma",
          job_url: "https://boards.greenhouse.io/figma/jobs/1",
          adapter_name: "greenhouse",
          field_names: ["email", "name", "phone"],
          profile_fact_names: ["email", "name"],
          resume_path: null,
          requires_manual_review: true,
          application_id: "application-1",
        },
        application_id: "application-1",
      })
    )
  )
}

describe("the approval panel's board questions", () => {
  it("renders the board's own question order", async () => {
    stubPrepareWithForm()
    const user = setupUser()
    await prepare(user)

    const panel = await screen.findByTestId("board-questions")
    const labels = within(panel)
      .getAllByRole("listitem")
      .map((item) => item.textContent ?? "")

    const first = labels.findIndex((text) => text.includes("First Name"))
    const latitude = labels.findIndex((text) => text.includes("Latitude"))
    const custom = labels.findIndex((text) => text.includes("Why do you want"))

    expect(first).toBeGreaterThanOrEqual(0)
    // As sent. Alphabetical would put "First Name" first anyway, so the
    // second pair is what proves the order is the board's: Latitude before
    // the custom question, which sorting would reverse.
    expect(latitude).toBeGreaterThan(first)
    expect(custom).toBeGreaterThan(latitude)
  })

  it("names each question that needs a human", async () => {
    stubPrepareWithForm()
    const user = setupUser()
    await prepare(user)

    const panel = await screen.findByTestId("board-questions")
    // Both blockers are named in the panel, not merely counted.
    const items = within(panel).getAllByRole("listitem")
    const blockers = items.filter((item) =>
      /needs a human/i.test(item.textContent ?? "")
    )
    expect(blockers.map((item) => item.textContent)).toEqual(
      expect.arrayContaining([
        expect.stringContaining("Latitude"),
        expect.stringContaining("Why do you want to join Figma?"),
      ])
    )
  })

  it("renders no board section when the board publishes no schema", async () => {
    // The fail-soft path: a board that timed out, or one that publishes no
    // schema at all (Remotive). The panel keeps the layout it had.
    server.use(
      http.post(`${BASE}/api/applications/prepare`, () =>
        HttpResponse.json({
          approval_id: "approval-1",
          workflow_id: "workflow-1",
          adapter_name: "fake-ats",
          status: "awaiting_approval",
          form_questions: [],
          blocking_questions: [],
          prepared_summary: {
            job_title: "AI Engineer",
            company_name: "Acme",
            job_url: "http://127.0.0.1:8901/basic",
            adapter_name: "fake-ats",
            field_names: ["email", "name", "phone"],
            profile_fact_names: ["email", "name", "phone"],
            resume_path: null,
            requires_manual_review: false,
          },
          application_id: "application-1",
        })
      )
    )
    const user = setupUser()
    await prepare(user)

    expect(await screen.findByText("What will be submitted")).toBeInTheDocument()
    expect(screen.queryByTestId("board-questions")).not.toBeInTheDocument()
  })
})
