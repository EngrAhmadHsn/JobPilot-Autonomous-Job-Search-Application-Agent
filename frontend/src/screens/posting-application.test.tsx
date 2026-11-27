import { screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { http, HttpResponse } from "msw"
import { describe, expect, it } from "vitest"

import type {
  AnswerValue,
  FormState,
  PostingForm,
  PostingQuestion,
  StoredPostingPacket,
} from "@/lib/api/posting-application"
import type { DocumentRecord } from "@/lib/api/types"
import { setCurrentProfileId } from "@/lib/profile"
import { jobListing } from "@/test/factories"
import { renderApp } from "@/test/render"
import { server } from "@/test/server"

const BASE = "http://api.test"
const POSTING = "/app/matches/greenhouse%3A1"
const PREPARE = `${POSTING}/prepare`
const REVIEW = "/app/tracker/application-1/review"
const EMPLOYER = "https://job-boards.greenhouse.io/northstar/jobs/1"
const WHY = "Why do you want to work at Northstar?"
const PARTNER = "Have you worked with a Northstar partner?"
const AREAS = "Which areas have you worked in?"
const WHY_ANSWER = "I want to work on the role."
const whyKey = "a".repeat(64)
const partnerKey = "b".repeat(64)
const areasKey = "c".repeat(64)

const questions: PostingQuestion[] = [
  {
    question_key: whyKey,
    label: WHY,
    kind: "textarea",
    required: true,
    description: "Please give a specific example.",
    options: [],
    answer: null,
  },
  {
    question_key: partnerKey,
    label: PARTNER,
    kind: "select",
    required: true,
    options: [
      { value: "1", label: "Yes" },
      { value: "2", label: "No" },
    ],
    answer: null,
  },
  {
    question_key: areasKey,
    label: AREAS,
    kind: "multiselect",
    required: true,
    options: [
      { value: "3", label: "Backend" },
      { value: "4", label: "Frontend" },
    ],
    answer: null,
  },
  {
    question_key: "d".repeat(64),
    label: "Consent to processing",
    kind: "employer",
    required: true,
    options: [],
    answer: null,
  },
]

const original: DocumentRecord = {
  id: "profile-profile-1",
  kind: "resume",
  title: "My uploaded résumé",
  filename: "resume.pdf",
  size_bytes: 100,
  profile_id: "profile-1",
  path: "data/resumes/resume.pdf",
  created_at: null,
  job_id: null,
}

function setPostingHandlers({
  states = ["available"],
  documents = [original],
}: { states?: FormState[]; documents?: DocumentRecord[] } = {}) {
  let rows = questions
  let reads = 0
  const saved: unknown[] = []
  server.use(
    http.get(`${BASE}/api/jobs/:jobId`, () =>
      HttpResponse.json({
        job: jobListing({ company: "Northstar", application_url: EMPLOYER }),
      })
    ),
    http.get(`${BASE}/api/jobs/:jobId/application-form`, () => {
      const state = states[Math.min(reads++, states.length - 1)]
      return HttpResponse.json({
        state,
        questions: state === "available" ? rows : [],
      })
    }),
    http.put(
      `${BASE}/api/jobs/:jobId/application-form/answers`,
      async ({ request }) => {
        const body = (await request.json()) as {
          answers: { question_key: string; answer: AnswerValue }[]
        }
        saved.push(body)
        rows = rows.map((q) => ({
          ...q,
          answer:
            body.answers.find((a) => a.question_key === q.question_key)
              ?.answer ?? q.answer,
        }))
        return HttpResponse.json({
          state: "available",
          questions: rows,
        } satisfies PostingForm)
      }
    ),
    http.get(`${BASE}/api/documents`, () =>
      HttpResponse.json({ documents, count: documents.length })
    )
  )
  return { saved, formReads: () => reads }
}

const contact = {
  candidate_name: "Ada Lovelace",
  email: "ada@example.com",
  phone: "+44 20 7946 0000",
}
const summary = {
  job_title: "AI Engineer",
  company_name: "Northstar",
  job_url: EMPLOYER,
  adapter_name: "manual-handoff",
  field_names: ["candidate_name", "email", "phone", "resume"],
  profile_fact_names: [],
  resume_path: null,
  requires_manual_review: true,
  document_id: original.id,
  document_filename: original.filename,
}

function prepareResult(form: PostingForm, blockers: string[] = []) {
  return {
    approval_id: "approval-1",
    application_id: "application-1",
    workflow_id: "workflow-1",
    adapter_name: "manual-handoff",
    status: blockers.length ? "blocked_human_review" : "prepared",
    form_questions: [],
    blocking_questions: blockers,
    prepared_summary: summary,
    posting_form: form,
    on_employer_site:
      form.state === "available" ? ["Consent to processing"] : [],
  }
}

function setStoredReview(overrides: Partial<StoredPostingPacket> = {}) {
  server.use(
    http.get(`${BASE}/api/applications/application-1/posting-review`, () =>
      HttpResponse.json({
        ...prepareResult({
          state: "available",
          questions: questions.map((q) => ({
            ...q,
            answer:
              q.question_key === whyKey
                ? WHY_ANSWER
                : q.question_key === partnerKey
                  ? "2"
                  : q.question_key === areasKey
                    ? ["3", "4"]
                    : null,
          })),
        }),
        job_id: "greenhouse:1",
        job_title: "AI Engineer",
        company_name: "Northstar",
        job_url: EMPLOYER,
        document_current: true,
        review_current: true,
        contact,
        ...overrides,
      } satisfies StoredPostingPacket)
    )
  )
}

describe("job-first preparation", () => {
  it("shows the employer's questions by default and opens the form directly, not Tailoring", async () => {
    const user = userEvent.setup()
    const { formReads } = setPostingHandlers()
    const { router } = renderApp({ route: POSTING })
    expect(await screen.findByText(WHY)).toBeVisible()
    expect(screen.getByText(/3 required answers not saved/i)).toBeVisible()
    expect(
      screen.getByRole("link", { name: /tailor for this role/i })
    ).toBeVisible()
    await user.click(
      screen.getByRole("link", { name: /^prepare application/i })
    )
    expect(router.state.location.pathname).toBe(PREPARE)
    expect(await screen.findByRole("textbox", { name: WHY })).toBeVisible()
    expect(formReads()).toBe(1)
  })

  it("opens the employer-question editor from Discover even without a match", async () => {
    const user = userEvent.setup()
    setCurrentProfileId("profile-1")
    setPostingHandlers()
    server.use(
      http.get(`${BASE}/api/profiles/:id/matches`, () =>
        HttpResponse.json({ profile_id: "profile-1", matches: [] })
      )
    )
    const { router } = renderApp({ route: "/app/matches?job=greenhouse%3A1" })
    const detail = within(
      await screen.findByRole("region", { name: "The selected job" })
    )
    expect(await detail.findByText("Not matched yet")).toBeVisible()
    expect(
      detail.getByRole("link", { name: "Prepare application" })
    ).toHaveAttribute("href", PREPARE)
    expect(await detail.findByText(WHY)).toBeVisible()
    expect(
      detail.getByRole("link", { name: /open original listing/i })
    ).toHaveAttribute("href", EMPLOYER)
    await user.click(
      detail.getByRole("link", { name: "Open employer questions" })
    )
    expect(router.state.location.hash).toBe("#employer-questions")
    expect(await screen.findByRole("textbox", { name: WHY })).toBeVisible()
    expect(
      screen.getByRole("heading", { name: "Employer questions" })
    ).toHaveFocus()
  })

  it("saves the employer's answers with real textarea, select, and multi-select controls", async () => {
    const user = userEvent.setup()
    const { saved } = setPostingHandlers()
    renderApp({ route: PREPARE })
    const answer = await screen.findByRole("textbox", { name: WHY })
    expect(answer.tagName).toBe("TEXTAREA")
    expect(answer).toHaveAccessibleDescription(
      "Please give a specific example."
    )
    await user.type(answer, WHY_ANSWER)
    await user.selectOptions(
      screen.getByRole("combobox", { name: PARTNER }),
      "2"
    )
    await user.click(screen.getByRole("checkbox", { name: "Backend" }))
    await user.click(screen.getByRole("checkbox", { name: "Frontend" }))
    expect(
      screen.queryByRole("textbox", { name: "Consent to processing" })
    ).not.toBeInTheDocument()
    expect(screen.getByText("Consent to processing")).toBeVisible()
    const save = screen.getByRole("button", { name: "Save answers" })
    expect(save.closest("form")).toContainElement(answer)
    await user.click(save)
    expect(await screen.findByText(/saved to your profile/i)).toBeVisible()
    expect(saved).toEqual([
      {
        answers: [
          { question_key: whyKey, answer: WHY_ANSWER },
          { question_key: partnerKey, answer: "2" },
          { question_key: areasKey, answer: ["3", "4"] },
        ],
      },
    ])
  })

  it("retries an unavailable read without discarding the chosen contact details", async () => {
    const user = userEvent.setup()
    const { formReads } = setPostingHandlers({
      states: ["unavailable", "available"],
    })
    renderApp({ route: PREPARE })
    expect(
      await screen.findByText(/could not read the employer.s questions/i)
    ).toBeVisible()
    const name = screen.getByRole("textbox", { name: "Full name" })
    expect(await screen.findByDisplayValue(contact.candidate_name)).toBe(name)
    await user.clear(name)
    await user.type(name, "Ada Byron")
    await user.click(
      screen.getByRole("button", { name: "Retry employer questions" })
    )
    expect(await screen.findByRole("textbox", { name: WHY })).toBeVisible()
    expect(name).toHaveValue("Ada Byron")
    expect(formReads()).toBe(2)
  })

  it("takes the default original document straight to review without asking for a model key", async () => {
    const user = userEvent.setup()
    setPostingHandlers({ states: ["unavailable"] })
    let body: unknown
    server.use(
      http.post(`${BASE}/api/applications/prepare`, async ({ request }) => {
        body = await request.json()
        return HttpResponse.json(
          prepareResult({ state: "unavailable", questions: [] })
        )
      })
    )
    renderApp({ route: PREPARE })
    expect(
      await screen.findByText(/could not read the employer.s questions/i)
    ).toBeVisible()
    const résumé = await screen.findByRole("combobox", { name: "Résumé" })
    await waitFor(() => expect(résumé).toHaveValue(original.id))
    const name = screen.getByRole("textbox", { name: "Full name" })
    const email = screen.getByRole("textbox", { name: "Email" })
    expect(await screen.findByDisplayValue(contact.candidate_name)).toBe(name)
    await user.clear(name)
    await user.type(name, "Ada Byron")
    await user.clear(email)
    await user.type(email, "ada.byron@example.com")
    await user.click(screen.getByRole("button", { name: "Prepare for review" }))
    expect(
      await screen.findByRole("heading", { name: "Ready for your review" })
    ).toBeVisible()
    expect(body).toEqual({
      job_id: "greenhouse:1",
      job_title: "AI Engineer",
      company_name: "Northstar",
      job_url: EMPLOYER,
      document_id: original.id,
      candidate_name: "Ada Byron",
      email: "ada.byron@example.com",
      phone: contact.phone,
    })
    expect(
      screen.getByRole("link", { name: /open employer site/i })
    ).toHaveAttribute("href", EMPLOYER)
    expect(
      screen.getByText(/nothing has been filled in or submitted/i)
    ).toBeVisible()
  })

  it("only offers same-posting tailored documents and respects an explicit draft link", async () => {
    const suggested: DocumentRecord = {
      ...original,
      id: "tailored-draft-1",
      kind: "tailored",
      filename: "northstar.docx",
      job_id: "greenhouse:1",
    }
    setPostingHandlers({
      documents: [
        {
          ...suggested,
          id: "tailored-other",
          filename: "other.docx",
          job_id: "greenhouse:2",
        },
        suggested,
        original,
      ],
    })
    renderApp({ route: `${PREPARE}?draft=draft-1` })
    const picker = await screen.findByRole("combobox", { name: "Résumé" })
    await waitFor(() => expect(picker).toHaveValue(suggested.id))
    expect(
      within(picker).queryByRole("option", { name: /other\.docx/i })
    ).not.toBeInTheDocument()
    expect(
      within(picker).getByRole("option", { name: /resume\.pdf/i })
    ).toBeInTheDocument()
  })

  it("shows a blocked packet without saying it is ready", async () => {
    const user = userEvent.setup()
    setPostingHandlers()
    server.use(
      http.post(`${BASE}/api/applications/prepare`, () =>
        HttpResponse.json(
          prepareResult({ state: "available", questions }, [WHY])
        )
      )
    )
    renderApp({ route: PREPARE })
    await screen.findByDisplayValue(contact.candidate_name)
    await screen.findByRole("textbox", { name: WHY })
    await user.click(screen.getByRole("button", { name: "Prepare for review" }))
    expect(
      await screen.findByRole("heading", {
        name: /required answers still missing/i,
      })
    ).toBeVisible()
    expect(screen.getByText(WHY)).toBeVisible()
    expect(
      screen.queryByRole("heading", { name: "Ready for your review" })
    ).not.toBeInTheDocument()
    expect(
      screen.getByRole("button", { name: "Edit preparation" })
    ).toBeVisible()
  })

  it("rehydrates a stored review with human-readable, copyable answers and a document link", async () => {
    const user = userEvent.setup()
    setStoredReview()
    renderApp({ route: REVIEW })
    expect(
      await screen.findByRole("heading", { name: "Ready for your review" })
    ).toBeVisible()
    expect(screen.getByText(contact.email)).toBeVisible()
    expect(screen.getByText("Consent to processing")).toBeVisible()
    expect(
      screen.getByRole("link", { name: /download.*resume\.pdf/i })
    ).toHaveAttribute(
      "href",
      `${BASE}/api/documents/profile-profile-1/download`
    )
    await user.click(
      screen.getByRole("button", { name: `Copy answer for ${AREAS}` })
    )
    expect(await navigator.clipboard.readText()).toBe("Backend, Frontend")
    expect(
      screen.getByRole("link", { name: "Edit preparation" })
    ).toHaveAttribute("href", PREPARE)
    expect(
      screen.getByRole("link", { name: /back to posting/i })
    ).toHaveAttribute("href", POSTING)
  })

  it("does not offer handoff or the old download if a saved review no longer reflects the document or answers", async () => {
    setStoredReview({ document_current: false, review_current: false })
    renderApp({ route: REVIEW })
    expect(
      await screen.findByText(/résumé has changed or is no longer available/i)
    ).toBeVisible()
    expect(screen.getByText(/saved answers have changed/i)).toBeVisible()
    expect(
      screen.queryByRole("link", { name: /open employer site|download/i })
    ).not.toBeInTheDocument()
    expect(
      screen.queryByRole("heading", { name: "Ready for your review" })
    ).not.toBeInTheDocument()
    expect(screen.getByRole("link", { name: "Edit preparation" })).toBeVisible()
  })
})
