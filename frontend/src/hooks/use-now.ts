import { useEffect, useState } from "react"

const FRESH_TICK_MS = 1_000
const MINUTE_TICK_MS = 15_000
const STALE_TICK_MS = 60_000

/** How often a timestamp this old needs re-reading to keep its sentence true. */
function tickDelay(ageMs: number): number {
  if (ageMs < 60_000) return FRESH_TICK_MS
  if (ageMs < 3_600_000) return MINUTE_TICK_MS
  return STALE_TICK_MS
}

/**
 * A ticking "now", owned by the component that needs it.
 *
 * The point of this hook is its **blast radius**: the ticking state lives
 * inside one small component, so a clock that changes every second re-renders
 * that component and nothing else. Screens used to keep a `now` state at the
 * screen level, which re-rendered the whole tree just to age one timestamp.
 *
 * The cadence adapts to the age of the timestamp being displayed — 1 s while
 * it is fresh, 15 s within the hour, 1 min beyond — so "2h ago" is not
 * recomputed every second. The clock is read inside timer callbacks, never
 * during render (the render stays pure), and the tick pauses while the tab is
 * hidden and catches up immediately when it becomes visible again.
 *
 * @param targetMs The timestamp (epoch ms) whose relative age is displayed.
 *   A non-finite value (no timestamp yet) means "do not tick".
 */
export function useNow(targetMs: number): number {
  const [now, setNow] = useState(() => Date.now())

  useEffect(() => {
    if (!Number.isFinite(targetMs)) return
    let timer: number | null = null
    let cancelled = false

    const schedule = () => {
      timer = window.setTimeout(tick, tickDelay(Date.now() - targetMs))
    }
    const tick = () => {
      if (cancelled) return
      setNow(Date.now())
      schedule()
    }
    const start = () => {
      if (timer === null) schedule()
    }
    const stop = () => {
      if (timer !== null) {
        window.clearTimeout(timer)
        timer = null
      }
    }
    const onVisibilityChange = () => {
      stop()
      if (!document.hidden) {
        setNow(Date.now())
        start()
      }
    }

    start()
    document.addEventListener("visibilitychange", onVisibilityChange)
    return () => {
      cancelled = true
      stop()
      document.removeEventListener("visibilitychange", onVisibilityChange)
    }
  }, [targetMs])

  return now
}
