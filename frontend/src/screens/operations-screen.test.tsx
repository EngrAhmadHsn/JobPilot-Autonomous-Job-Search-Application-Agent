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
    // The child embedding run carries the parent's report only in the mock;
    // in the backend it has its own (empty) metadata.
    server.use(
      http.get(`${BASE}/api/runs/:runId`, ({ params }) =>
        HttpResponse.json({
          run: runDetail({
            id: String(params.runId),
            metadata:
              String(params.runId) === "run-embed-1" ? {} : runSummary().metadata,
          }),
        })
      )
    )
    const user = userEvent.setup()
    renderScreen(<OperationsScreen />)

    await user.click(screen.getByRole("button", { name: "Queue the refresh" }))

    expect(await screen.findByText("Refresh accepted")).toBeInTheDocument()
    expect(await screen.findByText("Latest run")).toBeInTheDocument()
    expect(
      (await screen.findAllByText(/Finished/)).length
    ).toBeGreaterThan(0)
    // The report comes from the run's persisted metadata, not a response body.
    expect(await screen.findByText("The refresh report")).toBeInTheDocument()
    expect(screen.getByText("Persisted")).toBeInTheDocument()
  })

  it("adopts a run that is still going, after a reload", async () => {
    /*
      The point of a durable run: the page can be closed and reopened. The
      screen follows the newest run that has not finished, from the backend's
      own history, without anything remembered in the browser.
    */
    server.use(
      http.get(`${BASE}/api/runs`, () =>
        HttpResponse.json(
          runsResponse([
            runSummary({
              id: "run-live",
              job_type: "refresh",
              status: "RUNNING",
              progress_percent: 40,
              completed_items: 20,
              total_items: 50,
              remaining_items: 30,
            }),
          ])
        )
      ),
      http.get(`${BASE}/api/runs/:runId`, () =>
        HttpResponse.json({
          run: runDetail({
            id: "run-live",
            job_type: "refresh",
            status: "RUNNING",
            progress_percent: 40,
            completed_items: 20,
            total_items: 50,
            remaining_items: 30,
            metadata: {},
          }),
        })
      )
    )
    renderScreen(<OperationsScreen />)

    expect(await screen.findByText("Latest run")).toBeInTheDocument()
    expect(await screen.findByText("Working now")).toBeInTheDocument()
    expect(screen.getByText(/20 of 50 done/)).toBeInTheDocument()
  })

  it("shows the embedding pass a refresh started", async () => {
    const user = userEvent.setup()
    renderScreen(<OperationsScreen />)

    await user.click(screen.getByRole("button", { name: "Queue the refresh" }))

    expect(
      await screen.findByText(/The embedding pass this refresh started/)
    ).toBeInTheDocument()
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

    expect(
      (await screen.findAllByText(/Paused — daily budget spent/)).length
    ).toBeGreaterThan(0)
    expect(
      screen.getAllByText(/The daily embedding budget is spent/).length
    ).toBeGreaterThan(0)
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
      (await screen.findAllByText(/Interrupted — needs an administrator/)).length
    ).toBeGreaterThan(0)
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

  it("shows the account's run history in the backend's own words", async () => {
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
    expect(
      screen.getAllByText(/Interrupted — needs an administrator/).length
    ).toBeGreaterThan(0)
    // Every row can be opened into the same progress panel.
    expect(screen.getAllByRole("button", { name: /Show|Showing/ }).length).toBe(2)
  })
})