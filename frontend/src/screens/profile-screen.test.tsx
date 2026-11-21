import { screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { http, HttpResponse } from "msw"
import { describe, expect, it } from "vitest"

import { ProfileScreen } from "@/screens/profile-screen"
import { profileResponse } from "@/test/factories"
import { setCurrentProfileId } from "@/lib/profile"
import { server } from "@/test/server"
import { renderScreen } from "@/test/render"

const BASE = "http://api.test"

/**
 * WS-46 · Where the model-credentials card sits now.
 *
 * It used to be appended to the foot of Profile — WS-27 moved it out of the
 * data guard so a `required`-mode deployment could take a key before the
 * first résumé existed, but it remained an orphan card on a screen about
 * profile answers. WS-46 gives it a real home: the Account & Security
 * screen at `/app/account`, reachable from the account menu in every state.
 *
 * What is pinned here is the move itself: the card renders **nowhere** on
 * Profile — on any tab, with or without a profile — and the "Private by
 * design." card says where it went and links there.
 */

function stubCredentials() {
  server.use(
    http.get(`${BASE}/api/llm/credentials`, () =>
      HttpResponse.json({
        using: "platform",
        provider: "google",
        model: "gemini-3.8-flash",
        hint: "",
      })
    )
  )
}

function stubProfile() {
  server.use(
    http.get(`${BASE}/api/resumes/:profileId`, () =>
      HttpResponse.json(profileResponse())
    )
  )
}

/** A library big enough to need more than one page (five per page). */
function stubDocuments(count: number) {
  const documents = Array.from({ length: count }, (_, index) => ({
    id: `doc-${index + 1}`,
    kind: "resume" as const,
    title: `Résumé ${index + 1}`,
    filename: `doc-${index + 1}.docx`,
    path: `data/resumes/doc-${index + 1}.docx`,
    size_bytes: 1024,
    created_at: "2026-10-21T10:00:00Z",
    profile_id: "profile-1",
    job_id: null,
  }))
  server.use(
    http.get(`${BASE}/api/documents`, () =>
      HttpResponse.json({ documents, count })
    )
  )
}

describe("the model key has moved to Account & Security (WS-46)", () => {
  it("renders no credential card on any tab", async () => {
    setCurrentProfileId("profile-1")
    stubCredentials()
    stubProfile()

    const user = userEvent.setup()
    renderScreen(<ProfileScreen />)

    await screen.findByRole("tablist")
    // The card's controls and its section heading are gone — on the tab the
    // screen opens with…
    expect(screen.queryByRole("button", { name: "Save key" })).toBeNull()
    expect(screen.queryByRole("heading", { name: "Your model" })).toBeNull()

    // …and after visiting both other tabs.
    await user.click(screen.getByRole("tab", { name: "Application answers" }))
    await screen.findByText("Questions that still need you")
    await user.click(screen.getByRole("tab", { name: "Work preferences" }))
    await screen.findByText(/What you want from a job/)
    expect(screen.queryByRole("button", { name: "Save key" })).toBeNull()
  })

  it("leaves the no-profile state on the account screen too", async () => {
    /*
      WS-27's guarantee did not die with the move: a `required`-mode
      deployment must be able to take a key before the first résumé exists.
      The card no longer renders here — the guarantee is kept by the account
      screen, which has no profile guard at all.
    */
    setCurrentProfileId(null)
    stubCredentials()
    server.use(
      http.get(`${BASE}/api/documents`, () =>
        HttpResponse.json({ documents: [], count: 0 })
      )
    )

    renderScreen(<ProfileScreen />)

    expect(await screen.findByText("No profile yet")).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "Save key" })).toBeNull()
    expect(screen.queryByRole("heading", { name: "Your model" })).toBeNull()
  })

  it("says where the credentials went, and links there", async () => {
    setCurrentProfileId("profile-1")
    stubCredentials()
    stubProfile()

    renderScreen(<ProfileScreen />)

    // The design's verbatim line on the "Private by design." card.
    expect(
      await screen.findByText(
        "Model credentials and account controls remain in your account menu."
      )
    ).toBeInTheDocument()
    const link = screen.getByRole("link", { name: "Privacy & account →" })
    expect(link).toHaveAttribute("href", "/app/account")
  })
})

describe("the profile document library's pagination (WS-46)", () => {
  it("pages the library at five per page with the shared pager", async () => {
    setCurrentProfileId("profile-1")
    stubCredentials()
    stubProfile()
    stubDocuments(8)

    const user = userEvent.setup()
    renderScreen(<ProfileScreen />)

    await screen.findByRole("tablist")

    /*
      Each row names its file twice — the visible name and the Preview
      link's screen-reader-only span — so presence is asserted through
      `getAllByText` and absence through `queryByText`.
    */
    expect(screen.getAllByText("doc-1.docx").length).toBeGreaterThan(0)
    expect(screen.getAllByText("doc-5.docx").length).toBeGreaterThan(0)
    expect(screen.queryByText("doc-6.docx")).toBeNull()
    expect(screen.getByText("1–5 of 8 documents")).toBeInTheDocument()
    expect(screen.getByText("Page 1 of 2")).toBeInTheDocument()

    // The counter moves with the page, and the row set follows.
    await user.click(screen.getByRole("button", { name: "Next" }))
    expect(screen.getAllByText("doc-6.docx").length).toBeGreaterThan(0)
    expect(screen.getAllByText("doc-8.docx").length).toBeGreaterThan(0)
    expect(screen.queryByText("doc-1.docx")).toBeNull()
    expect(screen.getByText("6–8 of 8 documents")).toBeInTheDocument()

    await user.click(screen.getByRole("button", { name: "Previous" }))
    expect(screen.getAllByText("doc-1.docx").length).toBeGreaterThan(0)
  })

  it("renders no pager while everything fits on one page", async () => {
    setCurrentProfileId("profile-1")
    stubCredentials()
    stubProfile()
    stubDocuments(3)

    renderScreen(<ProfileScreen />)

    await screen.findAllByText("doc-1.docx")
    expect(screen.queryByRole("button", { name: "Previous" })).toBeNull()
    expect(screen.queryByRole("button", { name: "Next" })).toBeNull()
    expect(screen.queryByText(/of 3 documents/)).toBeNull()
  })

  it("starts over when the library changes underneath the pager", async () => {
    setCurrentProfileId("profile-1")
    stubCredentials()
    stubProfile()
    stubDocuments(8)

    const user = userEvent.setup()
    const { queryClient } = renderScreen(<ProfileScreen />)

    await screen.findAllByText("doc-1.docx")
    await user.click(screen.getByRole("button", { name: "Next" }))
    expect(screen.getAllByText("doc-6.docx").length).toBeGreaterThan(0)

    // A new tailored résumé arrives: the library refetches, and the pager
    // goes back to its first page rather than pointing at rows that moved.
    stubDocuments(9)
    await queryClient.refetchQueries({ queryKey: ["documents"] })

    await screen.findAllByText("doc-1.docx")
    expect(screen.queryByText("doc-6.docx")).toBeNull()
    expect(screen.getByText("1–5 of 9 documents")).toBeInTheDocument()
  })
})

describe("the design's tabbed profile (WS-42, from WS-40)", () => {
  /*
    The design file (node `16:202`) draws three content tabs — Documents ·
    Application answers · Work preferences — and the Documents card carries
    the upload action. Every tab must render real content — a tab that opens
    onto nothing is worse than no tab, because it promises a surface that
    does not exist.
  */
  it("offers the design's three tabs and every one opens onto real content", async () => {
    setCurrentProfileId("profile-1")
    stubCredentials()
    stubProfile()

    const user = userEvent.setup()
    renderScreen(<ProfileScreen />)

    const tabs = await screen.findByRole("tablist")
    for (const name of [
      "Documents",
      "Application answers",
      "Work preferences",
    ]) {
      expect(within(tabs).getByRole("tab", { name })).toBeInTheDocument()
    }

    // Documents: the library, with provenance chips on both kinds.
    expect(
      screen.getByText("Your original stays original.")
    ).toBeInTheDocument()
    expect(screen.getByText("ORIGINAL")).toBeInTheDocument()
    expect(screen.getByText("TAILORED")).toBeInTheDocument()
    expect(screen.getAllByText("In use").length).toBeGreaterThan(0)

    // The source-facts reveal opens onto the parsed résumé.
    await user.click(
      screen.getByRole("button", { name: "View source facts →" })
    )
    expect(
      await screen.findByText(/roles on record|role on record/)
    ).toBeInTheDocument()

    // Application answers: the confirmed-answers panel, gaps included.
    await user.click(screen.getByRole("tab", { name: "Application answers" }))
    expect(
      await screen.findByText("Questions that still need you")
    ).toBeInTheDocument()
    expect(
      screen.getByText("Your choice. Never a ranking signal.")
    ).toBeInTheDocument()

    // Work preferences: the one editor, shared with the intake page.
    await user.click(screen.getByRole("tab", { name: "Work preferences" }))
    expect(
      await screen.findByText(/What you want from a job/)
    ).toBeInTheDocument()
  })

  it("opens the answers tab from a ?tab= deep link", async () => {
    /*
      The account screen's privacy panel links to the profile's answers tab,
      where the voluntary EEO answers live. The link must land there, not on
      Documents.
    */
    setCurrentProfileId("profile-1")
    stubCredentials()
    stubProfile()

    renderScreen(<ProfileScreen />, { route: "/app/profile?tab=answers" })

    expect(
      await screen.findByText("Questions that still need you")
    ).toBeInTheDocument()
    // And the Documents content is not on the page — the link landed on
    // answers, not on the default tab.
    expect(screen.queryByText("Your original stays original.")).toBeNull()
  })

  it("never invents a completeness percentage", async () => {
    /*
      The reference draws a "Profile Complete" badge. There is no completeness
      endpoint, so the console must not print a percentage it cannot source.
    */
    setCurrentProfileId("profile-1")
    stubCredentials()
    stubProfile()
    renderScreen(<ProfileScreen />)

    await screen.findByRole("tablist")
    expect(screen.queryByText(/profile complete/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/\d{1,3}%\s*complete/i)).not.toBeInTheDocument()
  })
})
