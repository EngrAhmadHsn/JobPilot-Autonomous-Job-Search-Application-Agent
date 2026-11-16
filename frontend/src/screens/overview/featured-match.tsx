import type { LucideIcon } from "lucide-react"
import { Building2Icon, CircleDashedIcon, MapPinIcon } from "lucide-react"
import { cn } from "cn"

import { PlainText } from "@/components/common/plain-text"
import {
  EvidenceCoverage,
  OverallScore,
  ScoreBar,
} from "@/components/common/score-grid"
import { Card, CardContent } from "@/components/ui/card"
import { LinkButton } from "@/components/ui/link-button"

import type { JobListing, JobMatchResult } from "@/lib/api/types"

/*
  The featured opportunity (WS-35) — the reference's "Top Match" card,
  grounded.

  What the reference draws that this card does **not**: the 96% arc (the
  real score is component-weighted and renders as the lime chip the console
  already uses), employer logos (the listing carries text only — a letter
  monogram instead), "Company Fit" (no such component exists — the real
  component states render, and an unknown stays unknown), and the
  Overview/Match Details/Company/… tab row (there is no per-tab data; the
  full breakdown lives one click away on the job's own screen).
*/

/** One component of the featured card's compact breakdown. */
const HIGHLIGHTS: {
  /** The state key (`component_states`) and the score field's name stem. */
  state: string
  field: keyof JobMatchResult
  label: string
}[] = [
  { state: "skill", field: "skill_score", label: "Skills" },
  { state: "experience", field: "experience_score", label: "Experience" },
  { state: "semantic", field: "semantic_score", label: "Semantic fit" },
  { state: "location", field: "location_score", label: "Location" },
]

/*
  The states that mean the component rests on a real measurement, and the
  short, human word for the rest — the same rules `ScoreGrid` applies. They
  are mirrored here (not imported) because `score-grid.tsx` keeps them
  private; the WS-35 report proposes promoting them so every surface shares
  one table. Until then this mirror is kept byte-identical to the original.
*/
const MEASURED = new Set(["MATCHED", "PARTIAL_MATCH", "MISMATCH"])

const UNKNOWN_REASON: Record<string, string> = {
  CANDIDATE_DATA_MISSING: "unknown — you haven't said",
  JOB_REQUIREMENT_MISSING: "unknown — not stated",
  EMBEDDING_PENDING: "pending",
  EMBEDDING_UNAVAILABLE: "unavailable",
  NOT_APPLICABLE: "n/a",
}

/** The first letter of the company name, as the identity block's mark. */
function CompanyMonogram({ company }: { company: string }) {
  const letter = company.trim().charAt(0).toUpperCase() || "?"
  return (
    <span
      aria-hidden="true"
      className="flex size-11 shrink-0 items-center justify-center rounded-lg bg-forest-soft font-heading text-lg font-semibold text-forest"
    >
      {letter}
    </span>
  )
}

/** A real skill signal from the match or the listing, as a chip. */
function SignalChip({
  children,
  tone,
}: {
  children: string
  tone: "match" | "neutral"
}) {
  return (
    <li
      className={cn(
        "inline-flex max-w-full items-center rounded-full border px-2.5 py-0.5 text-xs",
        tone === "match"
          ? "border-lime/70 bg-lime-soft text-lime-foreground"
          : "border-border bg-muted text-muted-foreground"
      )}
    >
      <PlainText as="span" className="text-xs">
        {children}
      </PlainText>
    </li>
  )
}

function MetaItem({
  icon: Icon,
  children,
}: {
  icon: LucideIcon
  children: string
}) {
  return (
    <span className="inline-flex min-w-0 items-center gap-1.5">
      <Icon
        aria-hidden="true"
        className="size-3.5 shrink-0"
        strokeWidth={1.8}
      />
      <PlainText
        as="span"
        className="text-sm wrap-anywhere text-muted-foreground"
      >
        {children}
      </PlainText>
    </span>
  )
}

/**
 * The compact component breakdown, with unknowns kept unknown.
 *
 * A component whose state is not a measured one renders its reason — never
 * the `0.0` the raw score carries for it, because an unknown is not a low
 * score and must not read like one (WS-20).
 */
export function MatchHighlights({ match }: { match: JobMatchResult }) {
  const states = match.component_states ?? {}
  return (
    <div className="space-y-3">
      {HIGHLIGHTS.map(({ state: stateKey, field, label }) => {
        const state = states[stateKey]
        if (state && !MEASURED.has(state)) {
          return (
            <div key={stateKey} className="space-y-1.5">
              <div className="flex items-baseline justify-between gap-2">
                <span className="text-xs font-medium text-muted-foreground">
                  {label}
                </span>
                <span className="text-[11px] text-muted-foreground italic">
                  {UNKNOWN_REASON[state] ?? "unknown"}
                </span>
              </div>
              <div
                aria-hidden="true"
                className="h-1.5 w-full overflow-hidden rounded-full bg-muted"
              >
                <div className="h-full w-0 rounded-full bg-muted-foreground/30" />
              </div>
            </div>
          )
        }
        return (
          <div key={stateKey}>
            <ScoreBar label={label} value={Number(match[field] ?? 0)} />
          </div>
        )
      })}
    </div>
  )
}

export interface FeaturedMatchProps {
  job: JobListing
  match: JobMatchResult
}

export function FeaturedMatch({ job, match }: FeaturedMatchProps) {
  // The chips are the match's own "matched requirements" — the signals the
  // engine actually credited. A match that credited none falls back to the
  // listing's own required skills, marked as what the listing asks for.
  const matched = match.matched_requirements.slice(0, 5)
  const fallbackSkills =
    matched.length === 0 ? job.required_skills.slice(0, 5) : []
  const meta = [
    job.location
      ? { key: "location", icon: MapPinIcon, value: job.location }
      : null,
    job.employment_type
      ? { key: "type", icon: Building2Icon, value: job.employment_type }
      : null,
  ].filter((item): item is { key: string; icon: LucideIcon; value: string } =>
    Boolean(item)
  )

  return (
    <Card className="rounded-2xl">
      <CardContent className="space-y-4">
        <div className="flex items-start justify-between gap-3">
          <div className="flex min-w-0 items-center gap-3">
            <CompanyMonogram company={job.company} />
            <div className="min-w-0">
              <PlainText className="text-sm wrap-anywhere text-muted-foreground">
                {job.company}
              </PlainText>
              <h3 className="font-heading text-xl leading-snug font-semibold tracking-tight text-balance text-foreground">
                <PlainText as="span" className="text-xl">
                  {job.title}
                </PlainText>
              </h3>
            </div>
          </div>
          <div className="flex shrink-0 flex-col items-end gap-1">
            <OverallScore value={match.overall_score} />
          </div>
        </div>

        {meta.length > 0 ? (
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
            {meta.map(({ key, icon, value }) => (
              <MetaItem key={key} icon={icon}>
                {value}
              </MetaItem>
            ))}
          </div>
        ) : null}

        {matched.length > 0 || fallbackSkills.length > 0 ? (
          <ul className="flex flex-wrap gap-1.5">
            {matched.map((item) => (
              <SignalChip key={item} tone="match">
                {item}
              </SignalChip>
            ))}
            {fallbackSkills.map((item) => (
              <SignalChip key={item} tone="neutral">
                {item}
              </SignalChip>
            ))}
          </ul>
        ) : null}

        <div className="grid gap-5 sm:grid-cols-[minmax(0,1fr)_minmax(0,240px)]">
          <div className="min-w-0 space-y-2">
            <p className="text-xs font-medium tracking-wide text-muted-foreground uppercase">
              Why this match
            </p>
            {match.explanation ? (
              <PlainText className="line-clamp-4 max-w-[52ch] text-muted-foreground">
                {match.explanation}
              </PlainText>
            ) : (
              <p className="text-sm text-muted-foreground">
                The matching engine returned no explanation for this listing.
              </p>
            )}
            {match.role_capped ? (
              <p className="text-[11px] text-destructive">
                The listing's role is unrelated to the candidate's target roles,
                so the overall score is capped.
              </p>
            ) : null}
            <EvidenceCoverage value={match.evidence_coverage} />
          </div>
          <MatchHighlights match={match} />
        </div>

        <div className="flex flex-wrap items-center gap-2 border-t border-border pt-4">
          <LinkButton to={`/app/tailor/${encodeURIComponent(job.id)}`}>
            Tailor for this job
          </LinkButton>
          <LinkButton
            to={`/app/matches/${encodeURIComponent(job.id)}`}
            variant="outline"
          >
            View details
          </LinkButton>
        </div>
      </CardContent>
    </Card>
  )
}

/**
 * The featured slot while the job listing is on the way, or when the top
 * match's listing can no longer be read (a corpus that moved on). Both are
 * honest frames — the first reserves the card's shape, the second says what
 * happened and links to the screen that re-runs the search.
 */
export function FeaturedMatchSkeleton() {
  return (
    <Card className="rounded-2xl" aria-busy="true">
      <CardContent className="space-y-4">
        <div className="flex items-center gap-3">
          <div
            aria-hidden="true"
            className="size-11 shrink-0 rounded-lg bg-muted"
          />
          <div className="flex-1 space-y-2">
            <div aria-hidden="true" className="h-5 w-2/3 rounded bg-muted" />
            <div aria-hidden="true" className="h-4 w-1/3 rounded bg-muted" />
          </div>
        </div>
        <div aria-hidden="true" className="h-3 w-1/2 rounded bg-muted" />
        <div aria-hidden="true" className="h-20 rounded-xl bg-muted/60" />
      </CardContent>
    </Card>
  )
}

export function FeaturedMatchMissing() {
  return (
    <div className="flex flex-col items-center justify-center gap-3 rounded-xl border border-dashed border-border bg-card/60 px-6 py-10 text-center">
      <span
        aria-hidden="true"
        className="flex size-10 items-center justify-center rounded-full bg-muted text-muted-foreground"
      >
        <CircleDashedIcon className="size-5" strokeWidth={1.6} />
      </span>
      <div className="max-w-[48ch]">
        <h3 className="font-heading text-base font-semibold text-foreground">
          The top match's listing can't be shown
        </h3>
        <p className="mt-1.5 text-sm leading-relaxed text-muted-foreground">
          The ranked match exists, but its listing did not answer. Run a fresh
          search on Matches — the ranking is rebuilt from what the corpus holds
          now.
        </p>
      </div>
      <div className="mt-1 flex items-center gap-2">
        <LinkButton to="/app/matches" variant="outline" size="sm">
          Open Matches
        </LinkButton>
      </div>
    </div>
  )
}
