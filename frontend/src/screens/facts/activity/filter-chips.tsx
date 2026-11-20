import { cn } from "cn"

import {
  ACTIVITY_FILTERS,
  type ActivityFilter,
} from "@/screens/facts/activity/filters"

/*
  The Activity screen's filter chips (WS-40, rebuilt to the design file's
  screen `16:242` in WS-42).

  A radio group, not a set of toggle buttons: exactly one chip is active, so
  the semantics tell a screen reader "one of these" rather than "any number
  of independent switches". The look is the design's pill row — the active
  chip forest-filled — and the counts come from the caller: the server's own
  rows, never an estimate.
*/
export function ActivityFilters({
  value,
  onChange,
  counts,
}: {
  value: ActivityFilter
  onChange: (next: ActivityFilter) => void
  /** How many rows each chip would show, for the chip's own label. */
  counts: Record<ActivityFilter, number>
}) {
  return (
    <div
      role="radiogroup"
      aria-label="Filter the trail"
      className="flex flex-wrap items-center gap-2.5"
    >
      {ACTIVITY_FILTERS.map((filter) => {
        const active = filter.value === value
        return (
          <button
            key={filter.value}
            type="button"
            role="radio"
            aria-checked={active}
            onClick={() => onChange(filter.value)}
            className={cn(
              "inline-flex h-[37px] items-center rounded-lg px-3.5 py-2 text-[13px] font-semibold leading-[19px] transition-colors outline-none focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring",
              active
                ? "bg-primary text-primary-foreground"
                : "border border-border-surface bg-card text-primary hover:bg-accent"
            )}
          >
            {filter.label}
            <span
              className={cn(
                "ml-1.5 tabular-nums",
                active ? "opacity-75" : "opacity-60"
              )}
            >
              {counts[filter.value]}
            </span>
          </button>
        )
      })}
    </div>
  )
}
