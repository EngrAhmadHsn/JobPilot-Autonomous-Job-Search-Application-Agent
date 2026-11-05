import { screen } from "@testing-library/react"
import { HttpResponse, http } from "msw"
import { describe, expect, it } from "vitest"

import { adminOverviewResponse, identityResponse } from "@/test/factories"
import { renderApp } from "@/test/render"
import { server } from "@/test/server"

const BASE = "http://api.test"

/**
 * The administration screen.
 *
 * The security property is the point: the screen holds no authority. A
 * non-superuser is refused by the **server**, and the screen reports that
 * refusal rather than working around it. A superuser sees the server's
 * platform totals.
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
})
