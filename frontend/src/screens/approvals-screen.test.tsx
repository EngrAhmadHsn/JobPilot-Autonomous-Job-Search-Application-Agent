import { screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { http, HttpResponse } from "msw"
import { describe, expect, it, vi } from "vitest"

import { server } from "@/test/server"
import { renderApp } from "@/test/render"
import { approvalDecision } from "@/test/factories"

const BASE = "http://api.test"

/**
 * The approvals screen: the human-approval boundary (WS-38).
 *
 * The properties pinned here are the ones the product's safety case rests
 * on:
 *
 * - the primary action says **Approve & continue** and its confirmation
 *   states the queued consequence — the route answers `202` with a run id,
 *   so nothing may say "submit" before a run reports a submission;
 * - the approve request goes to **the approval id the screen displays**,
 *   so the payload a human inspects is the payload that gets approved;
 * - a decision cannot be sent twice — the action is replaced once recorded
 *   and the confirmation is disabled while in flight;
 * - the decision survives a reload, because it is re-read from the
 *   `GET /api/applications/approvals/{id}` route, not from memory;
 * - a refusal names its real state (expired, already decided, profile
 *   changed) with the way back, never a fabricated recovery.
 */

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

async function prepare(user: ReturnType<typeof userEvent.setup>) {
  await fillPrepareForm(user)
  await user.click(screen.getByRole("button", { name: "Prepare application" }))
  await screen.findByText("What will be submitted")
}

/** The two clicks an approve decision takes: open the dialog, confirm it. */
async function approveThroughDialog(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole("button", { name: "Approve & continue" }))
  const dialog = await screen.findByRole("alertdialog")
  expect(
    await within(dialog).findByText(/queues the submission as durable work/i)
  ).toBeInTheDocument()
  await user.click(
    within(dialog).getByRole("button", { name: "Approve & continue" })
  )
}

describe("the approvals screen", () => {
  it("prepares an application and shows the stored package", async () => {
    const user = setupUser()
    renderApp({ route: "/app/approvals" })

    await prepare(user)

    expect(
      screen.getByText(/Nothing has been submitted yet/)
    ).toBeInTheDocument()
    expect(screen.getAllByText("approval-1").length).toBeGreaterThan(0)
    expect(
      screen.getByText("You're in control. Nothing runs before you approve it.")
    ).toBeInTheDocument()
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

    await prepare(user)

    expect(screen.queryByLabelText("Approver")).not.toBeInTheDocument()
    expect(
      screen.getByText(/recorded against your account/i)
    ).toBeInTheDocument()
  })

  it("approves through the confirmation, names the run it queued, and never says submitted", async () => {
    let sentBody: unknown = null
    let approveUrl: string | null = null
    server.use(
      http.post(
        `${BASE}/api/applications/:approvalId/approve`,
        async ({ request }) => {
          approveUrl = request.url
          sentBody = await request.json()
          // WS-32: the real route answers 202 with the queued run.
          return HttpResponse.json(approvalDecision(), { status: 202 })
        }
      )
    )
    const user = setupUser()
    renderApp({ route: "/app/approvals" })

    await prepare(user)

    await user.type(screen.getByLabelText("Reason"), "Looks right")
    await approveThroughDialog(user)

    expect(await screen.findByText("The decision")).toBeInTheDocument()
    // The decision carries the reason only; the server attributes it to
    // the authenticated principal.
    expect(sentBody).toEqual({ reason: "Looks right" })
    // The approve request references the exact payload the screen showed:
    // the id in the URL is the id displayed on the packet.
    expect(approveUrl).toContain("/api/applications/approval-1/approve")
    expect(screen.getAllByText("approval-1").length).toBeGreaterThan(0)
    // The approval accepted the work; the run is how it is followed.
    expect(screen.getByText("Approved — queued")).toBeInTheDocument()
    expect(screen.getByText("run-1")).toBeInTheDocument()
    // The 202 is an acceptance, never a submission.
    expect(
      screen.queryByText("The application was submitted")
    ).not.toBeInTheDocument()
    expect(
      screen.getByText(
        /Nothing has been submitted yet, so there is no evidence/
      )
    ).toBeInTheDocument()
  })

  it("guards against a duplicate approve: the action is replaced once the decision is recorded", async () => {
    const approve = vi.fn()
    server.use(
      http.post(`${BASE}/api/applications/:approvalId/approve`, async () => {
        approve()
        return HttpResponse.json(approvalDecision(), { status: 202 })
      })
    )
    const user = setupUser()
    renderApp({ route: "/app/approvals" })

    await prepare(user)
    await approveThroughDialog(user)

    await screen.findByText("Approved — queued")
    expect(approve).toHaveBeenCalledTimes(1)
    // The decision bar is replaced by the recorded line, so a second
    // approve cannot be sent from this screen.
    expect(
      screen.getByText(/Decision recorded — the result is below/)
    ).toBeInTheDocument()
    expect(
      screen.queryByRole("button", { name: "Approve & continue" })
    ).not.toBeInTheDocument()
    expect(
      screen.queryByRole("button", { name: "Reject" })
    ).not.toBeInTheDocument()
  })

  it("keeps the confirmation disabled while the decision is in flight", async () => {
    const release: { call?: () => void } = {}
    server.use(
      http.post(`${BASE}/api/applications/:approvalId/approve`, () => {
        return new Promise((resolve) => {
          release.call = () =>
            resolve(HttpResponse.json(approvalDecision(), { status: 202 }))
        })
      })
    )
    const user = setupUser()
    renderApp({ route: "/app/approvals" })

    await prepare(user)
    await user.click(screen.getByRole("button", { name: "Approve & continue" }))
    const dialog = await screen.findByRole("alertdialog")
    await user.click(
      within(dialog).getByRole("button", { name: "Approve & continue" })
    )

    // In flight: the confirm button reads its pending label and cannot be
    // clicked again.
    const pendingButton = await within(dialog).findByRole("button", {
      name: "Queuing…",
    })
    expect(pendingButton).toBeDisabled()
    expect(
      within(dialog).getByRole("button", { name: "Cancel" })
    ).toBeDisabled()

    release.call?.()
    await waitFor(() => {
      expect(screen.getByText("Approved — queued")).toBeInTheDocument()
    })
  })

  it("shows a completed execution as submitted, with its evidence", async () => {
    /*
      The other side of the same distinction: a response that reports a
      **completed** execution (`success: true`) is rendered as submitted, with
      its evidence. No route answers this shape for an approval any more — the
      worker records the outcome later — but the rendering has to stay honest
      for it: `success` alone still decides between "submitted" and a refusal.
    */
    server.use(
      http.post(`${BASE}/api/applications/:approvalId/approve`, () =>
        HttpResponse.json(
          approvalDecision({
            status: "verified",
            success: true,
            run_id: null,
            message: "The application was submitted and verified.",
            evidence: {
              url: "http://127.0.0.1:8901/submitted",
              confirmation_text: "Application submitted",
              status: "submitted",
              screenshot_path: "./data/evidence/workflow-1.png",
              trace_path: "workflow-1.trace.json",
            },
          })
        )
      )
    )
    const user = setupUser()
    renderApp({ route: "/app/approvals" })

    await prepare(user)
    await approveThroughDialog(user)

    expect(
      await screen.findByText("The application was submitted")
    ).toBeInTheDocument()
    expect(screen.getByText("Application submitted")).toBeInTheDocument()
  })

  it("shows the unanswered questions of a needs_human result", async () => {
    server.use(
      http.post(`${BASE}/api/applications/:approvalId/approve`, () =>
        HttpResponse.json(
          approvalDecision({
            success: false,
            status: "needs_human",
            // A refusal carries no run: nothing was queued. Without this the
            // factory's default would read as an accepted submission.
            run_id: null,
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

    await prepare(user)
    await approveThroughDialog(user)

    expect(
      await screen.findByText(
        "The form asked questions the evidence does not answer"
      )
    ).toBeInTheDocument()
    expect(screen.getByText("Years of experience")).toBeInTheDocument()
    expect(screen.getByText("Needs a human answer")).toBeInTheDocument()
    // A refusal is a refusal: no run was queued, and the banner says so.
    expect(
      screen.getByText("The application was not submitted")
    ).toBeInTheDocument()
  })

  it("renders an expired approval's real state with the rebuild path when the approve is refused", async () => {
    // WS-25: the backend writes the `expired` state and refuses the approve
    // with the recovery sentence. The console renders the refusal verbatim
    // and re-reads the stored state — which is now `expired`.
    server.use(
      http.post(`${BASE}/api/applications/:approvalId/approve`, () =>
        HttpResponse.json(
          {
            detail:
              "Approval request 'approval-1' has expired. Prepare the application again to get a fresh review.",
          },
          { status: 409 }
        )
      ),
      http.get(`${BASE}/api/applications/approvals/:approvalId`, () =>
        HttpResponse.json({
          approval_id: "approval-1",
          workflow_id: "workflow-1",
          adapter_name: "fake-ats",
          job_url: "http://127.0.0.1:8901/basic",
          job_title: "AI Engineer",
          company_name: "Acme",
          status: "expired",
          approver: null,
          decision_reason:
            "the approval window closed at 2026-11-10T00:00:00Z; it was not executed",
          created_at: "2026-11-03T10:00:00Z",
          decided_at: null,
          success: null,
          message: null,
        })
      )
    )
    const user = setupUser()
    renderApp({ route: "/app/approvals" })

    await prepare(user)
    await approveThroughDialog(user)

    // The server's refusal, verbatim — with its rebuild path.
    expect(
      await screen.findByText(
        /has expired\. Prepare the application again to get a fresh review/
      )
    ).toBeInTheDocument()
  })

  it("renders a profile-binding refusal verbatim with its rebuild path", async () => {
    /*
      WS-25 binds an approval to the profile digest it was built from. The
      backend does not re-check the digest at approve time yet (recorded as
      the WS-38 follow-up), so the console cannot manufacture this state —
      what it must do is show the server's refusal, word for word, with the
      rebuild path, instead of burying it in a generic error. When the
      backend adds the check, this rendering is already the honest one.
    */
    server.use(
      http.post(`${BASE}/api/applications/:approvalId/approve`, () =>
        HttpResponse.json(
          {
            detail:
              "The profile has changed since this application was prepared; the approval no longer matches what it authorized. Prepare the application again.",
          },
          { status: 409 }
        )
      )
    )
    const user = setupUser()
    renderApp({ route: "/app/approvals" })

    await prepare(user)
    await approveThroughDialog(user)

    expect(
      await screen.findByText(
        /The profile has changed since this application was prepared/
      )
    ).toBeInTheDocument()
    expect(
      screen.getByText(/Prepare the application again/)
    ).toBeInTheDocument()
  })

  it("rejects through the confirmation without submitting anything", async () => {
    const reject = vi.fn()
    server.use(
      http.post(`${BASE}/api/applications/:approvalId/reject`, async () => {
        reject()
        return HttpResponse.json(
          approvalDecision({
            success: false,
            status: "rejected",
            // The reject path queues nothing (WS-32), so there is no run.
            run_id: null,
            message: "Not this one",
            evidence: null,
          })
        )
      })
    )
    const user = setupUser()
    renderApp({ route: "/app/approvals" })

    await prepare(user)

    await user.click(screen.getByRole("button", { name: "Reject" }))
    const dialog = await screen.findByRole("alertdialog")
    expect(
      await within(dialog).findByText(
        /Nothing is submitted and nothing is queued/
      )
    ).toBeInTheDocument()
    await user.click(within(dialog).getByRole("button", { name: "Reject" }))

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

  it("tells the two paths apart: the local test board and a real board's assist", async () => {
    const user = setupUser()
    renderApp({ route: "/app/approvals" })

    await prepare(user)

    // The fake-ATS packet names the local test board and says no employer
    // is involved.
    expect(
      screen.getByText(/the local test board of this deployment/)
    ).toBeInTheDocument()
    expect(
      screen.getByText(/No employer is involved|not an employer/i)
    ).toBeTruthy()
  })

  it("renders the real-board assist path as fill-then-hand-back", async () => {
    server.use(
      http.post(`${BASE}/api/applications/prepare`, () =>
        HttpResponse.json({
          approval_id: "approval-1",
          workflow_id: "workflow-1",
          adapter_name: "greenhouse",
          status: "awaiting_approval",
          form_questions: [],
          blocking_questions: [],
          prepared_summary: {
            job_title: "AI Engineer",
            company_name: "Acme",
            job_url: "https://boards.greenhouse.io/acme/jobs/1",
            adapter_name: "greenhouse",
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
    renderApp({ route: "/app/approvals" })

    await prepare(user)

    // The assist truth: the human's submit is the final one; challenges are
    // handed back, never bypassed; no submit capability exists.
    expect(
      screen.getByText("You're in control. The final submit is yours.")
    ).toBeInTheDocument()
    expect(screen.getByText(/handed back to you/)).toBeInTheDocument()
    expect(
      screen.getByText(/never bypassed|Those are never bypassed/)
    ).toBeTruthy()
    expect(screen.getByText(/hold no submit capability/)).toBeInTheDocument()
  })

  it("shows the persisted decision after a reload, read back from the GET route", async () => {
    /*
      The reload contract (the second audit fix): the decision the human made
      is stored on the approval row and `GET /api/applications/approvals/{id}`
      reports it. The screen seeds its localStorage pointer (what a reload
      leaves behind) and re-reads the state — the run id comes from the
      mirror, labelled as what was queued at approval time.
    */
    window.localStorage.setItem(
      "aja.lastApproval",
      JSON.stringify({
        approval_id: "approval-1",
        application_id: "application-1",
        run_id: "run-1",
      })
    )
    server.use(
      http.get(`${BASE}/api/applications/approvals/:approvalId`, () =>
        HttpResponse.json({
          approval_id: "approval-1",
          workflow_id: "workflow-1",
          adapter_name: "fake-ats",
          job_url: "http://127.0.0.1:8901/basic",
          job_title: "AI Engineer",
          company_name: "Acme",
          status: "approved",
          approver: "user-1",
          decision_reason: "Looks right",
          created_at: "2026-10-21T10:00:00Z",
          decided_at: "2026-10-21T10:02:00Z",
          success: null,
          message: null,
        })
      )
    )
    renderApp({ route: "/app/approvals" })

    expect(await screen.findByText("Approved — queued")).toBeInTheDocument()
    expect(screen.getByText("run-1")).toBeInTheDocument()
    expect(screen.getByText(/was queued when you approved/)).toBeInTheDocument()
    expect(
      screen.getByRole("link", { name: "Open Operations" })
    ).toBeInTheDocument()
    // The reload shows the persisted truth; it must not invent a submission.
    expect(
      screen.queryByText("The application was submitted")
    ).not.toBeInTheDocument()
    // And with no packet on screen, there is no approve action to take.
    expect(
      screen.queryByRole("button", { name: "Approve & continue" })
    ).not.toBeInTheDocument()
  })

  it("shows a pending approval after a reload without offering to approve what it cannot show", async () => {
    window.localStorage.setItem(
      "aja.lastApproval",
      JSON.stringify({
        approval_id: "approval-1",
        application_id: null,
        run_id: null,
      })
    )
    // The default GET handler answers `pending`.
    renderApp({ route: "/app/approvals" })

    expect(
      await screen.findByText(
        "A prepared application is waiting for your decision"
      )
    ).toBeInTheDocument()
    expect(screen.getAllByText("approval-1").length).toBeGreaterThan(0)
    // The GET does not carry the payload, so approving from here would
    // approve a packet the human is not looking at. The way back is the
    // prepare form.
    expect(
      screen.queryByRole("button", { name: "Approve & continue" })
    ).not.toBeInTheDocument()
    expect(
      screen.getByText(/preparing the application again/i)
    ).toBeInTheDocument()
  })

  it("shows an expired approval after a reload with its rebuild path", async () => {
    window.localStorage.setItem(
      "aja.lastApproval",
      JSON.stringify({
        approval_id: "approval-1",
        application_id: null,
        run_id: null,
      })
    )
    server.use(
      http.get(`${BASE}/api/applications/approvals/:approvalId`, () =>
        HttpResponse.json({
          approval_id: "approval-1",
          workflow_id: "workflow-1",
          adapter_name: "greenhouse",
          job_url: "https://boards.greenhouse.io/acme/jobs/1",
          job_title: "AI Engineer",
          company_name: "Acme",
          status: "expired",
          approver: null,
          decision_reason:
            "the approval window closed at 2026-11-10T00:00:00Z; it was not executed",
          created_at: "2026-11-03T10:00:00Z",
          decided_at: null,
          success: null,
          message: null,
        })
      )
    )
    renderApp({ route: "/app/approvals" })

    expect(await screen.findByText("The approval expired")).toBeInTheDocument()
    expect(
      screen.getByText(/prepare the application again/i)
    ).toBeInTheDocument()
    expect(
      screen.queryByRole("button", { name: "Approve & continue" })
    ).not.toBeInTheDocument()
  })

  it("drops a stale pointer when the approval it names does not exist", async () => {
    window.localStorage.setItem(
      "aja.lastApproval",
      JSON.stringify({
        approval_id: "gone-approval",
        application_id: null,
        run_id: null,
      })
    )
    server.use(
      http.get(`${BASE}/api/applications/approvals/:approvalId`, () =>
        HttpResponse.json(
          { detail: "Approval request not found" },
          { status: 404 }
        )
      )
    )
    const user = setupUser()
    renderApp({ route: "/app/approvals" })

    // A 404 means the pointer names nothing this account owns: the console
    // drops it and shows the prepare form, not a dead end.
    await screen.findByLabelText("Job title")
    await waitFor(() => {
      expect(window.localStorage.getItem("aja.lastApproval")).toBeNull()
    })
    // The form is usable again — a fresh prepare works.
    await user.type(screen.getByLabelText("Job title"), "AI Engineer")
    expect(
      screen.getByRole("button", { name: "Prepare application" })
    ).toBeEnabled()
  })
})
