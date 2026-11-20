import { screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { http, HttpResponse } from "msw"
import { describe, expect, it } from "vitest"

import { renderApp } from "@/test/render"
import { server } from "@/test/server"

const BASE = "http://api.test"

/**
 * WS-45 task 4 · the Review screen's per-application answering flow.
 *
 * Until now a required employer question blocked approval with no path
 * through the console. The answers routes (`GET`/`PUT
 * /api/applications/{id}/answers`) give the human's answer a home, and the
 * prepare flow re-merges it: a saved answer flips the question's verdict to
 * `answerable` (`answer_from: "you"`) and `blocking_questions` shrinks —
 * **but only on a re-prepare**, because every prepare creates a fresh
 * application row and the saved answers are inherited onto it. That wiring
 * fact is what these tests pin:
 *
 * 1. saving sends the answer under the `question_key` the prepare response
 *    handed the console, addressed to the application that prepare created;
 * 2. saving **re-prepares with the same payload** — the merge is
 *    server-side, and re-preparing is the only path to it;
 * 3. the answered question leaves the queue, the next one surfaces one at a
 *    time, and when `blocking_questions` is empty the "Not ready to
 *    authorize" panel is gone and the authorize action is enabled;
 * 4. a never-autofill question (EEO/attestation) is never offered a save —
 *    it renders read-only, routed to the employer site;
 * 5. a save the server refuses (422) surfaces the server's own sentence,
 *    verbatim — never a paraphrase.
 */

const VISA =
  "Will you now or in the future require visa sponsorship for this role?"
const AUTH = "Are you legally authorized to work in the United States?"
const EEO = "What is your race or ethnicity?"
const VISA_KEY =
  "will you now or in the future require visa sponsorship for this role"
const AUTH_KEY = "are you legally authorized to work in the united states"

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
  await screen.findByText("What will be submitted")
}

/**
 * The board's form, as the merged plan would publish it. The first question
 * is never-autofill (the design draws the demographics block on the same
 * form); `answered` flips the two human questions the way the backend's
 * merge does after a save — verdict `answerable`, source `you`.
 */
function formQuestions(answered: { visa?: boolean; auth?: boolean } = {}) {
  return [
    {
      label: EEO,
      required: true,
      block: "demographics",
      verdict: "never_autofill",
      category: "eeo_race",
      answer_from: null,
      fields: ["race"],
      question_key: "what is your race or ethnicity",
    },
    {
      label: "First Name",
      required: true,
      block: "questions",
      verdict: "answerable",
      category: "candidate_first_name",
      answer_from: "candidate_name",
      fields: ["first_name"],
      question_key: "first name",
    },
    {
      label: VISA,
      required: true,
      block: "questions",
      verdict: answered.visa ? "answerable" : "needs_human",
      category: "visa_sponsorship",
      answer_from: answered.visa ? "you" : null,
      fields: ["visa_sponsorship"],
      question_key: VISA_KEY,
    },
    {
      label: AUTH,
      required: true,
      block: "questions",
      verdict: answered.auth ? "answerable" : "needs_human",
      category: "work_authorization",
      answer_from: answered.auth ? "you" : null,
      fields: ["legally_authorized"],
      question_key: AUTH_KEY,
    },
    {
      label: "Available start date",
      required: false,
      block: "questions",
      verdict: "optional_unanswered",
      category: "availability_date",
      answer_from: null,
      fields: ["start_date"],
      question_key: "available start date",
    },
  ]
}

/**
 * A stateful mock of the whole WS-45 chain: prepare (which creates a fresh
 * application and inherits the answers saved so far), GET answers, PUT
 * answers. The captured request bodies let a test prove the wiring — the
 * re-prepare carries the same payload, the save carries the question key.
 */
function stubAnswerFlow(overrides?: {
  /** Refuse every save with this status and detail. */
  putRefusal?: { status: number; detail: string }
}) {
  const prepareBodies: unknown[] = []
  const putBodies: unknown[] = []
  const putUrls: string[] = []
  let prepares = 0
  const saved: { visa?: string; auth?: string } = {}

  const blocking = () => [
    ...(saved.visa ? [] : [VISA]),
    ...(saved.auth ? [] : [AUTH]),
  ]

  server.use(
    http.post(`${BASE}/api/applications/prepare`, async ({ request }) => {
      prepareBodies.push(await request.json())
      prepares += 1
      return HttpResponse.json({
        approval_id: `approval-${prepares}`,
        workflow_id: `workflow-${prepares}`,
        adapter_name: "greenhouse",
        status:
          blocking().length > 0 ? "blocked_human_review" : "awaiting_approval",
        form_questions: formQuestions({
          visa: Boolean(saved.visa),
          auth: Boolean(saved.auth),
        }),
        blocking_questions: blocking(),
        prepared_summary: {
          job_title: "AI Engineer",
          company_name: "Figma",
          job_url: "https://boards.greenhouse.io/figma/jobs/1",
          adapter_name: "greenhouse",
          field_names: ["email", "name", "phone"],
          profile_fact_names: ["email", "name"],
          resume_path: null,
          requires_manual_review: false,
        },
        application_id: `application-${prepares}`,
      })
    }),
    http.get(`${BASE}/api/applications/:applicationId/answers`, () =>
      HttpResponse.json({
        // The answers are inherited onto every application a prepare
        // creates for this posting, so every read sees the saved set.
        application_id: "application-any",
        answers: [
          ...(saved.visa
            ? [
                {
                  question_key: VISA_KEY,
                  label: VISA,
                  category: "visa_sponsorship",
                  answer: saved.visa,
                  answered_at: "2026-11-21T10:00:00Z",
                },
              ]
            : []),
          ...(saved.auth
            ? [
                {
                  question_key: AUTH_KEY,
                  label: AUTH,
                  category: "work_authorization",
                  answer: saved.auth,
                  answered_at: "2026-11-21T10:01:00Z",
                },
              ]
            : []),
        ],
      })
    ),
    http.put(
      `${BASE}/api/applications/:applicationId/answers`,
      async ({ request }) => {
        putUrls.push(request.url)
        if (overrides?.putRefusal) {
          return HttpResponse.json(
            { detail: overrides.putRefusal.detail },
            { status: overrides.putRefusal.status }
          )
        }
        const body = (await request.json()) as {
          answers: { question_key: string; label?: string; answer: string }[]
        }
        putBodies.push(body)
        for (const item of body.answers) {
          if (item.question_key === VISA_KEY) saved.visa = item.answer
          if (item.question_key === AUTH_KEY) saved.auth = item.answer
        }
        return HttpResponse.json({
          application_id: "application-any",
          answers: [
            ...(saved.visa
              ? [
                  {
                    question_key: VISA_KEY,
                    label: VISA,
                    category: "visa_sponsorship",
                    answer: saved.visa,
                    answered_at: "2026-11-21T10:00:00Z",
                  },
                ]
              : []),
            ...(saved.auth
              ? [
                  {
                    question_key: AUTH_KEY,
                    label: AUTH,
                    category: "work_authorization",
                    answer: saved.auth,
                    answered_at: "2026-11-21T10:01:00Z",
                  },
                ]
              : []),
          ],
        })
      }
    )
  )

  return { prepareBodies, putBodies, putUrls }
}

describe("the Review screen's answering flow", () => {
  it("surfaces the first unanswered question one at a time, with the design's chips and position", async () => {
    stubAnswerFlow()
    const user = setupUser()
    await prepare(user)

    const card = await screen.findByTestId("question-answer")
    // The visa question is the board's third; the walk opens on the first
    // question the profile cannot answer, in the board's own order.
    expect(within(card).getByText("QUESTION 3 OF 5")).toBeInTheDocument()
    expect(within(card).getByText("Required")).toBeInTheDocument()
    expect(within(card).getByText("3 / 5")).toBeInTheDocument()
    expect(
      within(card).getByText(
        "Will you now or in the future require visa sponsorship for this role?"
      )
    ).toBeInTheDocument()
    // The design's queue chips, on the answering card.
    expect(within(card).getByText("Needs you 2")).toBeInTheDocument()
    expect(within(card).getByText("Confirmed 3")).toBeInTheDocument()
    // The design's helper and the one-at-a-time rule.
    expect(
      within(card).getByText("Choose the answer that is true for you.")
    ).toBeInTheDocument()
    expect(
      within(card).getByText(
        "Each unanswered question appears here, one at a time. Review all before approval."
      )
    ).toBeInTheDocument()
    // The design's footer: back navigation, position, save.
    expect(
      within(card).getByRole("button", { name: "← Previous" })
    ).toBeEnabled()
    expect(
      within(card).getByRole("button", { name: "Save answer →" })
    ).toBeInTheDocument()
    // The save starts disabled: nothing has been answered yet.
    expect(
      within(card).getByRole("button", { name: "Save answer →" })
    ).toBeDisabled()
  })

  it("saves the answer under the prepare response's question key, re-prepares the same payload, and surfaces the next question", async () => {
    const { prepareBodies, putBodies, putUrls } = stubAnswerFlow()
    const user = setupUser()
    await prepare(user)

    const card = await screen.findByTestId("question-answer")
    await user.click(within(card).getByRole("radio", { name: "No" }))
    await user.click(
      within(card).getByRole("button", { name: "Save answer →" })
    )

    // The save went to the tracked application this prepare created, with
    // the key the prepare response handed the console.
    await waitFor(() => expect(putBodies.length).toBe(1))
    expect(putUrls[0]).toContain("/api/applications/application-1/answers")
    expect(putBodies[0]).toEqual({
      answers: [
        {
          question_key: VISA_KEY,
          label: VISA,
          category: "visa_sponsorship",
          answer: "No",
        },
      ],
    })

    // The merge is server-side: saving re-prepares with the **same**
    // payload, so the fresh application inherits the answer and the plan
    // re-merges it.
    await waitFor(() => expect(prepareBodies.length).toBe(2))
    expect(prepareBodies[1]).toEqual(prepareBodies[0])

    // The answered question left the queue; the next one surfaced.
    const next = await screen.findByTestId("question-answer")
    await waitFor(() => {
      expect(within(next).getByText("QUESTION 4 OF 5")).toBeInTheDocument()
    })
    expect(within(next).getByText("Needs you 1")).toBeInTheDocument()
    expect(within(next).getByText("Confirmed 4")).toBeInTheDocument()
    // And the read-only list below names the answered source honestly.
    const list = await screen.findByTestId("board-questions")
    expect(within(list).getByText("answered by you")).toBeInTheDocument()
  })

  it("unlocks the authorize action when blocking_questions empties", async () => {
    stubAnswerFlow()
    const user = setupUser()
    await prepare(user)

    // While a required question is open, approval is locked and the clay
    // panel says what unlocks it.
    await screen.findByTestId("question-answer")
    expect(
      screen.getByText("Confirm the required answer to unlock approval.")
    ).toBeInTheDocument()
    expect(
      screen.getByRole("button", { name: "Approve & continue" })
    ).toBeDisabled()

    // Answer both questions.
    let card = await screen.findByTestId("question-answer")
    await user.click(within(card).getByRole("radio", { name: "No" }))
    await user.click(
      within(card).getByRole("button", { name: "Save answer →" })
    )
    card = await screen.findByTestId("question-answer")
    await waitFor(() => {
      expect(within(card).getByText("QUESTION 4 OF 5")).toBeInTheDocument()
    })
    await user.click(within(card).getByRole("radio", { name: "Yes" }))
    await user.click(
      within(card).getByRole("button", { name: "Save answer →" })
    )

    // The clay panel is replaced by the enabled authorize action.
    await waitFor(() => {
      expect(
        screen.queryByText("Confirm the required answer to unlock approval.")
      ).not.toBeInTheDocument()
    })
    const approve = screen.getByRole("button", { name: "Approve & continue" })
    expect(approve).toBeEnabled()

    // And the unlocked action is the real 202 flow.
    await user.click(approve)
    const dialog = await screen.findByRole("alertdialog")
    await user.click(
      within(dialog).getByRole("button", { name: "Approve & continue" })
    )
    expect(await screen.findByText("Approved — queued")).toBeInTheDocument()
  })

  it("shows the answer already saved for this application, and Previous reaches it", async () => {
    stubAnswerFlow()
    const user = setupUser()
    await prepare(user)

    const card = await screen.findByTestId("question-answer")
    await user.click(within(card).getByRole("radio", { name: "No" }))
    await user.click(
      within(card).getByRole("button", { name: "Save answer →" })
    )

    // After the save and re-prepare, stepping back reaches the answered
    // question, and the answer the server holds is what the control shows.
    await waitFor(() => {
      expect(within(card).getByText("QUESTION 4 OF 5")).toBeInTheDocument()
    })
    await user.click(within(card).getByRole("button", { name: "← Previous" }))
    expect(within(card).getByText("QUESTION 3 OF 5")).toBeInTheDocument()
    expect(within(card).getByRole("radio", { name: "No" })).toBeChecked()
  })

  it("renders a never-autofill question read-only and routes it to the employer site", async () => {
    stubAnswerFlow()
    const user = setupUser()
    await prepare(user)

    // The walk opens on the visa question; stepping back passes the
    // profile-answered question and reaches the demographics question the
    // console must never autofill.
    const card = await screen.findByTestId("question-answer")
    await user.click(within(card).getByRole("button", { name: "← Previous" }))
    expect(within(card).getByText("QUESTION 2 OF 5")).toBeInTheDocument()
    await user.click(within(card).getByRole("button", { name: "← Previous" }))
    expect(within(card).getByText("QUESTION 1 OF 5")).toBeInTheDocument()

    expect(within(card).getByText(EEO)).toBeInTheDocument()
    expect(
      within(card).getByText(
        "Answer on the employer site — this console never autofills it."
      )
    ).toBeInTheDocument()
    // Read-only means no control and no save.
    expect(
      within(card).queryByRole("radio", { name: "Yes" })
    ).not.toBeInTheDocument()
    expect(
      within(card).queryByRole("button", { name: "Save answer →" })
    ).not.toBeInTheDocument()
  })

  it("surfaces the server's refusal of a save word for word", async () => {
    /*
      The laundering case: a question the console cannot classify (category
      `unknown`) that is, in fact, an attestation. The console offers the
      text control its verdict calls for; the server's taxonomy refuses the
      save — and the refusal's own sentence is what the operator reads.
    */
    const DETAIL =
      "Questions in the 'attestation' category are never saved by this system. " +
      "Equal-opportunity (EEO) and legal attestation questions are answered by you " +
      "on the employer's own site, at submission time — policy, not a limitation."
    server.use(
      http.post(`${BASE}/api/applications/prepare`, () =>
        HttpResponse.json({
          approval_id: "approval-1",
          workflow_id: "workflow-1",
          adapter_name: "greenhouse",
          status: "blocked_human_review",
          form_questions: [
            {
              label: "Please confirm your attestation of eligibility",
              required: true,
              block: "questions",
              verdict: "needs_human",
              category: "unknown",
              answer_from: null,
              fields: ["attestation_text"],
              question_key: "please confirm your attestation of eligibility",
            },
          ],
          blocking_questions: [
            "Please confirm your attestation of eligibility",
          ],
          prepared_summary: {
            job_title: "AI Engineer",
            company_name: "Figma",
            job_url: "https://boards.greenhouse.io/figma/jobs/1",
            adapter_name: "greenhouse",
            field_names: ["email", "name", "phone"],
            profile_fact_names: ["email", "name"],
            resume_path: null,
            requires_manual_review: false,
          },
          application_id: "application-1",
        })
      ),
      http.put(`${BASE}/api/applications/:applicationId/answers`, () =>
        HttpResponse.json({ detail: DETAIL }, { status: 422 })
      )
    )
    const user = setupUser()
    await prepare(user)

    const card = await screen.findByTestId("question-answer")
    await user.type(
      within(card).getByLabelText(
        "Please confirm your attestation of eligibility"
      ),
      "I attest"
    )
    await user.click(
      within(card).getByRole("button", { name: "Save answer →" })
    )

    // The server's sentence, verbatim — not a paraphrase of it.
    expect(
      await screen.findByText(/never saved by this system/)
    ).toBeInTheDocument()
    expect(screen.getByText(/policy, not a limitation\./)).toBeInTheDocument()
    // The flow did not advance: the question still stands, unanswered.
    expect(within(card).getByText("QUESTION 1 OF 1")).toBeInTheDocument()
    expect(within(card).getByText("Needs you 1")).toBeInTheDocument()
  })
})
