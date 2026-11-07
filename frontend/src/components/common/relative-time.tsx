import { useNow } from "@/hooks/use-now"
import { formatDateTime } from "@/lib/format"
import { formatRelativeTime } from "@/lib/observability"

/**
 * A "how long ago" timestamp that ages on its own.
 *
 * The server is the authority on *when* something happened; this component is
 * only the clock that keeps the sentence true between polls. It ticks at the
 * precision of its own text (see `use-now.ts`), so a page of timestamps costs
 * a handful of timers, never a screen-wide re-render.
 *
 * It keeps ticking after polling stops (a finished run's "started 12m ago"),
 * which is exactly when a polling-driven clock would freeze — the run detail
 * poll stops the moment a run becomes terminal.
 */
export function RelativeTime({
  value,
  className,
}: {
  /** The authoritative ISO timestamp, or null when nothing is known yet. */
  value: string | null | undefined
  className?: string
}) {
  const parsed = value ? Date.parse(value) : Number.NaN
  const now = useNow(parsed)

  return (
    <span
      className={className}
      title={value ? formatDateTime(value) : undefined}
    >
      {formatRelativeTime(value, now)}
    </span>
  )
}
