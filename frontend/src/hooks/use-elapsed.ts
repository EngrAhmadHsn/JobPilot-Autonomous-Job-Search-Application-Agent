import { useEffect, useState } from "react"

/**
 * The seconds since a call started.
 *
 * The long calls in this console take real time (a search ~10 s, a tailoring
 * run ~80 s, a refresh minutes). A spinner with no number reads as a hang;
 * a number tells the operator whether to wait or to look at the server.
 *
 * The count starts when the component that uses the hook is **mounted**, so
 * a new run must remount it: give the component a `key` that changes per
 * run. Without that, the previous run's elapsed time would be shown for up
 * to a second — a small lie, and the console does not tell small lies.
 */
export function useElapsed(active: boolean, intervalMs = 1000): number {
  const [seconds, setSeconds] = useState(0)

  useEffect(() => {
    if (!active) return
    const timer = window.setInterval(
      () => setSeconds((value) => value + 1),
      intervalMs
    )
    return () => window.clearInterval(timer)
  }, [active, intervalMs])

  return active ? seconds : 0
}
