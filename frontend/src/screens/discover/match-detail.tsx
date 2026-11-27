import { SearchXIcon } from "lucide-react"
import type { Ref } from "react"

import { PlainText } from "@/components/common/plain-text"
import { RelativeTime } from "@/components/common/relative-time"
import { OverallScore } from "@/components/common/score-grid"
import { EmptyState } from "@/components/ui/empty-state"
import { Button } from "@/components/ui/button"
import { LinkButton } from "@/components/ui/link-button"

import { MatchReasoning } from "@/screens/discover/match-reasoning"
import { PostingQuestionsPreview } from "@/screens/posting/questions-preview"

import { postingPath, preparePath } from "@/lib/api/posting-application"
import { isSafeLinkUrl } from "@/lib/safe-url"

import type { JobListing, JobMatchResult } from "@/lib/api/types"

/*
  The detail panel of the Discover split view, rebuilt to the design's
  "Desktop detail" card (WS-42, node `49:923`): the score chip, the title at
  28/600, one meta line, an uppercase freshness · source line, then the fit
  card — "Why this could be a good fit", the narrative, the matched chips,
  the evidence-gap panel, the sponsorship line, and the reasoning one
  disclosure deep. Preparation and a preview of the employer's questions
  sit above the fit card because they don't depend on a match.

  What the reference draws that this panel does **not**: employer logos (the
  corpus carries text only) and the Save/heart action (there is no save or
  shortlist endpoint — an action that only pretends would be worse than none,
  so the reference's heart is dropped). The design's second action opens the
  board's own listing; that conversion happens only through the guarded
  `isSafeLinkUrl` check, and a listing with no safe URL falls back to the
  console's complete-record route instead.

  The panel shows the stored description in full; `/app/matches/:jobId`
  still carries the complete listing record and the sponsorship guardrails.
  The split-view panel carries the one honest line (`SponsorSignal`).
*/

export function MatchDetail({
  job,
  match,
  matchReadFailed = false,
  onRetryMatch,
  titleRef,
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
  /** Focus destination when a result opens in the single-column view. */
  titleRef?: Ref<HTMLHeadingElement>
}) {
  // The design's meta line (`49:927`): company · location · employment type.
  const meta = [job.company, job.location, job.employment_type]
    .filter((part) => part && part.trim().length > 0)
    .join(" · ")
  const hasPosted = Boolean(job.posted_at)
  const hasSource = Boolean(job.source && job.source.trim().length > 0)
  const safeApplicationUrl =
    job.application_url && isSafeLinkUrl(job.application_url)
      ? job.application_url
      : null

  return (
    <div className="min-w-0 rounded-surface border border-border-surface bg-card p-4 sm:p-6">
      <div className="space-y-4">
        {/*
          The card's head (`49:924`–`49:928`): the chip, the title, the meta
          line, and the freshness · source line. The score renders only when
          a match exists — a chip showing 0 for a listing the profile never
          scored would be a fabricated number wearing a real one's clothes.
        */}
        <div className="min-w-0 space-y-2.5">
          {match ? <OverallScore value={match.overall_score} /> : null}
          <h2
            ref={titleRef}
            tabIndex={-1}
            className="leading-[34px] font-semibold tracking-tight text-balance text-forest"
          >
            <PlainText
              as="span"
              className="text-[28px] leading-[34px] wrap-anywhere"
            >
              {job.title}
            </PlainText>
          </h2>
          {meta ? (
            <PlainText className="block text-sm leading-5 wrap-anywhere text-muted-foreground">
              {meta}
            </PlainText>
          ) : null}
          {hasPosted || hasSource ? (
            <p className="text-[11px] leading-4 tracking-wide text-muted-foreground uppercase">
              {hasPosted ? (
                <>
                  Posted <RelativeTime value={job.posted_at as string} />
                </>
              ) : null}
              {hasPosted && hasSource ? " · " : null}
              {hasSource ? (
                <PlainText as="span" className="text-[11px]">
                  {job.source}
                </PlainText>
              ) : null}
            </p>
          ) : null}
        </div>

        <div className="flex flex-wrap items-center gap-3">
          <LinkButton to={preparePath(job.id)}>Prepare application</LinkButton>
          <LinkButton
            variant="outline"
            to={`/app/tailor/${encodeURIComponent(job.id)}`}
          >
            Tailor for this role →
          </LinkButton>
          {safeApplicationUrl ? (
            <a
              href={safeApplicationUrl}
              target="_blank"
              rel="noreferrer noopener"
              className="inline-flex h-9 items-center rounded-lg border border-border-surface bg-card px-3.5 text-[13px] leading-[19px] font-semibold text-forest transition-colors outline-none hover:bg-accent focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
            >
              Open original listing ↗
            </a>
          ) : (
            <LinkButton variant="outline" to={postingPath(job.id)}>
              Open the full listing
            </LinkButton>
          )}
        </div>
        <PostingQuestionsPreview jobId={job.id} heading="h3" />

        <div aria-hidden="true" className="h-px bg-border-surface" />

        {match ? (
          <div className="space-y-4">
            <h3 className="text-[19px] leading-[28px] font-semibold text-forest">
              Why this could be a good fit
            </h3>
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
              history did not answer. Trying again is safe and reads nothing
              new.
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

        <div className="space-y-2 border-t border-border-surface pt-5">
          <h3 className="type-section">Job description</h3>
          {job.description?.trim() ? (
            <PlainText className="max-w-[72ch] wrap-anywhere sm:text-base">
              {job.description}
            </PlainText>
          ) : (
            <p className="text-sm text-muted-foreground">
              The listing has no description.
            </p>
          )}
        </div>
      </div>
    </div>
  )
}
