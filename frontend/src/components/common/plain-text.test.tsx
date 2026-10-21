import { render } from "@testing-library/react"
import { describe, expect, it } from "vitest"

import { PlainText } from "@/components/common/plain-text"

/**
 * The untrusted-text rule, as a test.
 *
 * The backend returns job descriptions, tailored text and confirmation
 * messages that came from a third party. The console renders them as
 * plain text. This test proves that a hostile description is shown, and
 * shown *as text* — not executed, not parsed, not turned into an element.
 */
describe("PlainText", () => {
  it("renders a hostile description as text and does not execute it", () => {
    const hostile =
      '<script>window.__pwned = true</script><img src=x onerror="window.__pwned = true">'

    const { container } = render(<PlainText>{hostile}</PlainText>)

    expect(container.textContent).toContain("<script>")
    expect(container.querySelector("script")).toBeNull()
    expect(container.querySelector("img")).toBeNull()
    expect((window as unknown as { __pwned?: boolean }).__pwned).toBeUndefined()
  })

  it("keeps the line breaks of a multi-line text", () => {
    const { container } = render(
      <PlainText as="pre">{"line one\nline two"}</PlainText>
    )
    expect(container.querySelector("pre")?.textContent).toBe(
      "line one\nline two"
    )
  })
})
