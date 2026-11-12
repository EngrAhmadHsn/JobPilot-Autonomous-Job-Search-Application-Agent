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
    renderApp({ route: "/app/resume" })

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
    renderApp({ route: "/app/resume" })

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
    renderApp({ route: "/app/resume" })

    await user.click(
      await screen.findByRole("button", { name: /No account yet\?/ })
    )

    expect(
      await screen.findByRole("heading", { name: "Create an account" })
    ).toBeInTheDocument()
  })

  it("says when the credentials are refused, in words a person can use", async () => {
    server.use(
      http.get(`${BASE}/api/auth/me`, () =>
        HttpResponse.json({ detail: "Unauthorized" }, { status: 401 })
      ),
      http.post(`${BASE}/api/auth/cookie/login`, () =>
        // The server's real answer: a fastapi-users code, not a sentence.
        HttpResponse.json({ detail: "LOGIN_BAD_CREDENTIALS" }, { status: 400 })
      )
    )

    const user = userEvent.setup()
    renderApp({ route: "/app/resume" })

    await user.type(
      await screen.findByLabelText("Email"),
      "operator@example.com"
    )
    await user.type(screen.getByLabelText("Password"), "wrong")
    await user.click(screen.getByRole("button", { name: "Sign in" }))

    expect(
      await screen.findByText(/don't match an account here/i)
    ).toBeInTheDocument()
    // The signed-in surface says it in the product's voice: the taxonomy is
    // for an administrator, and the sign-in form is not one.
    expect(screen.queryByText(/LOGIN_BAD_CREDENTIALS/)).not.toBeInTheDocument()
    expect(screen.queryByText(/HTTP 400/)).not.toBeInTheDocument()
  })
})

/**
 * Which form the screen opens.
 *
 * The landing page's primary button says "Create your account". It pointed at
 * this route, which always opened in sign-in mode, so a first-time visitor was
 * asked for a password to an account that did not exist yet. The route now
 * reads the mode the caller asked for, and the default stays sign-in for the
 * returning visitor who arrives from the header.
 */
describe("the sign-in screen's opening form", () => {
  it("opens the create form when the caller asks for it", async () => {
    server.use(
      http.get(`${BASE}/api/auth/me`, () =>
        HttpResponse.json({ detail: "Unauthorized" }, { status: 401 })
      )
    )
    renderApp({ route: "/sign-in", state: { mode: "create" } })

    expect(
      await screen.findByRole("heading", { name: "Create an account" })
    ).toBeInTheDocument()
    expect(
      screen.getByRole("button", { name: "Create the account" })
    ).toBeInTheDocument()
  })

  it("opens the sign-in form by default", async () => {
    server.use(
      http.get(`${BASE}/api/auth/me`, () =>
        HttpResponse.json({ detail: "Unauthorized" }, { status: 401 })
      )
    )
    renderApp({ route: "/sign-in" })

    expect(
      await screen.findByRole("heading", { name: "Sign in" })
    ).toBeInTheDocument()
  })
})
