import { screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { http, HttpResponse } from "msw"
import { expect, it } from "vitest"

import { renderApp } from "@/test/render"
import { server } from "@/test/server"

it("requires an explicit fill-only decision before showing local autofill instructions", async () => {
  const user = userEvent.setup()
  let authorizations = 0
  server.use(
    http.get("http://api.test/api/applications/review-1/posting-review", () =>
      HttpResponse.json({
        application_id: "review-1",
        approval_id: "approval-1",
        job_id: "greenhouse:1",
        job_title: "Research engineer",
        company_name: "Acme",
        job_url: "https://job-boards.greenhouse.io/acme/jobs/1",
        prepared_summary: {
          document_id: "profile-1",
          document_filename: "original.pdf",
        },
        posting_form: { state: "available", questions: [] },
        on_employer_site: [],
        blocking_questions: [],
        contact: {
          candidate_name: "Ada Byron",
          email: "ada@example.com",
          phone: "",
        },
        document_current: true,
        review_current: true,
        assist_available: true,
      })
    ),
    http.post(
      "http://api.test/api/applications/review-1/authorize-fill",
      async ({ request }) => {
        authorizations++
        expect(await request.json()).toEqual({ purpose: "fill_only" })
        return HttpResponse.json({
          code: "one-time-test-code",
          expires_at: "2099-01-01T12:00:00Z",
        })
      }
    )
  )
  renderApp({ route: "/app/tracker/review-1/review" })
  await user.click(
    await screen.findByRole("button", { name: /assisted autofill/i })
  )
  const confirmation = within(screen.getByRole("alertdialog"))
  expect(authorizations).toBe(0)
  await user.click(
    confirmation.getByRole("button", { name: /authorize fill only/i })
  )
  expect(await screen.findByText("one-time-test-code")).toBeVisible()
  expect(screen.getByText(/python.exe -m scripts.fill_review/)).toBeVisible()
  expect(authorizations).toBe(1)
  expect(
    screen.getByRole("link", { name: /open employer site/i })
  ).toBeVisible()
})
