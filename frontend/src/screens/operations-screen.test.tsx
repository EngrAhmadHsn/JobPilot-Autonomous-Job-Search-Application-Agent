import { screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { http, HttpResponse } from "msw"
import { describe, expect, it } from "vitest"

import { OperationsScreen } from "@/screens/operations-screen"
import {
  runAccepted,
  runDetail,
  runsResponse,
  runSummary,
} from "@/test/factories"
import { server } from "@/test/server"
import { renderScreen } from "@/test/render"

const BASE = "http://api.test"

describe("the operations screen", () => {
  it("queues the refresh and reads the run from persistent state", async () => {
    const user = userEvent.setup()
    renderScreen(<OperationsScreen />)

    await user.click(screen.getByRole("button", { name: "Queue the refresh" }))

    expect(await screen.findByText("Refresh accepted")).toBeInTheDocument()
    expect(await screen.findByText("The run")).toBeInTheDocument()
    expect((await screen.findAllByText("COMPLETED")).length).toBeGreaterThan(0)
    // The report comes from the run's persisted metadata, not a response body.
    expect(await screen.findByText("The refresh report")).toBeInTheDocument()
    expect(screen.getByText("Persisted")).toBeInTheDocument()
    expect(screen.getByText("Every source answered.")).toBeInTheDocument()
  })

  it("joins an active refresh instead of starting a second one", async () => {
    server.use(
      http.post(`${BASE}/api/jobs/refresh`, () =>
        HttpResponse.json(runAccepted({ existing: true }))
      )
    )
    const user = userEvent.setup()
    renderScreen(<OperationsScreen />)

    await user.click(screen.getByRole("button", { name: "Queue the refresh" }))

    expect(
      await screen.findByText("A refresh was already in progress")
    ).toBeInTheDocument()
  })

  it("says when the run is paused on the daily budget", async () => {
    server.use(
      http.post(`${BASE}/api/jobs/refresh`, () =>
        HttpResponse.json(runAccepted())
      ),
      http.get(`${BASE}/api/runs/:runId`, () =>
        HttpResponse.json({
          run: runDetail({
            status: "PAUSED",
            last_error: "Daily embedding work budget spent",
            last_error_kind: "quota",
            progress_percent: 40,
            completed_items: 20,
            total_items: 50,
            remaining_items: 30,
          }),
        })
      )
    )
    const user = userEvent.setup()
    renderScreen(<OperationsScreen />)

    await user.click(screen.getByRole("button", { name: "Queue the refresh" }))

    expect(await screen.findByText("The run is paused")).toBeInTheDocument()
  })

  it("says an interrupted run needs an administrator", async () => {
    server.use(
      http.post(`${BASE}/api/jobs/refresh`, () =>
        HttpResponse.json(runAccepted())
      ),
      http.get(`${BASE}/api/runs/:runId`, () =>
        HttpResponse.json({
          run: runDetail({
            status: "RECOVERABLE",
            progress_percent: 40,
            completed_items: 20,
            total_items: 50,
            remaining_items: 30,
          }),
        })
      )
    )
    const user = userEvent.setup()
    renderScreen(<OperationsScreen />)

    await user.click(screen.getByRole("button", { name: "Queue the refresh" }))

    expect(
      await screen.findByText("The run needs an administrator")
    ).toBeInTheDocument()
  })

  it("shows the bounded queue's refusal", async () => {
    server.use(
      http.post(`${BASE}/api/jobs/refresh`, () =>
        HttpResponse.json(
          {
            detail:
              "The background queue is at its run limit (25). Wait for the current work to finish, then retry.",
          },
          { status: 503, headers: { "Retry-After": "30" } }
        )
      )
    )
    const user = userEvent.setup()
    renderScreen(<OperationsScreen />)

    await user.click(screen.getByRole("button", { name: "Queue the refresh" }))

    expect(
      await screen.findByText(/the background queue is at its run limit/i)
    ).toBeInTheDocument()
  })

  it("shows the account's run history", async () => {
    server.use(
      http.get(`${BASE}/api/runs`, () =>
        HttpResponse.json(
          runsResponse([
            runSummary({ id: "run-refresh", job_type: "refresh" }),
            runSummary({
              id: "run-embed",
              job_type: "embedding",
              status: "RECOVERABLE",
              progress_percent: 40,
              resumable: true,
            }),
          ])
        )
      )
    )
    renderScreen(<OperationsScreen />)

    expect(await screen.findByText("Recent runs")).toBeInTheDocument()
    expect(await screen.findByText("run-refresh")).toBeInTheDocument()
    expect(await screen.findByText("run-embed")).toBeInTheDocument()
    expect(screen.getByText("RECOVERABLE")).toBeInTheDocument()
  })
})