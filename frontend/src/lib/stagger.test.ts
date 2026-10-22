import type { CSSProperties } from "react"
import { describe, expect, it } from "vitest"

import { stagger } from "@/lib/stagger"

/**
 * The stagger.
 *
 * A list that arrives all at once reads as a wall; a list that arrives one
 * row after another reads as a sequence. The delay is the item's index, so
 * the order the operator sees is the order the data has.
 */
describe("the stagger", () => {
  it("marks the item for the entrance", () => {
    expect(stagger(0).className).toContain("enter-up")
  })

  it("gives each item its own delay", () => {
    const index = (style: CSSProperties) =>
      (style as Record<string, string | number>)["--i"]
    expect(index(stagger(0).style)).toBe(0)
    expect(index(stagger(4).style)).toBe(4)
  })

  it("keeps the caller's own classes", () => {
    expect(stagger(1, "rounded-2xl").className).toContain("rounded-2xl")
  })
})
