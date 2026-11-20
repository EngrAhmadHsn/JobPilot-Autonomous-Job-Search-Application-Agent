import { CircleDashedIcon } from "lucide-react"

import { PlainText } from "@/components/common/plain-text"
import { LinkButton } from "@/components/ui/link-button"

import type { JobListing, JobMatchResult } from "@/lib/api/types"

/*
  The featured opportunity (WS-35), rebuilt to the design's "Recommended role"
  card (node 49:836): forest ground, a lime-soft score chip, the title, one
  meta line, the match's own rationale, and a single action.

  What the design draws that this card does **not** invent: the rationale is
  the backend's explanation text — when a required skill is missing the card
  states the absence ("Kubernetes experience is not in the source résumé")
  instead of softening it, because a candidate who is told "strong fit" and
  then finds a gap in the interview was misled by us. The component-score
  breakdown the old card carried lives on the match's own screen (the design
  puts it there, on 47:488) — and with it the WS-20 rule that an unknown
  component renders its reason, never the raw 0.0.

  A role-capped score keeps its warning: a capped "81 / 100" without the cap
  line would overstate the fit.
*/

export interface FeaturedMatchProps {
  job: JobListing
  match: JobMatchResult
}

export function FeaturedMatch({ job, match }: FeaturedMatchProps) {
  const meta = [job.company, job.location, job.employment_type]
    .filter((part): part is string => Boolean(part))
    .join(" · ")

  return (
    <div className="rounded-[var(--radius-surface)] bg-primary p-5">
      {/*
        The design's chip is the lime **soft wash** on forest (node 49:837),
        not the solid lime — solid lime is the agent's action colour, and a
        score is a measurement, not an action.
      */}
      <span className="type-eyebrow inline-block rounded-md bg-lime-soft px-2 py-1 text-forest">
        {Math.round(match.overall_score)} / 100 match
      </span>
      {/*
        WS-43: the card's text colours are carried **inside** the
        `PlainText` spans, not only on the wrappers around them. `PlainText`
        paints its own `text-foreground` — right for untrusted text on the
        paper surfaces, but on this card it silently replaced the wrappers'
        `text-primary-foreground` and dropped dark ink onto the forest
        ground (and pale ink onto the dark theme's lime card). Passing the
        colour through is the fix at the cause: the span is the element the
        reader's eye sees, so the span is where the card's foreground
        belongs. (Measured against `01 · Home · 1440`: title paper-white,
        meta and rationale the /80 wash — in both themes, where `bg-primary`
        flips forest→lime and the foreground flips with it.)
      */}
      <h3 className="mt-2.5 text-[21px] leading-[30px] font-semibold text-balance text-primary-foreground">
        <PlainText
          as="span"
          className="text-[21px] font-semibold text-primary-foreground"
        >
          {job.title}
        </PlainText>
      </h3>
      {meta ? (
        <p className="mt-1.5 text-xs leading-[17px] text-primary-foreground/80">
          <PlainText as="span" className="text-xs text-primary-foreground/80">
            {meta}
          </PlainText>
        </p>
      ) : null}
      <p className="mt-2 text-[13px] leading-[19px] text-primary-foreground/80">
        {match.explanation ? (
          <PlainText
            as="span"
            className="line-clamp-3 text-[13px] text-primary-foreground/80"
          >
            {match.explanation}
          </PlainText>
        ) : (
          "The matching engine returned no explanation for this listing."
        )}
      </p>
      {match.role_capped ? (
        <p className="mt-2 text-[11px] text-destructive">
          The listing's role is unrelated to the candidate's target roles, so
          the overall score is capped.
        </p>
      ) : null}
      <div className="mt-4">
        <LinkButton
          to={`/app/matches/${encodeURIComponent(job.id)}`}
          variant="outline"
          className="border-[#dce1d6] bg-card text-forest hover:bg-card/90"
        >
          Explore matches →
        </LinkButton>
      </div>
    </div>
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
    <div
      aria-busy="true"
      className="rounded-[var(--radius-surface)] bg-primary p-5"
    >
      <div aria-hidden="true" className="h-6 w-28 rounded-md bg-lime-soft/40" />
      <div aria-hidden="true" className="mt-3 h-7 w-3/4 rounded bg-card/30" />
      <div aria-hidden="true" className="mt-2 h-4 w-1/2 rounded bg-card/20" />
      <div aria-hidden="true" className="mt-3 h-10 rounded bg-card/20" />
      <div aria-hidden="true" className="mt-4 h-9 w-36 rounded-lg bg-card/30" />
    </div>
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
