import { screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { http, HttpResponse } from "msw"
import { describe, expect, it, vi } from "vitest"

import { server } from "@/test/server"
import { renderApp } from "@/test/render"
import { approvalDecision } from "@/test/factories"

const BASE = "http://api.test"

async function fillPrepareForm(user: ReturnType<typeof userEvent.setup>) {
  await user.type(screen.getByLabelText("Job title"), "AI Engineer")
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
    const user = userEvent.setup()
    renderApp({ route: "/approvals" })

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
    const user = userEvent.setup()
    renderApp({ route: "/approvals" })

    await user.type(screen.getByLabelText("Job title"), "AI Engineer")
    await user.click(
      screen.getByRole("button", { name: "Prepare application" })
    )

    expect(
      await screen.findByText("The company name is required")
    ).toBeInTheDocument()
    expect(screen.queryByText("What will be submitted")).not.toBeInTheDocument()
  })

  it("requires the approver's name before it can approve", async () => {
    const user = userEvent.setup()
    renderApp({ route: "/approvals" })

    await fillPrepareForm(user)
    await user.click(
      screen.getByRole("button", { name: "Prepare application" })
    )
    await screen.findByText("What will be submitted")

    await user.click(screen.getByRole("button", { name: "Approve and submit" }))

    expect(
      await screen.findByText("The approver's name is required")
    ).toBeInTheDocument()
  })

  it("approves with the approver's identity and shows the evidence", async () => {
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
    const user = userEvent.setup()
    renderApp({ route: "/approvals" })

    await fillPrepareForm(user)
    await user.click(
      screen.getByRole("button", { name: "Prepare application" })
    )
    await screen.findByText("What will be submitted")

    await user.type(screen.getByLabelText("Approver"), "Ada")
    await user.type(screen.getByLabelText("Reason"), "Looks right")
    await user.click(screen.getByRole("button", { name: "Approve and submit" }))

    expect(await screen.findByText("The decision")).toBeInTheDocument()
    expect(sentBody).toEqual({ approver: "Ada", reason: "Looks right" })
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
    const user = userEvent.setup()
    renderApp({ route: "/approvals" })

    await fillPrepareForm(user)
    await user.click(
      screen.getByRole("button", { name: "Prepare application" })
    )
    await screen.findByText("What will be submitted")

    await user.type(screen.getByLabelText("Approver"), "Ada")
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
    const user = userEvent.setup()
    renderApp({ route: "/approvals" })

    await fillPrepareForm(user)
    await user.click(
      screen.getByRole("button", { name: "Prepare application" })
    )
    await screen.findByText("What will be submitted")

    await user.type(screen.getByLabelText("Approver"), "Ada")
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
    const user = userEvent.setup()
    renderApp({ route: "/approvals" })

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
