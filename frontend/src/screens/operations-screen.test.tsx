import { screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { http, HttpResponse } from "msw"
import { describe, expect, it } from "vitest"

import { OperationsScreen } from "@/screens/operations-screen"
import { server } from "@/test/server"
import { renderScreen } from "@/test/render"
import { refreshResponse } from "@/test/factories"

const BASE = "http://api.test"

describe("the operations screen", () => {
  it("runs the refresh and shows the report", async () => {
    const user = userEvent.setup()
    renderScreen(<OperationsScreen />)

    await user.click(screen.getByRole("button", { name: "Run the refresh" }))

    expect(await screen.findByText("The report")).toBeInTheDocument()
    expect(screen.getByText("Persisted")).toBeInTheDocument()
    expect(screen.getByText("35 of 35")).toBeInTheDocument()
    expect(screen.getByText("Every source answered.")).toBeInTheDocument()
  })

  it("says when the run stopped on the daily quota", async () => {
    server.use(
      http.post(`${BASE}/api/jobs/refresh`, () =>
        HttpResponse.json(
          refreshResponse({ quota_exhausted: true, degraded_embedding: true })
        )
      )
    )
    const user = userEvent.setup()
    renderScreen(<OperationsScreen />)

    await user.click(screen.getByRole("button", { name: "Run the refresh" }))

    expect(
      await screen.findByText("The run stopped on the daily embedding budget")
    ).toBeInTheDocument()
    expect(screen.getByText("The embedding was degraded")).toBeInTheDocument()
  })

  it("names the sources that failed", async () => {
    server.use(
      http.post(`${BASE}/api/jobs/refresh`, () =>
        HttpResponse.json(
          refreshResponse({ source_errors: { remotive: "timed out" } })
        )
      )
    )
    const user = userEvent.setup()
    renderScreen(<OperationsScreen />)

    await user.click(screen.getByRole("button", { name: "Run the refresh" }))

    expect(await screen.findByText("Sources that failed")).toBeInTheDocument()
    expect(screen.getByText("remotive")).toBeInTheDocument()
    expect(screen.getByText(/timed out/)).toBeInTheDocument()
  })

  it("shows the concurrency gate as a busy server", async () => {
    server.use(
      http.post(`${BASE}/api/jobs/refresh`, () =>
        HttpResponse.json(
          { detail: "Server busy. Please retry shortly." },
          { status: 503, headers: { "Retry-After": "5" } }
        )
      )
    )
    const user = userEvent.setup()
    renderScreen(<OperationsScreen />)

    await user.click(screen.getByRole("button", { name: "Run the refresh" }))

    expect(
      await screen.findByText("Server busy. Please retry shortly.")
    ).toBeInTheDocument()
  })
})
