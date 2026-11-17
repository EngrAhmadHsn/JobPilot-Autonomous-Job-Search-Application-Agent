import { EvidenceCoverage, ScoreGrid } from "@/components/common/score-grid"
import { MatchGapChips } from "@/components/common/match-gap-chips"
import { Disclosure } from "@/components/common/disclosure"
import { PlainText } from "@/components/common/plain-text"

import { SponsorSignal } from "@/screens/discover/sponsor-signal"

import type { JobMatchResult } from "@/lib/api/types"

/*
  The match's reasoning, as one block (WS-36).

  The overall score is a number the operator cannot argue with; the reasoning
  is what makes it explainable. This block renders it in the order a person
  reads it: the engine's own explanation, how much of the score rests on real
  evidence, the requirements it credited and the ones it could not, the
  sponsorship finding, and — progressively, per the workstream's rule that
  deeper scoring detail is expandable rather than eight bars per card — the
  full component breakdown.

  `breakdown` controls the component grid:
  - "disclosed": the Discover panel's mode. The grid sits in a disclosure, so
    the panel stays at the reference's density; unknown components still render
    as unknown with their reason once opened (`ScoreGrid` owns that rule).
  - "expanded": the job-detail route's mode. The route's whole purpose is the
    full reasoning, so the grid renders in place.

  The gap line is the workstream's framing rule: a missing requirement is an
  evidence gap — the profile does not state it — which is not a
  disqualification. It renders only when there is at least one missing item,
  so it never explains an empty list.
*/
export function MatchReasoning({
  match,
  breakdown,
}: {
  match: JobMatchResult
  breakdown: "disclosed" | "expanded"
}) {
  const hasMissing = match.missing_requirements.length > 0
  return (
    <div className="space-y-4">
      {match.explanation ? (
        <PlainText className="max-w-[68ch] leading-relaxed text-foreground">
          {match.explanation}
        </PlainText>
      ) : (
        <p className="text-sm text-muted-foreground">
          The matching engine returned no explanation for this listing.
        </p>
      )}

      {/*
        The evidence-coverage line renders exactly once. In the expanded
        breakdown `ScoreGrid` closes with its own; in the disclosed mode the
        grid sits inside the disclosure, so the line stands here, visible
        before anything is opened.
      */}
      {breakdown === "disclosed" ? (
        <>
          <EvidenceCoverage value={match.evidence_coverage} />
          {match.role_capped ? (
            <p className="text-[11px] text-destructive">
              The listing&apos;s role is unrelated to the candidate&apos;s
              target roles, so the overall score is capped.
            </p>
          ) : null}
          <Disclosure
            summary="Show the full scoring breakdown"
            hint="all eight components and their states"
          >
            <ScoreGrid match={match} showCoverage={false} showRoleCap={false} />
          </Disclosure>
        </>
      ) : (
        <ScoreGrid match={match} />
      )}

      <MatchGapChips
        matched={match.matched_requirements}
        missing={match.missing_requirements}
      />
      {hasMissing ? (
        <p className="text-xs leading-relaxed text-muted-foreground">
          A missing requirement is an evidence gap — the profile does not state
          it, which is not the same as lacking it. It is not a disqualification.
        </p>
      ) : null}

      <SponsorSignal status={match.sponsor_status} note={match.sponsor_note} />
    </div>
  )
}
