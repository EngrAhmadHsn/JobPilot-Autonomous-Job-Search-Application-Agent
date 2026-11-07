import { act, renderHook } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { useNow } from "@/hooks/use-now"

describe("useNow", () => {
  let hiddenDescriptor: PropertyDescriptor | undefined

  beforeEach(() => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date("2026-11-08T10:00:00.000Z"))
    hiddenDescriptor = Object.getOwnPropertyDescriptor(document, "hidden")
  })

  afterEach(() => {
    if (hiddenDescriptor) {
      Object.defineProperty(document, "hidden", hiddenDescriptor)
    }
    vi.useRealTimers()
  })

  function setHidden(hidden: boolean) {
    Object.defineProperty(document, "hidden", {
      configurable: true,
      get: () => hidden,
    })
  }

  it("ticks once a second while the timestamp is fresh", () => {
    const { result } = renderHook(() => useNow(Date.now()))
    const first = result.current
    act(() => {
      vi.advanceTimersByTime(1_000)
    })
    expect(result.current).toBeGreaterThan(first)
  })

  it("does not tick without a timestamp", () => {
    const { result } = renderHook(() => useNow(Number.NaN))
    const first = result.current
    const before = vi.getTimerCount()
    act(() => {
      vi.advanceTimersByTime(5_000)
    })
    expect(result.current).toBe(first)
    expect(vi.getTimerCount()).toBe(before)
  })

  it("uses a coarser cadence for an older timestamp", () => {
    const { result } = renderHook(() => useNow(Date.now() - 90_000))
    const first = result.current
    act(() => {
      vi.advanceTimersByTime(5_000)
    })
    // The minute-scale cadence has not come due yet.
    expect(result.current).toBe(first)
    act(() => {
      vi.advanceTimersByTime(10_000)
    })
    expect(result.current).toBeGreaterThan(first)
  })

  it("pauses while the tab is hidden and catches up when it returns", () => {
    const { result } = renderHook(() => useNow(Date.now()))
    const first = result.current
    act(() => {
      setHidden(true)
      document.dispatchEvent(new Event("visibilitychange"))
    })
    act(() => {
      vi.advanceTimersByTime(5_000)
    })
    expect(result.current).toBe(first)
    act(() => {
      setHidden(false)
      document.dispatchEvent(new Event("visibilitychange"))
    })
    // Caught up at once — the returned clock reflects the true time again.
    expect(result.current).toBe(Date.now())
    expect(result.current).toBeGreaterThan(first)
    // And it keeps ticking.
    act(() => {
      vi.advanceTimersByTime(1_000)
    })
    expect(result.current).toBeGreaterThan(first)
  })

  it("cleans up its timer on unmount", () => {
    const { unmount } = renderHook(() => useNow(Date.now()))
    const before = vi.getTimerCount()
    unmount()
    expect(vi.getTimerCount()).toBe(before - 1)
  })
})
