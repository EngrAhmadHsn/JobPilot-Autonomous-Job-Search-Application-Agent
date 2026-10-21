import { screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { http, HttpResponse } from "msw"
import { describe, expect, it } from "vitest"

import { setCurrentProfileId } from "@/lib/profile"
import { server } from "@/test/server"
import { renderApp } from "@/test/render"
import { tailorResponse } from "@/test/factories"

const BASE = "http://api.test"
const ROUTE = `/tailor/${encodeURIComponent("greenhouse:1")}`

describe("the tailor screen", () => {
  it("tails the resume and shows the reports", async () => {
    setCurrentProfileId("profile-1")
    const user = userEvent.setup()
    renderApp({ route: ROUTE })

    await user.click(
      await screen.findByRole("button", { name: "Tailor this resume" })
    )

    expect(
      await screen.findByText("The tailored resume is ready")
    ).toBeInTheDocument()
    expect(screen.getByText("Factuality report")).toBeInTheDocument()
    expect(screen.getByText("ATS report")).toBeInTheDocument()
    expect(screen.getByText("Grounded job insights")).toBeInTheDocument()
    expect(
      screen.getByText(
        "AI Engineer with analytical and machine learning experience."
      )
    ).toBeInTheDocument()
  })

  it("offers the rendered DOCX for download", async () => {
    setCurrentProfileId("profile-1")
    const user = userEvent.setup()
    renderApp({ route: ROUTE })

    await user.click(
      await screen.findByRole("button", { name: "Tailor this resume" })
    )

    const link = await screen.findByRole("link", { name: "Download the DOCX" })
    expect(link).toHaveAttribute(
      "href",
      "http://api.test/api/tailored/tailoring-1/download"
    )
  })

  it("renders a factuality failure as content, not as an error", async () => {
    server.use(
      http.post(`${BASE}/api/tailor`, () =>
        HttpResponse.json(
          tailorResponse({
            factuality: {
              passed: false,
              removed_skills: ["Kubernetes"],
              removed_experience: ["Chief Scientist"],
              removed_projects: [],
              violations: ["'Kubernetes' is not stated by the resume"],
            },
          })
        )
      )
    )
    setCurrentProfileId("profile-1")
    const user = userEvent.setup()
    renderApp({ route: ROUTE })

    await user.click(
      await screen.findByRole("button", { name: "Tailor this resume" })
    )

    expect(
      await screen.findByText(/unsupported item\(s\) were removed/)
    ).toBeInTheDocument()
    expect(screen.getByText("Kubernetes")).toBeInTheDocument()
    expect(screen.getByText("Chief Scientist")).toBeInTheDocument()
    expect(
      screen.getByText("'Kubernetes' is not stated by the resume")
    ).toBeInTheDocument()
    // A failed factuality report is not an error: no error banner.
    expect(
      screen.queryByText(/The server refused the request/)
    ).not.toBeInTheDocument()
  })

  it("says so when the language model is unavailable", async () => {
    server.use(
      http.post(`${BASE}/api/tailor`, () =>
        HttpResponse.json(
          { detail: "The language model is unavailable; try again later." },
          { status: 503 }
        )
      )
    )
    setCurrentProfileId("profile-1")
    const user = userEvent.setup()
    renderApp({ route: ROUTE })

    await user.click(
      await screen.findByRole("button", { name: "Tailor this resume" })
    )

    expect(
      await screen.findByText(
        "The language model is unavailable; try again later."
      )
    ).toBeInTheDocument()
  })

  it("asks for a profile before it can tailor", async () => {
    renderApp({ route: ROUTE })

    await waitFor(() => {
      expect(screen.getByText("No profile selected")).toBeInTheDocument()
    })
  })
})
