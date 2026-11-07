import { screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { HttpResponse, http } from "msw"
import { describe, expect, it } from "vitest"

import {
  adminOverviewResponse,
  identityResponse,
  runsResponse,
  runSummary,
} from "@/test/factories"
import { renderApp } from "@/test/render"
import { server } from "@/test/server"

const BASE = "http://api.test"

/**
 * The administration screen.
 *
 * The security property is the point: the screen holds no authority. A
 * non-superuser is refused by the **server**, and the screen reports that
 * refusal rather than working around it. A superuser sees the server's
 * platform totals and the platform's background runs, and a resume is a
 * confirmation followed by the real recovery API — never a client-side
 * status change.
 */
describe("the administration screen", () => {
  it("tells an ordinary account that it is not an administrator", async () => {
    // The default mocked principal is not a superuser.
    renderApp({ route: "/app/admin" })

    expect(
      await screen.findByText(/this account is not an administrator/i)
    ).toBeInTheDocument()
  })

  it("shows the platform totals to a superuser", async () => {
    server.use(
      http.get(`${BASE}/api/auth/me`, () =>
        HttpResponse.json({ ...identityResponse(), is_superuser: true })
      ),
      http.get(`${BASE}/api/admin/overview`, () =>
        HttpResponse.json(adminOverviewResponse())
      )
    )

    renderApp({ route: "/app/admin" })

    expect(await screen.findByText("Accounts")).toBeInTheDocument()
    expect(await screen.findByText("Job corpus")).toBeInTheDocument()
    // The mocked overview reports a corpus of 5,854 listings.
    expect(screen.getByText("5854")).toBeInTheDocument()
  })

  it("reports the server's refusal rather than hiding it", async () => {
    // A superuser in the header, but the server refuses the overview: the
    // screen must show the 403, not pretend the data is there.
    server.use(
      http.get(`${BASE}/api/auth/me`, () =>
        HttpResponse.json({ ...identityResponse(), is_superuser: true })
      ),
      http.get(`${BASE}/api/admin/overview`, () =>
        HttpResponse.json({ detail: "Refused." }, { status: 403 })
      )
    )

    renderApp({ route: "/app/admin" })

    expect(
      await screen.findByText(/the server refused this view \(403\)/i)
    ).toBeInTheDocument()
  })

  it("shows background runs and resumes one after a confirmation", async () => {
    server.use(
      http.get(`${BASE}/api/auth/me`, () =>
        HttpResponse.json({ ...identityResponse(), is_superuser: true })
      ),
      http.get(`${BASE}/api/admin/overview`, () =>
        HttpResponse.json(adminOverviewResponse())
      ),
      http.get(`${BASE}/api/admin/embedding-runs`, () =>
        HttpResponse.json(
          runsResponse([
            runSummary({
              id: "run-embed-1",
              job_type: "embedding",
              status: "RECOVERABLE",
              progress_percent: 40,
              completed_items: 20,
              total_items: 50,
              remaining_items: 30,
              embedding_model: "google/embeddinggemma-2@int8",
              embedding_dimension: 768,
              last_error: "Worker stopped heartbeating",
              resumable: true,
            }),
          ])
        )
      ),
      http.post(`${BASE}/api/admin/embedding-runs/:runId/resume`, () =>
        HttpResponse.json(
          {
            run_id: "run-embed-1",
            status: "QUEUED",
            job_type: "embedding",
            queued: true,
          },
          { status: 202 }
        )
      )
    )

    renderApp({ route: "/app/admin" })
    const user = userEvent.setup()

    expect(await screen.findByText("Background runs")).toBeInTheDocument()
    expect(await screen.findByText("RECOVERABLE")).toBeInTheDocument()

    await user.click(await screen.findByRole("button", { name: "Resume" }))

    // Confirmation first: the brief asks for it, and the dialog shows the
    // checkpoint the administrator is resuming from.
    expect(
      await screen.findByText("Resume this embedding run?")
    ).toBeInTheDocument()
    expect(screen.getByText(/20 of 50 completed, 30 remaining/)).toBeInTheDocument()
    expect(screen.getByText(/google\/embeddinggemma-2@int8/)).toBeInTheDocument()

    await user.click(
      screen.getByRole("button", { name: "Resume outstanding work" })
    )

    expect(await screen.findByText(/is QUEUED/)).toBeInTheDocument()
  })

  it("reports the server's refusal of a resume", async () => {
    server.use(
      http.get(`${BASE}/api/auth/me`, () =>
        HttpResponse.json({ ...identityResponse(), is_superuser: true })
      ),
      http.get(`${BASE}/api/admin/overview`, () =>
        HttpResponse.json(adminOverviewResponse())
      ),
      http.get(`${BASE}/api/admin/embedding-runs`, () =>
        HttpResponse.json(
          runsResponse([
            runSummary({
              id: "run-embed-2",
              job_type: "embedding",
              status: "RECOVERABLE",
              resumable: true,
            }),
          ])
        )
      ),
      http.post(`${BASE}/api/admin/embedding-runs/:runId/resume`, () =>
        HttpResponse.json(
          { detail: "This run embedded with a different model." },
          { status: 409 }
        )
      )
    )

    renderApp({ route: "/app/admin" })
    const user = userEvent.setup()

    await user.click(await screen.findByRole("button", { name: "Resume" }))
    await user.click(
      screen.getByRole("button", { name: "Resume outstanding work" })
    )

    // The sentence appears twice on purpose: as the message, and inside the
    // technical line the administrator reads.
    expect(
      (await screen.findAllByText(/This run embedded with a different model/))
        .length
    ).toBeGreaterThan(0)
    // The administration panel is where the raw answer is wanted: the
    // status and the server's own words, verbatim.
    expect(
      screen.getByText(
        "HTTP 409 · This run embedded with a different model."
      )
    ).toBeInTheDocument()
  })

  it("offers no resume for a finished run", async () => {
    server.use(
      http.get(`${BASE}/api/auth/me`, () =>
        HttpResponse.json({ ...identityResponse(), is_superuser: true })
      ),
      http.get(`${BASE}/api/admin/overview`, () =>
        HttpResponse.json(adminOverviewResponse())
      ),
      http.get(`${BASE}/api/admin/embedding-runs`, () =>
        HttpResponse.json(
          runsResponse([
            runSummary({
              id: "run-embed-3",
              job_type: "embedding",
              status: "COMPLETED",
              resumable: false,
            }),
          ])
        )
      )
    )

    renderApp({ route: "/app/admin" })

    expect(await screen.findByText("Background runs")).toBeInTheDocument()
    expect(await screen.findByText("COMPLETED")).toBeInTheDocument()
    expect(
      screen.queryByRole("button", { name: "Resume" })
    ).not.toBeInTheDocument()
  })
})