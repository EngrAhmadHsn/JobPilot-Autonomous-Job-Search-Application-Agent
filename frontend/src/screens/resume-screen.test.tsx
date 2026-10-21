import { fireEvent, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { http, HttpResponse } from "msw"
import { describe, expect, it } from "vitest"

import { ResumeScreen } from "@/screens/resume-screen"
import { getCurrentProfileId } from "@/lib/profile"
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
      screen.getByLabelText("Resume file"),
      makeFile("resume.txt")
    )
    await user.click(screen.getByRole("button", { name: "Upload and parse" }))

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
    const input = screen.getByLabelText("Resume file")
    fireEvent.change(input, { target: { files: [makeFile("resume.pdf")] } })

    expect(screen.getByText("This file will be refused")).toBeInTheDocument()
    expect(
      screen.getByRole("button", { name: "Upload and parse" })
    ).toBeDisabled()
  })

  it("refuses a file above the 5 MB cap", async () => {
    const user = userEvent.setup()
    renderScreen(<ResumeScreen />)

    const oversized = makeFile("resume.txt", "text/plain", 5 * 1024 * 1024 + 1)
    await user.upload(screen.getByLabelText("Resume file"), oversized)

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
      screen.getByLabelText("Resume file"),
      makeFile("resume.txt")
    )
    await user.click(screen.getByRole("button", { name: "Upload and parse" }))

    expect(
      await screen.findByText("Resume could not be parsed: the file is empty.")
    ).toBeInTheDocument()
  })

  it("shows the parsed profile of the current profile", async () => {
    window.localStorage.setItem("aja.currentProfileId", "profile-1")
    renderScreen(<ResumeScreen />)

    await waitFor(() => {
      expect(screen.getByText("Ada Lovelace")).toBeInTheDocument()
    })
    expect(screen.getAllByText("Python").length).toBeGreaterThan(0)
  })
})
