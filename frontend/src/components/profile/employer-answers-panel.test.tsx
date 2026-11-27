import { QueryClientProvider, useQuery } from "@tanstack/react-query"
import { act, render, screen, waitFor, within } from "@testing-library/react"
import type { ReactNode } from "react"
import { MemoryRouter } from "react-router-dom"
import userEvent from "@testing-library/user-event"
import { http, HttpResponse } from "msw"
import { describe, expect, it } from "vitest"

import { displayAnswer } from "@/components/profile/employer-question-field"
import {
  readPostingPacket,
  type AnswerValue,
  type EmployerAnswer,
  type StoredPostingPacket,
  usePostingForm,
} from "@/lib/api/posting-application"
import { setCurrentProfileId } from "@/lib/profile"
import { createQueryClient } from "@/lib/query-client"
import { ProfileScreen } from "@/screens/profile-screen"
import { identityResponse } from "@/test/factories"
import { server } from "@/test/server"

const BASE = "http://api.test"
const LIBRARY = `${BASE}/api/profiles/employer-answers`
const PROFILE = "/app/profile"
const ANSWERS_TAB = `${PROFILE}?tab=answers`
const SECTION = "Company-specific answers"
const question = "Which work arrangements would suit you?"
const savedAnswer: EmployerAnswer = {
  id: "opaque-answer-7",
  question_key: "a".repeat(64),
  job_id: "greenhouse:31",
  company_name: "Northstar",
  job_title: "Software Engineer",
  updated_at: "2026-10-21T10:00:00Z",
  label: question,
  description: null,
  required: true,
  kind: "multiselect",
  options: [
    { value: "1", label: "Remote" },
    { value: "2", label: "Hybrid" },
    { value: "3", label: "On site" },
  ],
  answer: ["1"],
}

function renderScreen(ui: ReactNode, { route }: { route: string }) {
  const queryClient = createQueryClient()
  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[route]}>{ui}</MemoryRouter>
    </QueryClientProvider>
  )
  return { queryClient }
}

function noResume() {
  setCurrentProfileId(null)
  server.use(
    http.get(`${BASE}/api/documents`, () =>
      HttpResponse.json({ documents: [], count: 0 })
    )
  )
}

function PostingAnswer({ jobId }: { jobId: string }) {
  const form = usePostingForm(jobId)
  const first = form.data?.questions[0]
  return (
    <section aria-label={`Form for ${jobId}`}>
      {form.isSuccess ? (first && displayAnswer(first)) || "Unanswered" : null}
    </section>
  )
}

function PacketStatus() {
  const review = useQuery({
    queryKey: ["posting-review", "packet-1"],
    queryFn: ({ signal }) => readPostingPacket("packet-1", signal),
  })
  return (
    <section aria-label="Prepared packet">
      {review.isSuccess
        ? review.data.review_current
          ? "Current"
          : "Needs review"
        : null}
    </section>
  )
}

describe("Profile’s company-specific answers", () => {
  it("is reachable without a résumé and groups paged answers by company and posting", async () => {
    const user = userEvent.setup()
    noResume()
    const offsets: (string | null)[] = []
    server.use(
      http.get(LIBRARY, ({ request }) => {
        const offset = new URL(request.url).searchParams.get("offset")
        offsets.push(offset)
        if (offset === "0") {
          return HttpResponse.json({ items: [savedAnswer], next_offset: 50 })
        }
        if (offset === "50") {
          return HttpResponse.json({
            items: [
              {
                ...savedAnswer,
                id: "second-answer",
                job_id: "greenhouse:32",
                answer: ["2"],
              },
              {
                ...savedAnswer,
                id: "another-company-answer",
                job_id: "greenhouse:33",
                company_name: "Skylark",
                job_title: "Staff Engineer",
              },
            ],
            next_offset: null,
          })
        }
        return new HttpResponse(null, { status: 400 })
      })
    )

    renderScreen(<ProfileScreen />, { route: PROFILE })
    await screen.findByText("No profile yet")
    await user.click(
      screen.getByRole("button", { name: "Application answers" })
    )
    const library = within(await screen.findByRole("region", { name: SECTION }))
    expect(await library.findByText("Remote")).toBeVisible()
    expect(library.queryByText("Hybrid")).not.toBeInTheDocument()

    await user.click(library.getByRole("button", { name: /load more/i }))
    expect(await library.findByText("Hybrid")).toBeVisible()
    expect(library.getAllByRole("heading", { name: "Northstar" })).toHaveLength(
      1
    )
    expect(
      library.getAllByRole("heading", { name: "Software Engineer" })
    ).toHaveLength(2)
    expect(library.getByRole("heading", { name: "Skylark" })).toBeVisible()
    expect(
      library.getAllByRole("link").map((link) => link.getAttribute("href"))
    ).toEqual([
      "/app/matches/greenhouse%3A31/prepare",
      "/app/matches/greenhouse%3A32/prepare",
      "/app/matches/greenhouse%3A33/prepare",
    ])
    expect(
      library.queryByRole("button", { name: /load more/i })
    ).not.toBeInTheDocument()
    expect(offsets).toEqual(["0", "50"])
  })

  it("belongs to the Application answers tab when a résumé is available", async () => {
    const user = userEvent.setup()
    setCurrentProfileId("profile-1")
    server.use(
      http.get(LIBRARY, () =>
        HttpResponse.json({ items: [], next_offset: null })
      )
    )
    renderScreen(<ProfileScreen />, { route: PROFILE })

    await screen.findByRole("heading", {
      name: "Your original stays original.",
    })
    expect(
      screen.queryByRole("heading", { name: SECTION })
    ).not.toBeInTheDocument()
    await user.click(screen.getByRole("tab", { name: "Application answers" }))
    const panel = await screen.findByRole("tabpanel", {
      name: "Application answers",
    })
    expect(
      within(panel).getByRole("heading", { name: SECTION })
    ).toBeInTheDocument()
  })

  it("can retry a failed library read from the answers deep link", async () => {
    const user = userEvent.setup()
    noResume()
    let reads = 0
    server.use(
      http.get(LIBRARY, () =>
        ++reads === 1
          ? HttpResponse.json(
              { detail: "The library is not available yet." },
              { status: 403 }
            )
          : HttpResponse.json({ items: [], next_offset: null })
      )
    )
    renderScreen(<ProfileScreen />, { route: ANSWERS_TAB })

    const library = within(await screen.findByRole("region", { name: SECTION }))
    expect(await library.findByRole("alert")).toHaveTextContent(
      "The library is not available yet."
    )
    expect(
      library.queryByText(/no company-specific answers yet/i)
    ).not.toBeInTheDocument()
    await user.click(library.getByRole("button", { name: "Try again" }))
    expect(
      await library.findByText(/no company-specific answers yet/i)
    ).toBeVisible()
  })

  it("does not show the previous account’s answers while loading another account", async () => {
    noResume()
    let account = identityResponse()
    let finishSecondRead = () => {}
    const secondRead = new Promise<void>((resolve) => {
      finishSecondRead = resolve
    })
    server.use(
      http.get(`${BASE}/api/auth/me`, () => HttpResponse.json(account)),
      http.get(LIBRARY, async () => {
        if (account.id === "user-2") {
          await secondRead
          return HttpResponse.json({ items: [], next_offset: null })
        }
        return HttpResponse.json({ items: [savedAnswer], next_offset: null })
      })
    )
    const { queryClient } = renderScreen(<ProfileScreen />, {
      route: ANSWERS_TAB,
    })
    const library = within(await screen.findByRole("region", { name: SECTION }))
    expect(await library.findByText("Remote")).toBeVisible()

    account = { ...account, id: "user-2" }
    await act(async () => {
      await queryClient.invalidateQueries({ queryKey: ["identity"] })
    })
    try {
      // Wait for the second identity's render, not just the settled HTTP request.
      // The pending second answer read must never show the first account's data.
      expect(
        await library.findByText(/loading company-specific answers/i)
      ).toBeVisible()
      expect(library.queryByText("Remote")).not.toBeInTheDocument()
    } finally {
      finishSecondRead()
    }
    expect(
      await library.findByText(/no company-specific answers yet/i)
    ).toBeVisible()
  })

  it("validates a typed edit and refreshes only the affected posting form after saving", async () => {
    const user = userEvent.setup()
    noResume()
    const otherJob = "greenhouse:32"
    let item = savedAnswer
    let allowSave = false
    const writes: unknown[] = []
    const formReads: string[] = []
    server.use(
      http.get(LIBRARY, () =>
        HttpResponse.json({ items: [item], next_offset: null })
      ),
      http.put(`${LIBRARY}/${savedAnswer.id}`, async ({ request }) => {
        const body = (await request.json()) as { answer: AnswerValue }
        writes.push(body)
        if (!allowSave) {
          return HttpResponse.json(
            { detail: "Please check the selected answers." },
            { status: 422 }
          )
        }
        item = { ...item, answer: body.answer }
        return HttpResponse.json(item)
      }),
      http.get(`${BASE}/api/jobs/:jobId/application-form`, ({ params }) => {
        const jobId = String(params.jobId)
        formReads.push(jobId)
        return HttpResponse.json({
          state: "available",
          questions: [
            { ...item, answer: jobId === otherJob ? ["3"] : item.answer },
          ],
        })
      })
    )
    renderScreen(
      <>
        <ProfileScreen />
        <PostingAnswer jobId={savedAnswer.job_id} />
        <PostingAnswer jobId={otherJob} />
      </>,
      { route: ANSWERS_TAB }
    )

    const posting = within(
      screen.getByRole("region", { name: "Form for greenhouse:31" })
    )
    await posting.findByText("Remote")
    const otherPosting = within(
      screen.getByRole("region", { name: "Form for greenhouse:32" })
    )
    await otherPosting.findByText("On site")
    const library = within(await screen.findByRole("region", { name: SECTION }))
    await user.click(
      await library.findByRole("button", { name: /^edit answer/i })
    )
    const editor = within(await screen.findByRole("dialog"))

    await user.click(editor.getByRole("checkbox", { name: "Remote" }))
    await user.click(editor.getByRole("button", { name: /save answer/i }))
    expect(editor.getByRole("alert")).toHaveTextContent(/select at least one/i)
    expect(writes).toEqual([])

    await user.click(editor.getByRole("checkbox", { name: "Hybrid" }))
    await user.click(editor.getByRole("button", { name: /save answer/i }))
    expect(await editor.findByRole("alert")).toHaveTextContent(
      "Please check the selected answers."
    )
    expect(editor.getByRole("checkbox", { name: "Hybrid" })).toBeChecked()

    allowSave = true
    await user.click(editor.getByRole("button", { name: /save answer/i }))
    await waitFor(() =>
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument()
    )
    expect(await library.findByText("Hybrid")).toBeVisible()
    expect(await posting.findByText("Hybrid")).toBeVisible()
    expect(otherPosting.getByText("On site")).toBeVisible()
    expect(formReads.filter((jobId) => jobId === otherJob)).toHaveLength(1)
    expect(writes).toEqual([{ answer: ["2"] }, { answer: ["2"] }])
  })

  it("deletes only the confirmed saved answer and updates its posting form", async () => {
    const user = userEvent.setup()
    noResume()
    let deleted = false
    const packet: StoredPostingPacket = {
      job_id: savedAnswer.job_id,
      job_title: savedAnswer.job_title,
      company_name: savedAnswer.company_name,
      job_url: "https://example.com/jobs/31",
      application_id: "packet-1",
      approval_id: "approval-1",
      blocking_questions: [],
      prepared_summary: {
        document_id: "resume-1",
        document_filename: "resume.pdf",
      },
      posting_form: { state: "available", questions: [savedAnswer] },
      on_employer_site: [],
      contact: {
        candidate_name: "Ada Lovelace",
        email: "ada@example.com",
        phone: "",
      },
      document_current: true,
      review_current: true,
    }
    server.use(
      http.get(`${BASE}/api/applications/packet-1/posting-review`, () =>
        HttpResponse.json({ ...packet, review_current: !deleted })
      ),
      http.get(LIBRARY, () =>
        HttpResponse.json({
          items: deleted ? [] : [savedAnswer],
          next_offset: null,
        })
      ),
      http.delete(`${LIBRARY}/${savedAnswer.id}`, () => {
        deleted = true
        return new HttpResponse(null, { status: 204 })
      }),
      http.get(`${BASE}/api/jobs/greenhouse%3A31/application-form`, () =>
        HttpResponse.json({
          state: "available",
          questions: [
            { ...savedAnswer, answer: deleted ? null : savedAnswer.answer },
          ],
        })
      )
    )
    renderScreen(
      <>
        <ProfileScreen />
        <PostingAnswer jobId={savedAnswer.job_id} />
        <PacketStatus />
      </>,
      { route: ANSWERS_TAB }
    )

    const review = within(
      screen.getByRole("region", { name: "Prepared packet" })
    )
    await review.findByText("Current")
    const posting = within(
      screen.getByRole("region", { name: "Form for greenhouse:31" })
    )
    await posting.findByText("Remote")
    const library = within(await screen.findByRole("region", { name: SECTION }))
    const deleteButton = await library.findByRole("button", {
      name: /^delete answer/i,
    })
    await user.click(deleteButton)
    const dialog = await screen.findByRole("alertdialog")
    expect(dialog).toHaveAccessibleDescription(/Software Engineer at Northstar/)
    await user.click(within(dialog).getByRole("button", { name: "Cancel" }))
    await waitFor(() =>
      expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument()
    )
    expect(deleted).toBe(false)
    expect(library.getByText("Remote")).toBeVisible()

    await user.click(deleteButton)
    await user.click(
      within(await screen.findByRole("alertdialog")).getByRole("button", {
        name: "Delete answer",
      })
    )
    expect(
      await library.findByText(/no company-specific answers yet/i)
    ).toBeVisible()
    expect(await posting.findByText("Unanswered")).toBeVisible()
    expect(await review.findByText("Needs review")).toBeVisible()
  })
})
