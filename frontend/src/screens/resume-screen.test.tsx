import { fireEvent, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { http, HttpResponse } from "msw"
import { describe, expect, it } from "vitest"

import { ResumeScreen } from "@/screens/resume-screen"
import { getCurrentProfileId, setCurrentProfileId } from "@/lib/profile"
import { profileResponse } from "@/test/factories"
import { server } from "@/test/server"
import { renderScreen } from "@/test/render"

const BASE = "http://api.test"

function makeFile(name: string, type = "text/plain", bytes = 64): File {
  return new File(["x".repeat(bytes)], name, { type })
}

describe("the resume screen", () => {
  it("uploads a resume, keeps the profile id and shows the server's warnings", async () => {
    const user = userEvent.setup()
    renderScreen(<ResumeScreen />)

    await user.upload(
      screen.getByLabelText("Résumé file"),
      makeFile("resume.txt")
    )
    await user.click(
      screen.getByRole("button", { name: /Upload and analyze résumé/ })
    )

    expect((await screen.findAllByText("profile-1")).length).toBeGreaterThan(0)
    expect(getCurrentProfileId()).toBe("profile-1")
    expect(
      await screen.findByText("Profile has no parseable email")
    ).toBeInTheDocument()
  })

  it("refuses a disallowed extension before the upload starts", () => {
    renderScreen(<ResumeScreen />)

    // The file input's `accept` attribute already filters the file dialog in
    // a browser; this drives the change event directly to prove the
    // console's own guard as well.
    const input = screen.getByLabelText("Résumé file")
    fireEvent.change(input, { target: { files: [makeFile("resume.pdf")] } })

    expect(screen.getByText("This file will be refused")).toBeInTheDocument()
    expect(
      screen.getByRole("button", { name: /Upload and analyze résumé/ })
    ).toBeDisabled()
  })

  it("refuses a file above the 5 MB cap", async () => {
    const user = userEvent.setup()
    renderScreen(<ResumeScreen />)

    const oversized = makeFile("resume.txt", "text/plain", 5 * 1024 * 1024 + 1)
    await user.upload(screen.getByLabelText("Résumé file"), oversized)

    expect(
      await screen.findByText("This file will be refused")
    ).toBeInTheDocument()
  })

  it("shows the server's refusal verbatim", async () => {
    server.use(
      http.post(`${BASE}/api/resumes`, () =>
        HttpResponse.json(
          { detail: "Resume could not be parsed: the file is empty." },
          { status: 400 }
        )
      )
    )
    const user = userEvent.setup()
    renderScreen(<ResumeScreen />)

    await user.upload(
      screen.getByLabelText("Résumé file"),
      makeFile("resume.txt")
    )
    await user.click(
      screen.getByRole("button", { name: /Upload and analyze résumé/ })
    )

    expect(
      await screen.findByText("Resume could not be parsed: the file is empty.")
    ).toBeInTheDocument()
  })

  it("works with a document chosen from the list", async () => {
    const user = userEvent.setup()
    renderScreen(<ResumeScreen />)

    await user.click(
      await screen.findByRole("button", { name: "Use Résumé — Ada Lovelace" })
    )

    expect(getCurrentProfileId()).toBe("profile-1")
  })

  it("adopts the newest document even when the profile check answers first", async () => {
    /*
      The order is not guaranteed: the 404 can arrive before the document
      library does. The console must not clear the handle in that window — it
      did once, and left the operator on the upload prompt with 64 résumés in
      the library.
    */
    server.use(
      http.get(`${BASE}/api/resumes/:profileId`, async ({ params }) => {
        if (params.profileId !== "gone") return HttpResponse.json(profileResponse())
        await new Promise((resolve) => setTimeout(resolve, 80))
        return HttpResponse.json(
          { detail: "Profile 'gone' not found" },
          { status: 404 }
        )
      }),
      http.get(`${BASE}/api/documents`, async () => {
        await new Promise((resolve) => setTimeout(resolve, 20))
        return HttpResponse.json({
          documents: [
            {
              id: "profile-profile-1",
              kind: "resume",
              title: "Résumé — Ada Lovelace",
              filename: "profile-1.docx",
              path: "data/resumes/profile-1.docx",
              size_bytes: 24576,
              created_at: "2026-10-21T10:00:00Z",
              profile_id: "profile-1",
              job_id: null,
            },
          ],
          count: 1,
        })
      })
    )
    setCurrentProfileId("gone")
    renderScreen(<ResumeScreen />)

    expect(await screen.findByText("Ada Lovelace")).toBeInTheDocument()
    await waitFor(() => expect(getCurrentProfileId()).toBe("profile-1"))
    expect(
      screen.queryByText(/Let's build your career profile/)
    ).not.toBeInTheDocument()
  })

  it("moves to the most recent document when the saved profile is gone", async () => {
    server.use(
      http.get(`${BASE}/api/resumes/:profileId`, ({ params }) =>
        params.profileId === "gone"
          ? HttpResponse.json(
              { detail: "Profile 'gone' not found" },
              { status: 404 }
            )
          : HttpResponse.json(profileResponse())
      )
    )
    // The profile this browser remembered belongs to somebody else, or is
    // gone: the console moves to the newest document the account has.
    setCurrentProfileId("gone")
    renderScreen(<ResumeScreen />)

    // No error: the console reads the newest document the account has, and
    // the library marks the one it is reading.
    expect(await screen.findByText("Ada Lovelace")).toBeInTheDocument()
    expect(await screen.findByText("In use")).toBeInTheDocument()
    await waitFor(() => expect(getCurrentProfileId()).toBe("profile-1"))
    expect(
      screen.queryByText(/not available to this account/)
    ).not.toBeInTheDocument()
  })

  it("asks for a résumé when the saved profile is gone and there is none", async () => {
    server.use(
      http.get(`${BASE}/api/resumes/:profileId`, () =>
        HttpResponse.json(
          { detail: "Profile 'gone' not found" },
          { status: 404 }
        )
      ),
      http.get(`${BASE}/api/documents`, () =>
        HttpResponse.json({ documents: [], count: 0 })
      )
    )
    setCurrentProfileId("gone")
    renderScreen(<ResumeScreen />)

    // Nothing to fall back to: the screen is the upload prompt, not an
    // error about a profile the operator cannot see anyway.
    expect(
      await screen.findByRole("heading", { name: /Let's build your career profile/ })
    ).toBeInTheDocument()
    await waitFor(() => expect(getCurrentProfileId()).toBeNull())
    expect(
      screen.queryByText(/not available to this account/)
    ).not.toBeInTheDocument()
  })

  it("pages the library five at a time and marks the document in use", async () => {
    const documents = Array.from({ length: 7 }, (_, index) => ({
      id: `profile-p${index + 1}`,
      kind: "resume" as const,
      title: `Résumé ${index + 1}`,
      filename: `resume-${index + 1}.docx`,
      path: `/data/users/x/resumes/resume-${index + 1}.docx`,
      size_bytes: 1024,
      created_at: "2026-11-05T10:00:00Z",
      profile_id: `p${index + 1}`,
      job_id: null,
    }))
    server.use(
      http.get(`${BASE}/api/documents`, () =>
        HttpResponse.json({ documents, count: documents.length })
      )
    )
    setCurrentProfileId("p1")
    renderScreen(<ResumeScreen />)

    expect(await screen.findByText("Résumé 1")).toBeInTheDocument()
    expect(screen.getByText("1–5 of 7 documents")).toBeInTheDocument()
    expect(screen.queryByText("Résumé 6")).not.toBeInTheDocument()
    // The document the console is working with is the one marked, and the
    // mark says what it means.
    expect(screen.getByText("In use")).toBeInTheDocument()
    expect(screen.getAllByText("Use")).toHaveLength(4)

    await userEvent.setup().click(screen.getByRole("button", { name: "Next" }))
    expect(await screen.findByText("Résumé 6")).toBeInTheDocument()
    expect(screen.getByText("6–7 of 7 documents")).toBeInTheDocument()
  })

  it("shows the parsed profile of the current profile", async () => {
    setCurrentProfileId("profile-1")
    renderScreen(<ResumeScreen />)

    await waitFor(() => {
      expect(screen.getByText("Ada Lovelace")).toBeInTheDocument()
    })
    expect(screen.getAllByText("Python").length).toBeGreaterThan(0)
  })
})
