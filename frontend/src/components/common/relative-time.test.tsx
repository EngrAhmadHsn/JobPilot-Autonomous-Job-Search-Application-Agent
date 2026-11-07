import { act, render, screen } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { RelativeTime } from "@/components/common/relative-time"

describe("RelativeTime", () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date("2026-11-08T10:00:00.000Z"))
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it("ages a fresh timestamp as the clock moves", () => {
    render(<RelativeTime value="2026-11-08T10:00:00.000Z" />)
    expect(screen.getByText("just now")).toBeInTheDocument()

    act(() => {
      vi.advanceTimersByTime(6_000)
    })
    expect(screen.getByText("6s ago")).toBeInTheDocument()
  })

  it("renders an em dash for null without scheduling a clock", () => {
    render(<RelativeTime value={null} />)
    expect(screen.getByText("—")).toBeInTheDocument()

    const before = vi.getTimerCount()
    act(() => {
      vi.advanceTimersByTime(5_000)
    })
    expect(vi.getTimerCount()).toBe(before)
  })

  it("shows the absolute timestamp in the tooltip", () => {
    render(<RelativeTime value="2026-11-08T09:30:00.000Z" />)
    expect(screen.getByText("30m ago")).toHaveAttribute("title")
  })

  it("keeps ticking inside its own component, never the parent screen", () => {
    /*
      The defect this pins: the elapsed clock used to live at the screen
      level, so every tick re-rendered the whole tree. The tick must now be
      contained in the timestamp's own component.
    */
    let parentRenders = 0
    function ParentProbe() {
      parentRenders += 1
      return null
    }

    render(
      <>
        <ParentProbe />
        <RelativeTime value="2026-11-08T10:00:00.000Z" />
      </>
    )
    const parentRendersAfterMount = parentRenders

    act(() => {
      vi.advanceTimersByTime(10_000)
    })

    expect(screen.getByText("10s ago")).toBeInTheDocument()
    expect(parentRenders).toBe(parentRendersAfterMount)
  })
})
