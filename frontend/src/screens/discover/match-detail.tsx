import {
  ArrowLeftIcon,
  BanknoteIcon,
  Building2Icon,
  ClockIcon,
  DatabaseIcon,
  LaptopIcon,
  MapPinIcon,
  SearchXIcon,
} from "lucide-react"
import type { LucideIcon } from "lucide-react"
import type { ReactNode } from "react"

import { PlainText } from "@/components/common/plain-text"
import { RelativeTime } from "@/components/common/relative-time"
import { OverallScore } from "@/components/common/score-grid"
import { EmptyState } from "@/components/ui/empty-state"
import { Button } from "@/components/ui/button"
import { LinkButton } from "@/components/ui/link-button"

import { MatchReasoning } from "@/screens/discover/match-reasoning"

import type { JobListing, JobMatchResult } from "@/lib/api/types"

/*
  The detail panel of the Discover split view (WS-36) — the reference's
  right-hand column, grounded.

  What the reference draws that this panel does **not**: employer logos (the
  corpus carries text only, so the identity block is a letter monogram), the
  "96%" score arc (the real component-weighted score renders as the lime chip
  the console already uses), and the Save/heart action (there is no save or
  shortlist endpoint — an action that only pretends would be worse than none,
  so the reference's heart is dropped). "Company Fit" and any other
  component the engine does not produce cannot appear: the breakdown is the
  shared `ScoreGrid`, whose unknown states render as unknown.

  The panel is the summary; the route `/app/matches/:jobId` is the complete
  record. The description excerpt clamps here and the action below hands off
  to the full listing rather than duplicating every field in a second noisy
  layout.

  The monogram and the compact evidence pattern mirror `screens/overview/`
  (WS-35) byte-for-byte; promoting them to shared primitives is the lead's
  Wave-4 work.
*/

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

function MetaItem({
  icon: Icon,
  children,
}: {
  icon: LucideIcon
  children: ReactNode
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
        className="text-xs wrap-anywhere text-muted-foreground"
      >
        {children}
      </PlainText>
    </span>
  )
}

export function MatchDetail({
  job,
  match,
  matchReadFailed = false,
  onRetryMatch,
  onBack,
}: {
  job: JobListing
  /** The match for the current profile, or null when none exists yet. */
  match: JobMatchResult | null
  /**
   * The persisted match could not be read. This is NOT the same fact as
   * `match === null`, and the difference is the whole point of this prop:
   * a null match with a healthy read means "not scored yet", while a null
   * match here means "nobody knows" — and rendering the first as the second
   * would state an outcome that was never observed (WS-36 review fix).
   */
  matchReadFailed?: boolean
  /** Retry the failed match read; rendered only alongside a failure. */
  onRetryMatch?: () => void
  /** The way back to the list on a phone; absent on desktop-first layouts. */
  onBack?: () => void
}) {
  const salary = job.salary
    ? `${job.salary}${job.currency ? ` ${job.currency}` : ""}`
    : null
  type MetaEntry = { key: string; icon: LucideIcon; value: ReactNode }
  const metaEntries: (MetaEntry | null)[] = [
    job.location
      ? { key: "location", icon: MapPinIcon, value: job.location }
      : null,
    job.employment_type
      ? { key: "type", icon: Building2Icon, value: job.employment_type }
      : null,
    job.remote_policy
      ? { key: "remote", icon: LaptopIcon, value: job.remote_policy }
      : null,
    salary ? { key: "salary", icon: BanknoteIcon, value: salary } : null,
    job.posted_at
      ? {
          key: "posted",
          icon: ClockIcon,
          value: <RelativeTime value={job.posted_at} />,
        }
      : null,
    job.source
      ? { key: "source", icon: DatabaseIcon, value: `via ${job.source}` }
      : null,
  ]
  const meta = metaEntries.filter((entry): entry is MetaEntry => entry !== null)

  return (
    <div className="space-y-5">
      {onBack ? (
        <Button
          type="button"
          variant="ghost"
          size="sm"
          className="lg:hidden"
          onClick={onBack}
        >
          <ArrowLeftIcon aria-hidden="true" className="size-4" />
          Back to results
        </Button>
      ) : null}

      <div className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 items-center gap-3">
          <CompanyMonogram company={job.company} />
          <div className="min-w-0">
            <PlainText className="text-sm wrap-anywhere text-muted-foreground">
              {job.company}
            </PlainText>
            <h3 className="font-heading text-xl leading-snug font-semibold tracking-tight text-balance text-foreground">
              <PlainText as="span" className="text-xl wrap-anywhere">
                {job.title}
              </PlainText>
            </h3>
          </div>
        </div>
        {/* The score renders only when a match exists — a chip showing 0.0
            for a listing the profile never scored would be a fabricated
            number wearing a real one's clothes. */}
        {match ? <OverallScore value={match.overall_score} /> : null}
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

      {match ? (
        <div className="space-y-2">
          <p className="font-heading text-sm font-semibold text-foreground">
            Why this match
          </p>
          <MatchReasoning match={match} breakdown="disclosed" />
        </div>
      ) : matchReadFailed ? (
        /*
          An unknown, not a negative. The read failed, so nothing was
          observed about this profile's match — the honest rendering names
          the failure and offers the one useful action (try again).
        */
        <div
          role="status"
          className="rounded-xl border border-border bg-muted p-4"
        >
          <p className="text-sm font-medium text-foreground">
            The match for this listing could not be read.
          </p>
          <p className="mt-1 text-sm text-muted-foreground">
            This is not a score of zero and not a missing match — the stored
            history did not answer. Trying again is safe and reads nothing new.
          </p>
          {onRetryMatch ? (
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="mt-3"
              onClick={onRetryMatch}
            >
              Try reading it again
            </Button>
          ) : null}
        </div>
      ) : (
        <EmptyState
          icon={SearchXIcon}
          title="Not matched yet"
          message="The current profile has not been scored against this listing. Run a search and this panel will show the reasoning beside the list."
        />
      )}

      {job.description ? (
        <div className="space-y-1.5">
          <p className="text-xs font-medium tracking-wide text-muted-foreground uppercase">
            From the listing
          </p>
          <PlainText className="line-clamp-4 max-w-[68ch] text-muted-foreground">
            {job.description}
          </PlainText>
        </div>
      ) : (
        <p className="text-sm text-muted-foreground">
          The listing has no description.
        </p>
      )}

      <div className="flex flex-wrap items-center gap-2 border-t border-border pt-4">
        <LinkButton to={`/app/tailor/${encodeURIComponent(job.id)}`}>
          Tailor for this job
        </LinkButton>
        <LinkButton
          variant="outline"
          to={`/app/matches/${encodeURIComponent(job.id)}`}
        >
          Open the full listing
        </LinkButton>
      </div>
    </div>
  )
}
