import { screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { http, HttpResponse } from "msw"
import { describe, expect, it, vi } from "vitest"

import { server } from "@/test/server"
import { renderApp } from "@/test/render"
import { approvalDecision } from "@/test/factories"

const BASE = "http://api.test"

/**
 * A user that does not wait between keystrokes.
 *
 * `userEvent.setup()` advances a real timer per key by default, and this
 * form has ~80 characters across six fields: the five-second per-test budget
 * is spent waiting on the keyboard, not on the screen. Nothing here debounces
 * or observes typing cadence, so `delay: null` types the same string into the
 * same fields and only removes the wall-clock cost — measured, the first test
 * went from 5.1 s to well inside its budget.
 */
function setupUser() {
  return userEvent.setup({ delay: null })
}

async function fillPrepareForm(user: ReturnType<typeof userEvent.setup>) {
  /*
    Every console screen is lazily loaded now, so the form arrives a microtask
    after the route mounts. Waiting for the first field is what makes this
    helper work for every caller: once it resolves, the chunk has loaded and
    the remaining fields are present synchronously.
  */
  await user.type(await screen.findByLabelText("Job title"), "AI Engineer")
  await user.type(screen.getByLabelText("Company"), "Acme")
  await user.type(
    screen.getByLabelText("Job URL"),
    "http://127.0.0.1:8901/basic"
  )
  await user.type(screen.getByLabelText("Candidate name"), "Ada Lovelace")
  await user.type(screen.getByLabelText("Email"), "ada@example.com")
  await user.type(screen.getByLabelText("Phone"), "+44 20 7946 0000")
}

describe("the approvals screen", () => {
  it("prepares an application and shows what would be submitted", async () => {
    const user = setupUser()
    renderApp({ route: "/app/approvals" })

    await fillPrepareForm(user)
    await user.click(
      screen.getByRole("button", { name: "Prepare application" })
    )

    expect(
      await screen.findByText("What will be submitted")
    ).toBeInTheDocument()
    expect(
      screen.getByText(/Nothing has been submitted yet/)
    ).toBeInTheDocument()
    expect(screen.getAllByText("email, name, phone").length).toBeGreaterThan(0)
    expect(screen.getByText("approval-1")).toBeInTheDocument()
  })

  it("refuses to prepare an application with a missing field", async () => {
    const user = setupUser()
    renderApp({ route: "/app/approvals" })

    // The route is a lazy chunk, so the first field is what proves the chunk
    // arrived. A synchronous `getByLabelText` here read an empty body
    // whenever the chunk lost the race — which, under the whole suite's
    // parallel load, it intermittently did.
    await user.type(await screen.findByLabelText("Job title"), "AI Engineer")
    await user.click(
      screen.getByRole("button", { name: "Prepare application" })
    )

    expect(
      await screen.findByText("The company name is required")
    ).toBeInTheDocument()
    expect(screen.queryByText("What will be submitted")).not.toBeInTheDocument()
  })

  it("does not ask for an approver name, and says who decides", async () => {
    // WS-14: the approver is the authenticated principal. Asking the
    // operator for a name would collect a value the server ignores.
    const user = setupUser()
    renderApp({ route: "/app/approvals" })

    await fillPrepareForm(user)
    await user.click(
      screen.getByRole("button", { name: "Prepare application" })
    )
    await screen.findByText("What will be submitted")

    expect(screen.queryByLabelText("Approver")).not.toBeInTheDocument()
    expect(
      screen.getByText(/recorded against your account/i)
    ).toBeInTheDocument()
  })

  it("approves without naming an approver and shows the evidence", async () => {
    let sentBody: unknown = null
    server.use(
      http.post(
        `${BASE}/api/applications/:approvalId/approve`,
        async ({ request }) => {
          sentBody = await request.json()
          return HttpResponse.json(approvalDecision())
        }
      )
    )
    const user = setupUser()
    renderApp({ route: "/app/approvals" })

    await fillPrepareForm(user)
    await user.click(
      screen.getByRole("button", { name: "Prepare application" })
    )
    await screen.findByText("What will be submitted")

    await user.type(screen.getByLabelText("Reason"), "Looks right")
    await user.click(screen.getByRole("button", { name: "Approve and submit" }))

    expect(await screen.findByText("The decision")).toBeInTheDocument()
    // The decision carries the reason only; the server attributes it to
    // the authenticated principal.
    expect(sentBody).toEqual({ reason: "Looks right" })
    expect(screen.getByText("Application submitted")).toBeInTheDocument()
  })

  it("shows the unanswered questions of a needs_human result", async () => {
    server.use(
      http.post(`${BASE}/api/applications/:approvalId/approve`, () =>
        HttpResponse.json(
          approvalDecision({
            success: false,
            status: "needs_human",
            message:
              "The form asks 1 question(s) the candidate's evidence does not answer: Years of experience.",
            evidence: null,
            metadata: { questions: ["Years of experience"] },
          })
        )
      )
    )
    const user = setupUser()
    renderApp({ route: "/app/approvals" })

    await fillPrepareForm(user)
    await user.click(
      screen.getByRole("button", { name: "Prepare application" })
    )
    await screen.findByText("What will be submitted")

    await user.click(screen.getByRole("button", { name: "Approve and submit" }))

    expect(
      await screen.findByText(
        "The form asked questions the evidence does not answer"
      )
    ).toBeInTheDocument()
    expect(screen.getByText("Years of experience")).toBeInTheDocument()
    expect(screen.getByText("Needs a human answer")).toBeInTheDocument()
  })

  it("rejects without submitting anything", async () => {
    const reject = vi.fn()
    server.use(
      http.post(`${BASE}/api/applications/:approvalId/reject`, async () => {
        reject()
        return HttpResponse.json(
          approvalDecision({
            success: false,
            status: "rejected",
            message: "Not this one",
            evidence: null,
          })
        )
      })
    )
    const user = setupUser()
    renderApp({ route: "/app/approvals" })

    await fillPrepareForm(user)
    await user.click(
      screen.getByRole("button", { name: "Prepare application" })
    )
    await screen.findByText("What will be submitted")

    await user.click(screen.getByRole("button", { name: "Reject" }))

    await waitFor(() => {
      expect(reject).toHaveBeenCalled()
    })
    expect(screen.getByText("Rejected")).toBeInTheDocument()
  })

  it("shows the server's refusal of a prepare", async () => {
    server.use(
      http.post(`${BASE}/api/applications/prepare`, () =>
        HttpResponse.json(
          { detail: "Host 'example.com' is not on the domain allowlist" },
          { status: 400 }
        )
      )
    )
    const user = setupUser()
    renderApp({ route: "/app/approvals" })

    await fillPrepareForm(user)
    await user.click(
      screen.getByRole("button", { name: "Prepare application" })
    )

    expect(
      await screen.findByText(
        "Host 'example.com' is not on the domain allowlist"
      )
    ).toBeInTheDocument()
  })
})
