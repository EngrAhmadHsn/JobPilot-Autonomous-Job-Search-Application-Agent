import { screen, waitFor } from "@testing-library/react"
import { http, HttpResponse } from "msw"
import { describe, expect, it, vi } from "vitest"

import { OperationsScreen } from "@/screens/operations-screen"
import { runDetail, runsResponse, runSummary } from "@/test/factories"
import { server } from "@/test/server"
import { renderScreen } from "@/test/render"

// The cadences are the production ones compressed to milliseconds (see
// `test/polling-cadence.ts`), so the polling *wiring* is observable here
// without waiting minutes. The cadences themselves are pinned in
// `lib/polling.test.ts`.
vi.mock("@/lib/polling", async () => await import("@/test/polling-cadence"))

const BASE = "http://api.test"

const hold = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms))

describe("the operations screen's polling", () => {
  it("keeps updating a running run, then never polls it again once terminal", async () => {
    let detailCalls = 0
    server.use(
      http.get(`${BASE}/api/runs`, () =>
        HttpResponse.json(
          runsResponse([
            runSummary({ id: "run-live", status: "RUNNING", metadata: {} }),
          ])
        )
      ),
      http.get(`${BASE}/api/runs/:runId`, ({ params }) => {
        detailCalls += 1
        const finished = detailCalls >= 3
        return HttpResponse.json({
          run: runDetail({
            id: String(params.runId),
            status: finished ? "COMPLETED" : "RUNNING",
            progress_percent: finished ? 100 : 40,
            completed_items: finished ? 50 : 20,
            total_items: 50,
            remaining_items: finished ? 0 : 30,
            metadata: {},
          }),
        })
      })
    )
    renderScreen(<OperationsScreen />)

    await screen.findAllByText(/Working now/)
    await waitFor(() => expect(detailCalls).toBeGreaterThanOrEqual(3))
    await screen.findAllByText(/Finished/)

    // The run is terminal now; no further detail request may fire.
    const settled = detailCalls
    await hold(240)
    expect(detailCalls).toBe(settled)
  })

  it("follows the embedding child while it works, and stops when it finishes", async () => {
    let childCalls = 0
    server.use(
      http.get(`${BASE}/api/runs`, () =>
        HttpResponse.json(
          runsResponse([
            runSummary({ id: "run-parent", status: "RUNNING", metadata: {} }),
          ])
        )
      ),
      http.get(`${BASE}/api/runs/:runId`, ({ params }) => {
        const id = String(params.runId)
        if (id === "run-embed-1") {
          childCalls += 1
          const finished = childCalls >= 3
          return HttpResponse.json({
            run: runDetail({
              id,
              job_type: "embedding",
              status: finished ? "COMPLETED" : "RUNNING",
              progress_percent: finished ? 100 : 30,
              metadata: {},
            }),
          })
        }
        return HttpResponse.json({
          run: runDetail({
            id,
            status: "RUNNING",
            metadata: { refresh: { embedding_run_id: "run-embed-1" } },
          }),
        })
      })
    )
    renderScreen(<OperationsScreen />)

    await screen.findAllByText(/The embedding pass this refresh started/)
    await waitFor(() => expect(childCalls).toBeGreaterThanOrEqual(3))

    const settled = childCalls
    await hold(240)
    expect(childCalls).toBe(settled)
  })

  it("keeps a settled history on a slow heartbeat instead of a fast poll", async () => {
    let listCalls = 0
    server.use(
      http.get(`${BASE}/api/runs`, () => {
        listCalls += 1
        return HttpResponse.json(runsResponse([runSummary()]))
      }),
      http.get(`${BASE}/api/runs/:runId`, ({ params }) =>
        HttpResponse.json({
          run: runDetail({ id: String(params.runId), metadata: {} }),
        })
      )
    )
    renderScreen(<OperationsScreen />)

    await waitFor(() => expect(listCalls).toBeGreaterThanOrEqual(1))
    // The idle cadence is 600 ms; the active one is 120 ms. Over this window
    // a fast cadence would have fired twice more.
    await hold(300)
    expect(listCalls).toBe(1)
  })
})
