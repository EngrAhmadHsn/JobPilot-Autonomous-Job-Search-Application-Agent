import { cn } from "cn"

import { EvidenceCoverage, ScoreGrid } from "@/components/common/score-grid"
import { Disclosure } from "@/components/common/disclosure"
import { PlainText } from "@/components/common/plain-text"

import { SponsorSignal } from "@/screens/discover/sponsor-signal"

import type { JobMatchResult } from "@/lib/api/types"

/*
  The fit card's body, rebuilt to the design (WS-42): the engine's narrative,
  the matched requirements as lime chips (node `49:1922`), the evidence-gap
  panel in the clay wash (`49:1929` route, `49:939` panel), and — in the
  route's expanded mode — the "How the match is explained" rationale rows
  (`49:1934`). The Discover panel keeps the reasoning one disclosure deep
  (node `49:944`'s "See all 8 score components and evidence"), so the panel
  stays at the reference's density.

  The overall score is a number the operator cannot argue with; this block is
  what makes it explainable. Two honesty rules hold against the design's
  example content: every string here is either the engine's own output or
  fixed UI copy, and an unknown component renders its reason — never the
  raw 0.0 (`ScoreGrid` owns that rule).

  `breakdown` controls the component grid:
  - "disclosed": the Discover panel's mode. The grid sits in a disclosure;
    the sponsorship finding renders as the design's single quiet line
    (`49:943`) — the route's rail owns the fuller guardrails block.
  - "expanded": the job-detail route's mode. The route's whole purpose is the
    full reasoning, so the rows render in place under their heading.
*/

/**
 * The verdict slot (node `49:1920` — the design's "A good fit, with one
 * gap."), derived from the match record and nothing else: a MISMATCH
 * anywhere holds the claim at "a partial match", and every missing
 * requirement is named as a gap. No threshold is invented — the words track
 * the engine's own component verdicts and the recorded gaps.
 */
export function fitVerdict(match: JobMatchResult): string {
  const states = Object.values(match.component_states ?? {})
  const partial = states.some((state) => state === "MISMATCH")
  const gaps = match.missing_requirements.length
  const tail =
    gaps === 0 ? "" : gaps === 1 ? ", with one gap" : `, with ${gaps} gaps`
  return `${partial ? "A partial match" : "A good fit"}${tail}.`
}

/** The matched requirements, as the design's lime chips (`49:1922`). */
function MatchedSkillChips({ items }: { items: string[] }) {
  if (items.length === 0) return null
  return (
    <ul className="flex flex-wrap gap-3">
      {items.map((item) => (
        <li
          key={item}
          className="inline-flex max-w-full items-center rounded-[6px] bg-lime-soft px-[9px] py-1"
        >
          <PlainText as="span" className="text-[11px] font-semibold leading-4 text-lime-foreground">
            {item}
          </PlainText>
        </li>
      ))}
    </ul>
  )
}

/**
 * The evidence-gap panel: a clay wash naming what the listing asks for that
 * the source résumé does not state — an evidence gap, never a
 * disqualification. The route variant carries the design's framing line;
 * the panel variant uses the compact chip-and-line anatomy. Renders nothing
 * when nothing is missing: a wash explaining an empty list is noise.
 */
function EvidenceGapPanel({
  missing,
  variant,
}: {
  missing: string[]
  variant: "panel" | "route"
}) {
  if (missing.length === 0) return null
  const items = missing.join(", ")
  if (variant === "panel") {
    return (
      <div className="rounded-surface bg-terracotta-soft p-3.5">
        <p className="text-[11px] font-semibold uppercase leading-4 tracking-wide text-forest">
          Evidence gap
        </p>
        <PlainText className="mt-1.5 block text-[13px] leading-[19px] text-terracotta-foreground">
          {`${items} not found in your source résumé`}
        </PlainText>
      </div>
    )
  }
  return (
    <div className="space-y-2 rounded-surface bg-terracotta-soft p-4">
      <PlainText className="text-[15px] font-semibold leading-[22px] text-terracotta-foreground">
        {missing.length === 1
          ? `${items} is not in your source résumé.`
          : `${items} are not in your source résumé.`}
      </PlainText>
      <p className="text-[13px] leading-[19px] text-terracotta-foreground">
        An evidence gap, not a reason to invent experience.
      </p>
    </div>
  )
}

export function MatchReasoning({
  match,
  breakdown,
}: {
  match: JobMatchResult
  breakdown: "disclosed" | "expanded"
}) {
  const isPanel = breakdown === "disclosed"
  return (
    <div className="space-y-4">
      {match.explanation ? (
        <PlainText
          className={cn(
            "max-w-[68ch] text-muted-foreground",
            isPanel
              ? "text-[15px] leading-[22px]"
              : "text-base leading-[23px]"
          )}
        >
          {match.explanation}
        </PlainText>
      ) : (
        <p className="text-sm text-muted-foreground">
          The matching engine returned no explanation for this listing.
        </p>
      )}

      <MatchedSkillChips items={match.matched_requirements} />

      <EvidenceGapPanel
        missing={match.missing_requirements}
        variant={isPanel ? "panel" : "route"}
      />

      {isPanel ? (
        <>
          {/*
            The evidence-coverage line renders exactly once per mode: here,
            visible before anything is opened, because the grid itself sits
            inside the disclosure.
          */}
          <EvidenceCoverage value={match.evidence_coverage} />
          {match.role_capped ? (
            <p className="text-[11px] text-destructive">
              The listing&apos;s role is unrelated to the candidate&apos;s
              target roles, so the overall score is capped.
            </p>
          ) : null}
          <SponsorSignal status={match.sponsor_status} note={match.sponsor_note} />
          <Disclosure
            summary="See all 8 score components and evidence"
            hint="every component's state, in words"
          >
            <ScoreGrid match={match} showCoverage={false} showRoleCap={false} />
          </Disclosure>
        </>
      ) : (
        <>
          {/*
            The route's own "How the match is explained" block (`49:1932`):
            a divider, the heading, and the rationale rows in place. The
            grid closes with the role-cap line and the evidence coverage.
          */}
          <div className="space-y-4 border-t border-border-surface pt-5">
            <h3 className="text-[19px] font-semibold leading-[28px] text-forest">
              How the match is explained
            </h3>
            <ScoreGrid match={match} />
          </div>
        </>
      )}
    </div>
  )
}
