import { cn } from "cn"

import { formatList, formatScore } from "@/lib/format"
import type { JobMatchResult } from "@/lib/api/types"

/**
 * The component scores, in the order the design's "How the match is
 * explained" rows draw them (WS-42, node `49:1934`): Semantic, Skill,
 * Experience, Seniority, Location, Preference, Lexical, Occupational role.
 *
 * The overall score alone would be a number the operator cannot argue with;
 * the components are what makes the ranking explainable. WS-21 appends the
 * occupational-role component: whether the listing is the *kind of work* the
 * candidate's target roles describe.
 */
const COMPONENTS: { key: keyof JobMatchResult; name: string; label: string }[] =
  [
    { key: "semantic_score", name: "semantic", label: "Semantic" },
    { key: "skill_score", name: "skill", label: "Skill" },
    { key: "experience_score", name: "experience", label: "Experience" },
    { key: "seniority_score", name: "seniority", label: "Seniority" },
    { key: "location_score", name: "location", label: "Location" },
    { key: "preference_score", name: "preference", label: "Preference" },
    { key: "lexical_score", name: "lexical", label: "Lexical" },
    { key: "role_score", name: "role", label: "Occupational role" },
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

/**
 * The engine's own component verdicts, in words. The state is the matching
 * engine's vocabulary, so the rationale never claims more than the engine
 * computed — it translates it.
 */
const STATE_PHRASE: Record<string, string> = {
  MATCHED: "Lines up with your profile.",
  PARTIAL_MATCH: "Partially lines up with your profile.",
  MISMATCH: "Does not line up with your profile.",
}

/**
 * The chip number, as the design draws it: a whole score ("86"), never a
 * decimal. Local to this module on purpose — `lib/format.ts` is shared and
 * the one-decimal `formatScore` stays the breakdown's secondary rendering.
 */
function wholeScore(value: number): string {
  return String(Math.round(value))
}

/**
 * What one component's row says, from the match record alone.
 *
 * A measured component states the engine's verdict in words — sharpened,
 * where the record carries real evidence, by what was actually found. A
 * component that rests on no evidence states *that* instead, with the
 * reason: an unknown is not a low score and must never read as one (WS-20).
 * A persisted row that predates the component states carries no verdict at
 * all; its defaulted zero is likewise an unknown, never a number.
 */
function rationaleFor(
  match: JobMatchResult,
  name: string,
  state: string | undefined,
  value: number
): { text: string; unknown: boolean } {
  if (state && !MEASURED.has(state)) {
    return { text: UNKNOWN_LABEL[state] ?? "unknown", unknown: true }
  }
  if (!state && value === 0) {
    return { text: "unknown", unknown: true }
  }
  if (state === "MATCHED") {
    if (name === "skill" && match.matched_requirements.length > 0) {
      return {
        text: `${formatList(match.matched_requirements)} found in your source résumé.`,
        unknown: false,
      }
    }
    if (name === "lexical" && match.matched_keywords.length > 0) {
      return {
        text: `Keyword overlap: ${match.matched_keywords.join(", ")}.`,
        unknown: false,
      }
    }
    if (name === "role" && match.role_targets.length > 0) {
      return {
        text: `Compared against your target role: ${match.role_targets.join(", ")}.`,
        unknown: false,
      }
    }
  }
  return {
    text: STATE_PHRASE[state as keyof typeof STATE_PHRASE] ??
      "Measured against your profile.",
    unknown: false,
  }
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
 * The overall score, as the design's chip (nodes `49:878`, `49:924`,
 * `49:1910`): a lime chip carrying the whole number and its scale —
 * "86 / 100 match" — in one line.
 *
 * The match score is the agent's own judgement, so it wears the agent's
 * colour. The chip rounds for display only; the full precision stays with
 * the breakdown rows below it.
 */
export function OverallScore({ value }: { value: number }) {
  return (
    <span className="inline-flex max-w-full shrink-0 items-center rounded-[6px] bg-lime-soft px-[9px] py-1 text-[11px] font-semibold leading-4 text-lime-foreground tabular-nums">
      {wholeScore(value)} / 100 match
    </span>
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

/**
 * The component scores as the design's explanation rows (node `49:1934`) —
 * a label (12/600, muted) beside a one-line rationale (13/400, forest ink),
 * two equal columns. The component's number rides along as a quiet
 * secondary rendering: the prose is the explanation, the number is the
 * measurement behind it.
 *
 * `showCoverage` / `showRoleCap` exist for one caller: the disclosed mode in
 * `MatchReasoning` renders those two lines itself, visible before the
 * disclosure is opened. With them suppressed here, each line still renders
 * exactly once per mode — the invariant that comment claims (WS-36 review
 * fix). Both default to true, so the expanded breakdown is unchanged.
 */
export function ScoreGrid({
  match,
  showCoverage = true,
  showRoleCap = true,
}: {
  match: JobMatchResult
  showCoverage?: boolean
  showRoleCap?: boolean
}) {
  const states = match.component_states ?? {}
  return (
    <div className="space-y-4">
      <div className="space-y-4">
        {COMPONENTS.map(({ key, name, label }) => {
          const state = states[name]
          const value = Number(match[key] ?? 0)
          const { text, unknown } = rationaleFor(match, name, state, value)
          return (
            <div
              key={key}
              className="grid grid-cols-1 gap-x-6 gap-y-0.5 sm:grid-cols-2"
            >
              <span className="text-xs font-semibold leading-[17px] text-muted-foreground">
                {label}
              </span>
              {unknown ? (
                <span className="text-[13px] italic leading-[19px] text-muted-foreground">
                  {text}
                </span>
              ) : (
                <span className="min-w-0 text-[13px] leading-[19px] text-forest">
                  {text}
                  <span className="ms-2 text-muted-foreground tabular-nums">
                    {formatScore(value)}
                  </span>
                </span>
              )}
            </div>
          )
        })}
      </div>
      {showRoleCap && match.role_capped ? (
        <p className="text-[11px] text-destructive">
          The listing's role is unrelated to the candidate's target roles, so
          the overall score is capped.
        </p>
      ) : null}
      {showCoverage ? (
        <EvidenceCoverage value={Number(match.evidence_coverage ?? 0)} />
      ) : null}
    </div>
  )
}
