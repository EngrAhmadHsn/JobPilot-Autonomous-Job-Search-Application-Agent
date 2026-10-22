import { screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it, vi } from "vitest"

import {
  DocumentList,
  DocumentPicker,
} from "@/components/documents/document-picker"
import { renderScreen } from "@/test/render"

describe("the document list", () => {
  it("shows the documents the account already has", async () => {
    renderScreen(<DocumentList />)

    expect(await screen.findByText("Résumé — Ada Lovelace")).toBeInTheDocument()
    expect(
      screen.getByText("Tailored résumé — greenhouse:1")
    ).toBeInTheDocument()
  })
})

describe("the document list", () => {
  it("offers to work with a document when the caller can", async () => {
    const onUse = vi.fn()
    const user = userEvent.setup()
    renderScreen(<DocumentList onUse={onUse} />)

    await user.click(
      await screen.findByRole("button", { name: "Use Résumé — Ada Lovelace" })
    )

    expect(onUse).toHaveBeenCalledWith(
      expect.objectContaining({ id: "profile-profile-1" })
    )
  })

  it("has no use action when nobody can use it", async () => {
    renderScreen(<DocumentList />)

    await screen.findByText("Résumé — Ada Lovelace")
    expect(
      screen.queryByRole("button", { name: /^Use/ })
    ).not.toBeInTheDocument()
  })
})

describe("the document picker", () => {
  it("lists the documents and hands the chosen one's path back", async () => {
    const onChange = vi.fn()
    const user = userEvent.setup()
    renderScreen(<DocumentPicker value="" onChange={onChange} />)

    await user.click(await screen.findByText("Résumé — Ada Lovelace"))

    expect(onChange).toHaveBeenCalledWith("data/resumes/profile-1.docx")
  })

  it("uploads a résumé and selects it when it arrives", async () => {
    const onChange = vi.fn()
    const user = userEvent.setup()
    renderScreen(<DocumentPicker value="" onChange={onChange} />)

    const file = new File(["hello"], "resume.txt", { type: "text/plain" })
    await user.upload(screen.getByLabelText("Upload a resume"), file)

    await waitFor(() => {
      expect(onChange).toHaveBeenCalled()
    })
    expect(onChange).toHaveBeenCalledWith(expect.stringContaining("profile-1"))
  })
})
