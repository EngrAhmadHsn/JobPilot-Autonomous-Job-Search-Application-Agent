import { screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { http, HttpResponse } from "msw"
import { describe, expect, it } from "vitest"

import { WorkPreferencesCard } from "@/components/profile/work-preferences-card"
import { setCurrentProfileId } from "@/lib/profile"
import { createQueryClient } from "@/lib/query-client"
import { applicationProfileResponse, candidateProfile } from "@/test/factories"
import { renderApp, renderScreen } from "@/test/render"
import { server, setStoredApplicationProfile } from "@/test/server"

/**
 * WS-21: one Work Preferences editor, on both pages, writing one source.
 *
 * The defects these tests pin down: the two pages showed different documents,
 * a cleared preference was silently resurrected by the engine, and each card
 * saved from its own stale snapshot.
 */

const BASE = "http://api.test"
const ROUTE = `${BASE}/api/profiles/:profileId/application-profile`

interface CapturedPut {
  body: {
    preferences?: Record<string, unknown>
    answers?: Record<string, unknown>
    confirmed_fields?: string[]
  }
}

function capturePuts() {
  const puts: CapturedPut[] = []
  server.use(
    http.put(ROUTE, async ({ request }) => {
      const body = (await request.json()) as CapturedPut["body"]
      puts.push({ body })
      setStoredApplicationProfile(
        body as unknown as ReturnType<
          typeof candidateProfile
        >["application_profile"]
      )
      return HttpResponse.json(applicationProfileResponse(body as never))
    })
  )
  return puts
}

describe("the shared Work Preferences card", () => {
  it("offers the résumé-detected values, saves nothing until Save, and saves them when asked", async () => {
    // The factory profile detected hybrid/London/full-time on the résumé.
    const puts = capturePuts()
    const user = userEvent.setup()
    renderScreen(<WorkPreferencesCard profileId="profile-1" />)

    expect(
      await screen.findByText(/Detected from your résumé/)
    ).toBeInTheDocument()
    expect(screen.getByText(/Work mode: hybrid/)).toBeInTheDocument()

    await user.click(
      screen.getByRole("button", { name: "Use detected values" })
    )
    expect(puts).toHaveLength(0) // importing fills the form; it does not save

    expect(screen.getByLabelText("Work mode")).toHaveValue("hybrid")
    await user.click(screen.getByRole("button", { name: "Save preferences" }))

    await waitFor(() => expect(puts).toHaveLength(1))
    const saved = puts[0]?.body
    expect(saved?.preferences?.remote_preference).toBe("hybrid")
    expect(saved?.preferences?.preferred_locations).toEqual(["London"])
    expect(saved?.preferences?.employment_types).toEqual(["full-time"])
    // The fine-grained marker: this save is an explicit target-roles answer.
    expect(saved?.confirmed_fields).toContain("preferences.target_roles")
    expect(saved?.confirmed_fields).toContain("answers.compensation")
  })

  it("saves a cleared preference as an explicit clear", async () => {
    const stored = candidateProfile().application_profile
    stored.preferences.remote_preference = "remote"
    server.use(
      http.get(ROUTE, () =>
        HttpResponse.json(applicationProfileResponse(stored))
      )
    )
    const puts = capturePuts()
    const user = userEvent.setup()
    renderScreen(<WorkPreferencesCard profileId="profile-1" />)

    await user.selectOptions(
      await screen.findByLabelText("Work mode"),
      "Not set"
    )
    await user.click(screen.getByRole("button", { name: "Save preferences" }))

    await waitFor(() => expect(puts).toHaveLength(1))
    expect(puts[0]?.body.preferences?.remote_preference).toBeNull()
  })

  it("writes target roles with provenance-safe markers", async () => {
    const puts = capturePuts()
    const user = userEvent.setup()
    renderScreen(<WorkPreferencesCard profileId="profile-1" />)

    const targets = await screen.findByLabelText("Target roles")
    await user.type(targets, "Web Developer, Frontend Developer")
    await user.click(screen.getByRole("button", { name: "Save preferences" }))

    await waitFor(() => expect(puts).toHaveLength(1))
    expect(puts[0]?.body.preferences?.target_roles).toEqual([
      "Web Developer",
      "Frontend Developer",
    ])
  })

  it("keeps another card's fields when saving (no stale snapshot)", async () => {
    const queryClient = createQueryClient()
    const stored = candidateProfile().application_profile
    stored.answers.compensation.current_salary = 50000
    queryClient.setQueryData(["application-profile", "profile-1"], {
      profile_id: "profile-1",
      application_profile: stored,
    })
    const puts = capturePuts()
    const user = userEvent.setup()
    renderScreen(<WorkPreferencesCard profileId="profile-1" />, { queryClient })

    const locations = await screen.findByLabelText("Preferred locations")
    await user.clear(locations)
    await user.type(locations, "Berlin")
    await user.click(screen.getByRole("button", { name: "Save preferences" }))

    await waitFor(() => expect(puts).toHaveLength(1))
    const answers = puts[0]?.body.answers as
      { compensation?: { current_salary?: number } } | undefined
    expect(answers?.compensation?.current_salary).toBe(50000)
    expect(puts[0]?.body.preferences?.preferred_locations).toEqual(["Berlin"])
  })

  it("is the same editor on the Résumé page and the Profile page", async () => {
    setCurrentProfileId("profile-1")

    const resume = renderApp({ route: "/app/resume" })
    expect(
      await screen.findByRole("button", { name: "Save preferences" })
    ).toBeInTheDocument()
    expect(screen.getByLabelText("Target roles")).toBeInTheDocument()
    resume.unmount()

    renderApp({ route: "/app/profile" })
    expect(
      await screen.findByRole("button", { name: "Save preferences" })
    ).toBeInTheDocument()
    expect(screen.getByLabelText("Target roles")).toBeInTheDocument()
  })
})
