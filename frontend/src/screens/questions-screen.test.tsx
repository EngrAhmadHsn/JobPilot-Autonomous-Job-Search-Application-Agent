import { screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { http, HttpResponse } from "msw"
import { describe, expect, it } from "vitest"

import { renderApp } from "@/test/render"
import { server } from "@/test/server"

const BASE = "http://api.test"
const ROUTE = "/app/tracker/application-1/questions"

const SPONSORSHIP = "Will you now or in the future require visa sponsorship?"

/**
 * WS-45 · The per-application questions page.
 *
 * The page exists because the Review screen answers one question at a time
 * and the design's way into the full list ("View all questions →") had
 * nowhere to go. What these tests pin:
 *
 * - it renders the **prepared packet's** questions, in the board's own
 *   order, off `GET /api/applications/{id}/questions` — the stored plan,
 *   not a live form fetch;
 * - a save goes through `PUT .../answers` with the question's own key, and
 *   the row's chip follows the **server's** re-read (the backend folds the
 *   saved answer into the stored verdict), so the page can never claim an
 *   answer the server did not accept;
 * - a never-autofill question (EEO / attestation) is listed with its
 *   verdict and **no control at all** — the console refuses to store such an
 *   answer, and offering the control would be a lie;
 * - an application with no prepared plan says its questions are *unknown*,
 *   rather than rendering an empty form that reads as "nothing was asked".
 */

/** The plan as the API sends it: verdicts, categories, the board's order. */
const PLAN = [
  {
    question_key: "first name",
    label: "First Name",
    required: true,
    block: "Personal information",
    verdict: "answerable",
    category: "first_name",
    answer_from: "first_name",
    fields: ["first_name"],
  },
  {
    question_key: SPONSORSHIP.toLowerCase(),
    label: SPONSORSHIP,
    required: true,
    block: "Personal information",
    verdict: "needs_human",
    category: "visa_sponsorship",
    answer_from: null,
    fields: ["question_42"],
  },
  {
    question_key: "voluntary self identification of gender",
    label: "Voluntary Self Identification of Gender",
    required: false,
    block: "Voluntary self identification",
    verdict: "never_autofill",
    category: "eeo_gender",
    answer_from: null,
    fields: ["question_99"],
  },
]

function questionsBody(overrides: Record<string, unknown> = {}) {
  return {
    application_id: "application-1",
    approval_id: "approval-1",
    job_title: "Backend Engineer",
    company_name: "Northstar Labs",
    job_url: "https://boards.example/northstar/1",
    status: "awaiting_approval",
    plan_available: true,
    questions: PLAN,
    answers: [],
    blocking_questions: [SPONSORSHIP],
    ...overrides,
  }
}

describe("the per-application questions page", () => {
  it("renders the prepared packet's questions in the board's own order", async () => {
    server.use(
      http.get(`${BASE}/api/applications/application-1/questions`, () =>
        HttpResponse.json(questionsBody())
      )
    )

    renderApp({ route: ROUTE })

    const rows = await screen.findAllByTestId("question-row")
    expect(rows).toHaveLength(3)
    expect(
      rows.map(
        (row) =>
          within(row).getByText(/^(First Name|Will you now|Voluntary Self)/)
            .textContent
      )
    ).toEqual([
      "First Name",
      SPONSORSHIP,
      "Voluntary Self Identification of Gender",
    ])

    // The board's position chips are the design's: `QUESTION i OF n`.
    expect(within(rows[1]!).getByText("QUESTION 2 OF 3")).toBeInTheDocument()
    // The queue counts, from the server's own verdicts.
    expect(screen.getByText("Needs you 1")).toBeInTheDocument()
    expect(screen.getByText("Confirmed 2")).toBeInTheDocument()
    // The source of a profile-derived answer is named, not implied.
    expect(
      within(rows[0]!).getByText(/From your application profile \(first_name\)/)
    ).toBeInTheDocument()
  })

  it(
    "saves an answer under the question's key and follows the server's re-read",
    { timeout: 20_000 },
    async () => {
      const puts: unknown[] = []
      let saved = false
      server.use(
        http.get(`${BASE}/api/applications/application-1/questions`, () =>
          HttpResponse.json(
            saved
              ? questionsBody({
                  questions: PLAN.map((question) =>
                    question.label === SPONSORSHIP
                      ? {
                          ...question,
                          verdict: "answerable",
                          answer_from: "you",
                        }
                      : question
                  ),
                  answers: [
                    {
                      question_key: SPONSORSHIP.toLowerCase(),
                      label: SPONSORSHIP,
                      category: "visa_sponsorship",
                      answer: "No",
                      answered_at: "2026-11-21T10:00:00Z",
                    },
                  ],
                  blocking_questions: [],
                })
              : questionsBody()
          )
        ),
        http.put(
          `${BASE}/api/applications/application-1/answers`,
          async ({ request }) => {
            puts.push(await request.json())
            saved = true
            return HttpResponse.json({
              application_id: "application-1",
              answers: [],
            })
          }
        )
      )

      renderApp({ route: ROUTE })

      const user = userEvent.setup()
      const rows = await screen.findAllByTestId("question-row")
      const sponsorshipRow = rows.find((element) =>
        within(element).queryByText(SPONSORSHIP)
      )
      expect(sponsorshipRow).toBeDefined()

      // The boolean question gets the design's Yes/No pair, not a text box.
      await user.click(
        within(sponsorshipRow!).getByRole("radio", { name: "No" })
      )
      await user.click(
        within(sponsorshipRow!).getByRole("button", { name: /Save answer/ })
      )

      expect(puts).toHaveLength(1)
      expect(puts[0]).toEqual({
        answers: [
          {
            question_key: SPONSORSHIP.toLowerCase(),
            label: SPONSORSHIP,
            category: "visa_sponsorship",
            answer: "No",
          },
        ],
      })

      // The chip moves off the server's answer, never off a local guess.
      expect(
        await within(sponsorshipRow!).findByText("Confirmed")
      ).toBeInTheDocument()
      expect(
        within(sponsorshipRow!).getByText("Your answer:")
      ).toBeInTheDocument()
      expect(await screen.findByText("Needs you 0")).toBeInTheDocument()
    }
  )

  it("lists a never-autofill question with no control at all", async () => {
    server.use(
      http.get(`${BASE}/api/applications/application-1/questions`, () =>
        HttpResponse.json(questionsBody())
      )
    )

    renderApp({ route: ROUTE })

    const rows = await screen.findAllByTestId("question-row")
    const eeoRow = rows.find((row) =>
      within(row).queryByText("Voluntary Self Identification of Gender")
    )
    expect(eeoRow).toBeDefined()

    expect(
      within(eeoRow!).getByText("On the employer's site")
    ).toBeInTheDocument()
    // No radio pair, no text box, no save button: the API would refuse it.
    expect(within(eeoRow!).queryByRole("radio")).toBeNull()
    expect(within(eeoRow!).queryByRole("textbox")).toBeNull()
    expect(within(eeoRow!).queryByRole("button")).toBeNull()
  })

  it("reports unknown questions for an application that was never prepared", async () => {
    server.use(
      http.get(`${BASE}/api/applications/application-1/questions`, () =>
        HttpResponse.json(
          questionsBody({
            plan_available: false,
            questions: [],
            blocking_questions: [],
          })
        )
      )
    )

    renderApp({ route: ROUTE })

    expect(
      await screen.findByText("No prepared questions for this application.")
    ).toBeInTheDocument()
    // An empty list is not the same claim as "the employer asked nothing".
    expect(screen.queryByText("The employer's form.")).toBeNull()
    expect(screen.queryByTestId("question-row")).toBeNull()
  })
})
