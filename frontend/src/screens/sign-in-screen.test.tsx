import { screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { http, HttpResponse } from "msw"
import { describe, expect, it } from "vitest"

import { server } from "@/test/server"
import { renderApp } from "@/test/render"

const BASE = "http://api.test"

/**
 * The sign-in screen.
 *
 * The API has an identity, so the console needs one: a caller with no
 * session is refused by every protected route, and the console has to
 * ask the server who it is before it shows anything.
 */
describe("the sign-in screen", () => {
  it("is shown when the server refuses the caller's identity", async () => {
    server.use(
      http.get(`${BASE}/api/auth/me`, () =>
        HttpResponse.json({ detail: "Unauthorized" }, { status: 401 })
      )
    )
    renderApp({ route: "/resume" })

    expect(
      await screen.findByRole("heading", { name: "Sign in" })
    ).toBeInTheDocument()
  })

  it("signs in and shows the console", async () => {
    let signedIn = false
    server.use(
      http.get(`${BASE}/api/auth/me`, () => {
        if (!signedIn) {
          return HttpResponse.json({ detail: "Unauthorized" }, { status: 401 })
        }
        return HttpResponse.json({
          id: "user-1",
          email: "operator@example.com",
          full_name: "Operator",
          is_active: true,
          is_superuser: false,
          is_verified: true,
        })
      }),
      http.post(`${BASE}/api/auth/cookie/login`, () => {
        signedIn = true
        return new HttpResponse(null, { status: 204 })
      })
    )

    const user = userEvent.setup()
    renderApp({ route: "/resume" })

    await user.type(
      await screen.findByLabelText("Email"),
      "operator@example.com"
    )
    await user.type(screen.getByLabelText("Password"), "a-long-password")
    await user.click(screen.getByRole("button", { name: "Sign in" }))

    await waitFor(() => {
      expect(screen.getByRole("link", { name: "Matches" })).toBeInTheDocument()
    })
  })

  it("offers to create an account", async () => {
    server.use(
      http.get(`${BASE}/api/auth/me`, () =>
        HttpResponse.json({ detail: "Unauthorized" }, { status: 401 })
      )
    )
    const user = userEvent.setup()
    renderApp({ route: "/resume" })

    await user.click(
      await screen.findByRole("button", { name: /No account yet\?/ })
    )

    expect(
      await screen.findByRole("heading", { name: "Create an account" })
    ).toBeInTheDocument()
  })

  it("says when the credentials are refused", async () => {
    server.use(
      http.get(`${BASE}/api/auth/me`, () =>
        HttpResponse.json({ detail: "Unauthorized" }, { status: 401 })
      ),
      http.post(`${BASE}/api/auth/cookie/login`, () =>
        HttpResponse.json(
          { detail: "400: LOGIN_BAD_CREDENTIALS" },
          { status: 400 }
        )
      )
    )

    const user = userEvent.setup()
    renderApp({ route: "/resume" })

    await user.type(
      await screen.findByLabelText("Email"),
      "operator@example.com"
    )
    await user.type(screen.getByLabelText("Password"), "wrong")
    await user.click(screen.getByRole("button", { name: "Sign in" }))

    expect(
      await screen.findByText(/LOGIN_BAD_CREDENTIALS|bad credentials/i)
    ).toBeInTheDocument()
  })
})
