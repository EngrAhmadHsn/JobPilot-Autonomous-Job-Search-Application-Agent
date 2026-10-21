import { cn } from "cn"

import { formatScore } from "@/lib/format"
import type { JobMatchResult } from "@/lib/api/types"

/**
 * The six component scores, in the order the matching engine produces them.
 *
 * The overall score alone would be a number the operator cannot argue with;
 * the six components are what makes the ranking explainable.
 */
const COMPONENTS: { key: keyof JobMatchResult; label: string }[] = [
  { key: "semantic_score", label: "Semantic" },
  { key: "skill_score", label: "Skills" },
  { key: "experience_score", label: "Experience" },
  { key: "seniority_score", label: "Seniority" },
  { key: "location_score", label: "Location" },
  { key: "preference_score", label: "Preferences" },
]

/** A single score, as a bar and a number. */
export function ScoreBar({
  label,
  value,
  className,
}: {
  label: string
  value: number
  className?: string
}) {
  const clamped = Math.max(0, Math.min(100, value))
  return (
    <div className={cn("space-y-1", className)}>
      <div className="flex items-baseline justify-between gap-2">
        <span className="text-xs font-medium text-muted-foreground">
          {label}
        </span>
        <span className="text-xs font-semibold tabular-nums">
          {formatScore(value)}
        </span>
      </div>
      <div
        role="meter"
        aria-label={label}
        aria-valuenow={Math.round(clamped)}
        aria-valuemin={0}
        aria-valuemax={100}
        className="h-1.5 w-full overflow-hidden rounded-full bg-muted"
      >
        <div
          className="h-full rounded-full bg-primary"
          style={{ width: `${clamped}%` }}
        />
      </div>
    </div>
  )
}

/** The overall score, prominently. */
export function OverallScore({ value }: { value: number }) {
  return (
    <div className="flex items-baseline gap-1.5">
      <span className="text-2xl font-semibold tabular-nums">
        {formatScore(value)}
      </span>
      <span className="text-xs text-muted-foreground">/ 100 overall</span>
    </div>
  )
}

/** The six component scores. */
export function ScoreGrid({ match }: { match: JobMatchResult }) {
  return (
    <div className="grid grid-cols-2 gap-x-4 gap-y-3 sm:grid-cols-3">
      {COMPONENTS.map(({ key, label }) => (
        <ScoreBar key={key} label={label} value={Number(match[key] ?? 0)} />
      ))}
    </div>
  )
}
