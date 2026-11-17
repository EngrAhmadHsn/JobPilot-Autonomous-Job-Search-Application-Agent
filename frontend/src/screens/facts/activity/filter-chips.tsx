import { cn } from "cn"

import {
  ACTIVITY_FILTERS,
  type ActivityFilter,
} from "@/screens/facts/activity/filters"

/*
  The Activity Center's filter chips (WS-40, reference panel 7).

  A radio group, not a set of toggle buttons: exactly one chip is active, so
  the semantics tell a screen reader "one of these four" rather than "any
  number of independent switches". The counts come from the caller — the
  server's own rows, never an estimate.
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
      className="flex flex-wrap items-center gap-1.5"
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
              "rounded-full border px-3 py-1 text-xs font-medium transition-colors",
              active
                ? "border-primary bg-primary text-primary-foreground"
                : "border-border bg-card text-muted-foreground hover:bg-accent hover:text-foreground"
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
