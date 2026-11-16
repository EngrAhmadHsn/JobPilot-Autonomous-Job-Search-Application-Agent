import { Link } from "react-router-dom"

import { PlainText } from "@/components/common/plain-text"

import { formatScore } from "@/lib/format"
import type { JobListing, JobMatchResult } from "@/lib/api/types"

/*
  The shortlist row (WS-35) — the reference's "Other Great Opportunities",
  grounded: real ranked matches and their real listings, no employer logos
  (the corpus carries text only, so the identity block is a letter
  monogram), no bookmark/save action (the backend has no shortlist
  endpoint), no salary or posted-when unless the listing carries them.

  The row is rendered only when the profile holds additional ranked
  matches; with none, the parent renders nothing at all — no placeholder
  cards.
*/

/** Small score pill for the shortlist cards — the same lime chip, compact. */
function ShortlistScore({ value }: { value: number }) {
  return (
    <span className="inline-flex items-baseline gap-1 rounded-full bg-lime px-2 py-0.5 text-xs font-semibold text-lime-foreground tabular-nums">
      {formatScore(value)}
      <span className="text-[10px] text-lime-foreground/80">match</span>
    </span>
  )
}

/** The first letter of the company name, as the identity block's mark. */
function Monogram({ company }: { company: string }) {
  const letter = company.trim().charAt(0).toUpperCase() || "?"
  return (
    <span
      aria-hidden="true"
      className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-forest-soft font-heading text-base font-semibold text-forest"
    >
      {letter}
    </span>
  )
}

export interface ShortlistEntry {
  job: JobListing
  match: JobMatchResult
}

function ShortlistCard({ job, match }: ShortlistEntry) {
  return (
    <Link
      to={`/app/matches/${encodeURIComponent(job.id)}`}
      viewTransition
      className="group flex h-full min-w-0 flex-col gap-2 rounded-xl border border-border bg-card p-4 transition-[box-shadow] duration-150 hover:shadow-[var(--shadow-lift)]"
    >
      <div className="flex items-start justify-between gap-2">
        <Monogram company={job.company} />
        <ShortlistScore value={match.overall_score} />
      </div>
      <PlainText className="font-heading text-sm leading-snug font-semibold wrap-anywhere text-foreground">
        {job.title}
      </PlainText>
      <PlainText className="text-xs wrap-anywhere text-muted-foreground">
        {job.company}
        {job.location ? ` · ${job.location}` : ""}
      </PlainText>
      <span className="mt-auto inline-flex items-center gap-1.5 pt-1 text-xs font-medium text-muted-foreground transition-colors duration-150 group-hover:text-foreground">
        View details
        <span aria-hidden="true">→</span>
      </span>
    </Link>
  )
}

/** Up to four additional real matches, at the reference's card density. */
export function Shortlist({ entries }: { entries: ShortlistEntry[] }) {
  if (entries.length === 0) return null
  return (
    <ul className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
      {entries.map((entry) => (
        <li key={entry.job.id} className="min-w-0">
          <ShortlistCard {...entry} />
        </li>
      ))}
    </ul>
  )
}
