import { screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { HttpResponse, http } from "msw"
import { describe, expect, it } from "vitest"

import {
  adminOverviewResponse,
  identityResponse,
  runDetail,
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
/** The worker view, as the backend reports it. */
function workersResponse(healthy: number, total = healthy) {
  return {
    workers: {
      healthy,
      total,
      stale_after_seconds: 60,
      workers: Array.from({ length: total }, (_, index) => ({
        worker_id: `worker-${index + 1}`,
        status: healthy > index ? "running" : "stopped",
        hostname: "dev-machine",
        pid: 100 + index,
        heartbeat_age_seconds: healthy > index ? 3 : 900,
        healthy: healthy > index,
        starts: 1,
        processed_items: 12,
        failed_items: 0,
        work_per_minute: 4,
        current_run_id: null,
        spawned_by_api: false,
        stoppable: healthy > index,
      })),
    },
    control: { enabled: true, max_concurrent: 4 },
    queue: {
      items: {
        queued: 2,
        running: 0,
        retry_wait: 0,
        completed: 0,
        failed: 0,
        cancelled: 0,
        stale_leases: 0,
        reclaimed_leases: 0,
        oldest_pending_age_seconds: 3773,
      },
      runs: { queued: 2 },
    },
  }
}

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
      http.get(`${BASE}/api/admin/health/workers`, () =>
        HttpResponse.json(workersResponse(1))
      ),
      http.get(`${BASE}/api/admin/runs`, () =>
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
    expect(
      await screen.findByText(/Interrupted — needs an administrator/)
    ).toBeInTheDocument()

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
      http.get(`${BASE}/api/admin/health/workers`, () =>
        HttpResponse.json(workersResponse(1))
      ),
      http.get(`${BASE}/api/admin/runs`, () =>
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

  it("says queued work will not run when no worker is alive, and offers one", async () => {
    /*
      The reported defect: a reconciliation was queued, the button said so,
      and nothing happened — because no worker was running. The screen has to
      say that rather than leave a silent queue, and it now offers to start
      one instead of only naming a command.
    */
    server.use(
      http.get(`${BASE}/api/auth/me`, () =>
        HttpResponse.json({ ...identityResponse(), is_superuser: true })
      ),
      http.get(`${BASE}/api/admin/overview`, () =>
        HttpResponse.json(adminOverviewResponse())
      ),
      http.get(`${BASE}/api/admin/health/workers`, () =>
        HttpResponse.json(workersResponse(0))
      ),
      http.get(`${BASE}/api/admin/runs`, () =>
        HttpResponse.json(
          runsResponse([
            runSummary({
              id: "run-reconcile-1",
              job_type: "reconcile",
              status: "QUEUED",
              resumable: false,
            }),
          ])
        )
      )
    )

    renderApp({ route: "/app/admin" })

    expect(await screen.findByText("No worker is running")).toBeInTheDocument()
    expect(
      screen.getByText(/Queued work waits until a worker is running/)
    ).toBeInTheDocument()
    // Wait for the control state to load before asserting the button, so the
    // assertion is about the loaded screen and not about the first paint.
    expect(await screen.findByText(/Up to 4 at once/)).toBeInTheDocument()
    expect(
      screen.getByRole("button", { name: "Start a worker" })
    ).toBeEnabled()
    // The queued run is listed, with the state a person can act on.
    expect(await screen.findByText("reconcile")).toBeInTheDocument()
    expect(screen.getByText(/Waiting for a worker/)).toBeInTheDocument()
  })

  it("starts and stops a worker through the control", async () => {
    const calls: string[] = []
    server.use(
      http.get(`${BASE}/api/auth/me`, () =>
        HttpResponse.json({ ...identityResponse(), is_superuser: true })
      ),
      http.get(`${BASE}/api/admin/overview`, () =>
        HttpResponse.json(adminOverviewResponse())
      ),
      http.get(`${BASE}/api/admin/health/workers`, () =>
        HttpResponse.json(workersResponse(1))
      ),
      http.get(`${BASE}/api/admin/runs`, () => HttpResponse.json(runsResponse([]))),
      http.post(`${BASE}/api/admin/workers`, async ({ request }) => {
        calls.push(`start ${JSON.stringify(await request.json())}`)
        return HttpResponse.json(
          { worker_id: "started-1", status: "starting", pid: 4242, detail: "" },
          { status: 202 }
        )
      }),
      http.post(`${BASE}/api/admin/workers/:id/stop`, ({ params }) => {
        calls.push(`stop ${params.id}`)
        return HttpResponse.json({
          worker_id: String(params.id),
          status: "stopping",
          pid: null,
          detail: "",
        })
      })
    )

    renderApp({ route: "/app/admin" })

    await screen.findByText(/Up to 4 at once/)
    await userEvent.click(
      screen.getByRole("button", { name: "Start a worker" })
    )
    expect(await screen.findByText(/Starting started-1/)).toBeInTheDocument()

    const [firstStop] = screen.getAllByRole("button", { name: "Stop" })
    expect(firstStop).toBeDefined()
    await userEvent.click(firstStop as HTMLElement)
    expect(await screen.findByText(/will stop after the job/)).toBeInTheDocument()

    expect(calls).toEqual(["start {}", "stop worker-1"])
  })

  it("shows a run's progress and its raw detail on demand", async () => {
    server.use(
      http.get(`${BASE}/api/auth/me`, () =>
        HttpResponse.json({ ...identityResponse(), is_superuser: true })
      ),
      http.get(`${BASE}/api/admin/overview`, () =>
        HttpResponse.json(adminOverviewResponse())
      ),
      http.get(`${BASE}/api/admin/health/workers`, () =>
        HttpResponse.json(workersResponse(1))
      ),
      http.get(`${BASE}/api/admin/runs`, () =>
        HttpResponse.json(
          runsResponse([
            runSummary({
              id: "run-refresh-1",
              job_type: "refresh",
              status: "RUNNING",
              progress_percent: 60,
              completed_items: 60,
              total_items: 100,
              remaining_items: 40,
            }),
          ])
        )
      ),
      http.get(`${BASE}/api/admin/runs/:runId`, () =>
        HttpResponse.json({
          run: runDetail({
            id: "run-refresh-1",
            job_type: "refresh",
            status: "RUNNING",
            progress_percent: 60,
            completed_items: 60,
            total_items: 100,
            remaining_items: 40,
          }),
        })
      )
    )

    renderApp({ route: "/app/admin" })
    const user = userEvent.setup()

    await user.click(await screen.findByRole("button", { name: "Progress" }))

    // The same panel the operator sees, plus the administrator's detail.
    expect(await screen.findByText("Working now")).toBeInTheDocument()
    expect(screen.getByText(/60 of 100 done/)).toBeInTheDocument()
    expect(screen.getByText("Run id")).toBeInTheDocument()
    expect(screen.getByText("Lifecycle events")).toBeInTheDocument()
  })

  it("offers no resume for a finished run", async () => {
    server.use(
      http.get(`${BASE}/api/auth/me`, () =>
        HttpResponse.json({ ...identityResponse(), is_superuser: true })
      ),
      http.get(`${BASE}/api/admin/overview`, () =>
        HttpResponse.json(adminOverviewResponse())
      ),
      http.get(`${BASE}/api/admin/health/workers`, () =>
        HttpResponse.json(workersResponse(1))
      ),
      http.get(`${BASE}/api/admin/runs`, () =>
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
    expect(await screen.findByText(/Finished/)).toBeInTheDocument()
    expect(
      screen.queryByRole("button", { name: "Resume" })
    ).not.toBeInTheDocument()
  })
})