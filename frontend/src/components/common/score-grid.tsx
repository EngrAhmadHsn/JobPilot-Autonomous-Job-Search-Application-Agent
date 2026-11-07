import { cn } from "cn"

import { formatScore } from "@/lib/format"
import type { JobMatchResult } from "@/lib/api/types"

/**
 * The seven component scores, in the order the matching engine produces them.
 *
 * The overall score alone would be a number the operator cannot argue with;
 * the components are what makes the ranking explainable.
 */
const COMPONENTS: { key: keyof JobMatchResult; name: string; label: string }[] =
  [
    { key: "semantic_score", name: "semantic", label: "Semantic" },
    { key: "lexical_score", name: "lexical", label: "Keywords" },
    { key: "skill_score", name: "skill", label: "Skills" },
    { key: "experience_score", name: "experience", label: "Experience" },
    { key: "seniority_score", name: "seniority", label: "Seniority" },
    { key: "location_score", name: "location", label: "Location" },
    { key: "preference_score", name: "preference", label: "Preferences" },
  ]

/** The states that mean the component rests on a real measurement. */
const MEASURED = new Set(["MATCHED", "PARTIAL_MATCH", "MISMATCH"])

/** A short, human word for a non-measured state. */
const UNKNOWN_LABEL: Record<string, string> = {
  CANDIDATE_DATA_MISSING: "unknown — you haven't said",
  JOB_REQUIREMENT_MISSING: "unknown — not stated",
  EMBEDDING_PENDING: "pending",
  EMBEDDING_UNAVAILABLE: "unavailable",
  NOT_APPLICABLE: "n/a",
}

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
 * A component that rests on no evidence.
 *
 * WS-20: a missing signal is shown as *unknown* with the reason, never as a
 * number — an unknown is not a low score and must not read like one.
 */
function UnknownBar({ label, reason }: { label: string; reason: string }) {
  return (
    <div className="space-y-1.5">
      <div className="flex items-baseline justify-between gap-2">
        <span className="text-xs font-medium text-muted-foreground">
          {label}
        </span>
        <span className="text-[11px] italic text-muted-foreground">
          {reason}
        </span>
      </div>
      <div className="h-1.5 w-full overflow-hidden rounded-full bg-muted">
        <div className="h-full w-0 rounded-full bg-muted-foreground/30" />
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

/**
 * How much of the score rests on actual information (WS-20).
 *
 * A score and its evidence coverage belong together: 71 from six measured
 * components is a different claim from 71 built mostly from unknowns.
 */
export function EvidenceCoverage({ value }: { value: number }) {
  return (
    <p className="text-[11px] text-muted-foreground">
      Based on {formatScore(value)}% of the available signals.
    </p>
  )
}

/** The component scores, with unknowns shown as such. */
export function ScoreGrid({ match }: { match: JobMatchResult }) {
  const states = match.component_states ?? {}
  return (
    <div className="space-y-3">
      <div className="grid grid-cols-1 gap-x-6 gap-y-4 sm:grid-cols-2 lg:grid-cols-3">
        {COMPONENTS.map(({ key, name, label }) => {
          const state = states[name]
          if (state && !MEASURED.has(state)) {
            return (
              <UnknownBar
                key={key}
                label={label}
                reason={UNKNOWN_LABEL[state] ?? "unknown"}
              />
            )
          }
          return (
            <ScoreBar key={key} label={label} value={Number(match[key] ?? 0)} />
          )
        })}
      </div>
      <EvidenceCoverage value={Number(match.evidence_coverage ?? 0)} />
    </div>
  )
}