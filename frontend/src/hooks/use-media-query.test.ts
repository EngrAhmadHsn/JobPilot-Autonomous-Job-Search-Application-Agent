import { renderHook } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"

import { usePointerCapable, useReducedMotion } from "./use-media-query"

/**
 * The motion gate.
 *
 * The queries are the whole control, so they are asserted by name: swapping
 * `any-pointer` back to `pointer` would silently disable the light field on
 * every touchscreen laptop (where the *primary* pointer may be the finger
 * while the visitor is using the trackpad), and nothing else would notice.
 */
describe("the media-query hooks", () => {
  it("asks whether *any* fine pointer is available, not the primary one", () => {
    const spy = vi.spyOn(window, "matchMedia")
    renderHook(() => usePointerCapable())
    expect(spy).toHaveBeenCalledWith("(any-hover: hover) and (any-pointer: fine)")
    spy.mockRestore()
  })

  it("reads the reduced-motion preference", () => {
    const spy = vi.spyOn(window, "matchMedia")
    renderHook(() => useReducedMotion())
    expect(spy).toHaveBeenCalledWith("(prefers-reduced-motion: reduce)")
    spy.mockRestore()
  })

  it("returns the matchMedia answer", () => {
    const spy = vi.spyOn(window, "matchMedia").mockReturnValue({
      matches: true,
      media: "",
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    } as unknown as MediaQueryList)
    const { result } = renderHook(() => usePointerCapable())
    expect(result.current).toBe(true)
    spy.mockRestore()
  })
})
