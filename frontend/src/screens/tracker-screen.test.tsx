import { screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { http, HttpResponse } from "msw"
import { describe, expect, it } from "vitest"

import { TrackerScreen } from "@/screens/tracker-screen"
import { server } from "@/test/server"
import { renderApp, renderScreen } from "@/test/render"

const BASE = "http://api.test"

describe("the tracker list", () => {
  it("lists the tracked applications", async () => {
    renderScreen(<TrackerScreen />)

    expect(await screen.findByText("AI Engineer")).toBeInTheDocument()
    expect(
      screen.getByText("1 application · showing 1 from 1")
    ).toBeInTheDocument()
    expect(screen.getAllByText("Verified").length).toBeGreaterThan(0)
  })

  it("filters by status through the server", async () => {
    let seenStatuses: string | null = null
    server.use(
      http.get(`${BASE}/api/applications`, ({ request }) => {
        seenStatuses = new URL(request.url).searchParams.get("status")
        return HttpResponse.json({ items: [], total: 0, limit: 20, offset: 0 })
      })
    )
    const user = userEvent.setup()
    renderScreen(<TrackerScreen />)

    await user.click(
      await screen.findByRole("button", { name: "Awaiting approval" })
    )

    await waitFor(() => {
      expect(seenStatuses).toBe("awaiting_approval")
    })
  })

  it("shows the server's refusal of an unknown status", async () => {
    server.use(
      http.get(`${BASE}/api/applications`, () =>
        HttpResponse.json(
          {
            detail:
              "Unknown status 'nope'. Known statuses: discovered, matched.",
          },
          { status: 400 }
        )
      )
    )
    renderScreen(<TrackerScreen />)

    expect(
      await screen.findByText(
        "Unknown status 'nope'. Known statuses: discovered, matched."
      )
    ).toBeInTheDocument()
  })
})

describe("the tracker detail", () => {
  it("brings the rows in one after another", async () => {
    renderScreen(<TrackerScreen />)

    const rows = await screen.findAllByRole("row")
    // The rows carry the entrance class, and each one carries its own
    // index so the delay grows down the list.
    const withEntrance = rows.filter((row) =>
      row.className.includes("enter-up")
    )
    expect(withEntrance.length).toBeGreaterThan(0)
    expect(withEntrance[0]?.style.getPropertyValue("--i")).toBe("0")
  })

  it("shows the history and the evidence", async () => {
    renderApp({ route: "/tracker/application-1" })

    expect(await screen.findByText("History (2)")).toBeInTheDocument()
    expect(screen.getByText("application_created")).toBeInTheDocument()
    expect(screen.getByText("approval_granted")).toBeInTheDocument()
    expect(await screen.findByText("Application submitted")).toBeInTheDocument()
  })

  it("records a human outcome with a human actor", async () => {
    let sentBody: unknown = null
    server.use(
      http.patch(
        `${BASE}/api/applications/:applicationId/status`,
        async ({ request }) => {
          sentBody = await request.json()
          return HttpResponse.json({
            ...(await import("@/test/factories")).applicationDetail(),
            status: "interview",
          })
        }
      )
    )
    const user = userEvent.setup()
    renderApp({ route: "/tracker/application-1" })

    await user.selectOptions(
      await screen.findByLabelText("Outcome"),
      "interview"
    )
    await user.click(
      await screen.findByRole("button", { name: "Record the outcome" })
    )

    // WS-14: the actor is the authenticated principal, so the console
    // does not collect one and does not send one.
    await waitFor(() => {
      expect(sentBody).toEqual({ status: "interview" })
    })
  })

  it("shows the conflict when the move is not legal", async () => {
    server.use(
      http.patch(`${BASE}/api/applications/:applicationId/status`, () =>
        HttpResponse.json(
          {
            detail: "Illegal transition: verified -> interview is not allowed",
          },
          { status: 409 }
        )
      )
    )
    const user = userEvent.setup()
    renderApp({ route: "/tracker/application-1" })

    await user.click(
      await screen.findByRole("button", { name: "Record the outcome" })
    )

    expect(
      await screen.findByText(
        "Illegal transition: verified -> interview is not allowed"
      )
    ).toBeInTheDocument()
  })

  it("says that the actor may not set the status", async () => {
    server.use(
      http.patch(`${BASE}/api/applications/:applicationId/status`, () =>
        HttpResponse.json(
          { detail: "A human outcome must be recorded by a human actor" },
          { status: 403 }
        )
      )
    )
    const user = userEvent.setup()
    renderApp({ route: "/tracker/application-1" })

    await user.click(
      await screen.findByRole("button", { name: "Record the outcome" })
    )

    expect(
      await screen.findByText(
        "A human outcome must be recorded by a human actor"
      )
    ).toBeInTheDocument()
  })
})
