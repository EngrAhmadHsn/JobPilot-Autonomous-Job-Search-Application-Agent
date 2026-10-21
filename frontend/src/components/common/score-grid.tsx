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
    <div className={cn("space-y-1.5", className)}>
      <div className="flex items-baseline justify-between gap-2">
        <span className="text-xs font-medium text-muted-foreground">
          {label}
        </span>
        <span className="text-xs font-semibold text-foreground tabular-nums">
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
          className="h-full rounded-full bg-primary transition-[width] duration-500 ease-[cubic-bezier(0.22,0.61,0.36,1)]"
          style={{ width: `${clamped}%` }}
        />
      </div>
    </div>
  )
}

/**
 * The overall score.
 *
 * The match score is the agent's own judgement, so it wears the agent's
 * colour: a lime chip, with the number in forest ink.
 */
export function OverallScore({ value }: { value: number }) {
  return (
    <div className="inline-flex items-baseline gap-1.5 rounded-full bg-lime px-3 py-1">
      <span className="text-lg font-semibold text-lime-foreground tabular-nums">
        {formatScore(value)}
      </span>
      <span className="text-[11px] text-lime-foreground/80">match</span>
    </div>
  )
}

/** The six component scores. */
export function ScoreGrid({ match }: { match: JobMatchResult }) {
  return (
    <div className="grid grid-cols-2 gap-x-6 gap-y-4 sm:grid-cols-3">
      {COMPONENTS.map(({ key, label }) => (
        <ScoreBar key={key} label={label} value={Number(match[key] ?? 0)} />
      ))}
    </div>
  )
}
