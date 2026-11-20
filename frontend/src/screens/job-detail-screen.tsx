import { useQuery } from "@tanstack/react-query"
import { ArrowLeftIcon } from "lucide-react"
import { Link, useParams } from "react-router-dom"

import { CardSkeleton } from "@/components/common/card-skeleton"
import { FieldList, SectionTitle } from "@/components/common/field-list"
import { PlainText } from "@/components/common/plain-text"
import { RelativeTime } from "@/components/common/relative-time"
import { OverallScore } from "@/components/common/score-grid"
import { EmptyState } from "@/components/ui/empty-state"
import { ErrorState } from "@/components/ui/error-state"
import { LinkButton } from "@/components/ui/link-button"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"

import { api } from "@/lib/api/endpoints"
import { formatDateTime, formatList } from "@/lib/format"
import { useCurrentProfileId } from "@/lib/profile"
import { isSafeLinkUrl } from "@/lib/safe-url"
import { useDocumentTitle } from "@/hooks/use-document-title"

import { MatchReasoning, fitVerdict } from "@/screens/discover/match-reasoning"
import { matchFromHistoryEntry } from "@/screens/discover/match-history"

import type { JobListing, JobMatchResult } from "@/lib/api/types"

/*
  One job listing, with the match the current profile scored against it
  (WS-36 rebuild).

  This route is the **complete record** behind the Discover panel: the full
  listing text, the full match reasoning with its component breakdown in
  place, the requirements as credited evidence and as gaps, and the source
  and freshness of the data. The Discover panel is the summary that hands off
  here; this screen does not duplicate the panel's compact anatomy back.

  Every value here came from a third party (a job board) or from the
  matching engine, and every one of them is rendered as plain text. The one
  untrusted→link conversion is guarded by `isSafeLinkUrl` (below).

  The header is built here rather than through the shared `PageHeader`
  because board-supplied titles carry long unbreakable tokens, and the
  measured fix (`wrap-anywhere`, which affects min-content sizing —
  `break-words` does not stop the clipping) has to sit on the `h1` itself.
  The tab title is still set from the screen's own name (the document-title
  contract), and the shared rhythm (display heading, prose line, meta row,
  actions) is mirrored one-for-one. Promoting a `wrap-anywhere` heading
  option into `PageHeader` is a report proposal to the lead.

  Research insights (facts vs inferred) render only when a real endpoint
  carries them: insights ride on the tailoring response, and there is no
  per-job insights route, so this screen renders none rather than inferring.
*/

/**
 * The match of one job, rebuilt from the persisted match history.
 *
 * Moved to `screens/discover/match-history.ts` (WS-36) so the Discover
 * panel and this route rebuild the row identically — the function there is
 * the documented screen-local mirror; extracting one shared copy is the
 * lead's Wave-4 work.
 */

/** The listing's facts as a label/value table. */
function ListingFields({ listing }: { listing: JobListing }) {
  return (
    <FieldList
      items={[
        {
          label: "Company",
          value: (
            <PlainText className="wrap-anywhere">{listing.company}</PlainText>
          ),
        },
        {
          label: "Location",
          value: listing.location ? (
            <PlainText className="wrap-anywhere">{listing.location}</PlainText>
          ) : (
            "—"
          ),
        },
        {
          label: "Remote policy",
          value: listing.remote_policy ? (
            <PlainText className="wrap-anywhere">
              {listing.remote_policy}
            </PlainText>
          ) : (
            "—"
          ),
        },
        {
          label: "Employment type",
          value: listing.employment_type ? (
            <PlainText className="wrap-anywhere">
              {listing.employment_type}
            </PlainText>
          ) : (
            "—"
          ),
        },
        {
          label: "Salary",
          value: listing.salary ? (
            <PlainText className="wrap-anywhere tabular-nums">
              {listing.salary}
              {listing.currency ? ` ${listing.currency}` : ""}
            </PlainText>
          ) : (
            "—"
          ),
        },
        {
          label: "Seniority",
          value: listing.seniority ? (
            <PlainText className="wrap-anywhere">{listing.seniority}</PlainText>
          ) : (
            "—"
          ),
        },
        {
          label: "Required skills",
          value: (
            <PlainText className="wrap-anywhere">
              {formatList(listing.required_skills)}
            </PlainText>
          ),
        },
        {
          label: "Preferred skills",
          value: (
            <PlainText className="wrap-anywhere">
              {formatList(listing.preferred_skills)}
            </PlainText>
          ),
        },
        {
          label: "Experience",
          value: listing.experience_requirements ? (
            <PlainText className="wrap-anywhere">
              {listing.experience_requirements}
            </PlainText>
          ) : (
            "—"
          ),
        },
        {
          label: "Education",
          value: listing.education_requirements ? (
            <PlainText className="wrap-anywhere">
              {listing.education_requirements}
            </PlainText>
          ) : (
            "—"
          ),
        },
        { label: "Posted", value: formatDateTime(listing.posted_at) },
        {
          label: "Source",
          value: (
            <PlainText className="wrap-anywhere">
              {listing.source}
              {listing.source_job_id ? ` · ${listing.source_job_id}` : ""}
            </PlainText>
          ),
        },
        {
          label: "Apply at",
          // WS-15: the application URL is board-supplied, and this is
          // the one place the console turns untrusted text into
          // something the browser acts on. Only http(s) becomes a
          // link; anything else is shown as text, so a board cannot
          // publish a `javascript:` URL into the operator's console.
          value: listing.application_url ? (
            isSafeLinkUrl(listing.application_url) ? (
              <a
                href={listing.application_url}
                target="_blank"
                rel="noreferrer noopener"
                className="wrap-anywhere underline underline-offset-4"
              >
                {listing.application_url}
              </a>
            ) : (
              <PlainText className="wrap-anywhere">
                {listing.application_url}
              </PlainText>
            )
          ) : (
            "—"
          ),
        },
      ]}
    />
  )
}

/**
 * The rail's sponsorship block, from the match record and nothing else.
 *
 * WS-22's three register states each get their own honest sentence: a
 * verified employer says so with the register's finding; a checked-and-empty
 * register says a register was consulted and holds no record; and no
 * register data says exactly that. The guardrail sentence is the design's
 * own copy (node `49:1962`) and holds in every state — sponsorship never
 * boosts a score or promises eligibility.
 */
function sponsorGuardrails(match: JobMatchResult | null): {
  heading: string
  note: string | null
  body: string
} {
  const guardrail =
    "Sponsorship information never boosts a match score or promises future eligibility."
  const status = match?.sponsor_status ?? null
  const note = match?.sponsor_note ?? null
  if (status === "verified") {
    return {
      heading: "Sponsorship: verified",
      note: note ?? "Verified visa sponsor",
      body: guardrail,
    }
  }
  if (status === "not_found") {
    return {
      heading: "Sponsorship: no record found",
      note: null,
      body: `A sponsor register was checked and holds no record for this employer. ${guardrail}`,
    }
  }
  return {
    heading: "Sponsorship: unknown",
    note: null,
    body: `No register data is available. ${guardrail}`,
  }
}

export function JobDetailScreen() {
  const { jobId = "" } = useParams()
  const profileId = useCurrentProfileId()

  const job = useQuery({
    queryKey: ["job", jobId],
    queryFn: ({ signal }) => api.getJob(jobId, signal),
    enabled: Boolean(jobId),
  })

  const history = useQuery({
    queryKey: ["profile-matches", profileId],
    queryFn: ({ signal }) =>
      api.getProfileMatches(profileId as string, { signal }),
    enabled: Boolean(profileId),
  })

  const listing = job.data?.job ?? null
  // The tab title is the listing's own, and falls back while the read is on
  // the way — the contract holds even before the content lands.
  useDocumentTitle(listing?.title ?? "Job listing")

  const match = listing
    ? matchFromHistoryEntry(
        history.data?.matches.find((entry) => entry.job_id === listing.id)
      )
    : null

  if (job.isPending) {
    /*
      A read, not a run the operator started, so there is nothing to cancel and
      no elapsed time worth showing. The bones reserve the listing's shape.
    */
    return (
      <div className="space-y-6">
        <CardSkeleton rows={3} />
        <CardSkeleton rows={4} />
      </div>
    )
  }

  if (job.isError || !listing) {
    return <ErrorState error={job.error} onRetry={() => void job.refetch()} />
  }

  return (
    <div className="space-y-6">
      {/*
        The design file's screen `47:488` puts the actions in their own row
        under the heading. The back pill carries the real number of matches
        the profile holds — the count is the history's length, never a guess.
      */}
      <header className="space-y-4">
        <div className="min-w-0">
          <h1 className="type-display wrap-anywhere">{listing.title}</h1>
          <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-sm leading-snug wrap-anywhere text-muted-foreground">
            <PlainText as="span">{listing.company}</PlainText>
            {listing.location ? <span>· {listing.location}</span> : null}
            {listing.employment_type ? (
              <span>· {listing.employment_type}</span>
            ) : null}
            {/*
              The design's meta line (node `47:524`) names the source — not
              the source's internal id. The raw `source_job_id` stays in the
              listing's own field table below, where it belongs.
            */}
            {listing.source ? (
              <span>
                ·{" "}
                <PlainText as="span">{listing.source}</PlainText>
              </span>
            ) : null}
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2.5">
          <Link
            to="/app/matches"
            className="inline-flex h-[37px] items-center gap-1.5 rounded-lg border border-border-surface bg-card px-3.5 py-2 text-[13px] font-semibold leading-[19px] text-primary transition-colors outline-none hover:bg-accent focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
          >
            <ArrowLeftIcon aria-hidden="true" className="size-3.5" />
            {history.data
              ? `Back to ${history.data.matches.length} match${history.data.matches.length === 1 ? "" : "es"}`
              : "Back to Discover"}
          </Link>
          {match ? <OverallScore value={match.overall_score} /> : null}
          <LinkButton to={`/app/tailor/${encodeURIComponent(listing.id)}`}>
            Tailor for this role →
          </LinkButton>
          {/*
            The design's "Open original listing ↗" — and the one untrusted→
            link conversion on this screen, still guarded by `isSafeLinkUrl`.
          */}
          {listing.application_url && isSafeLinkUrl(listing.application_url) ? (
            <a
              href={listing.application_url}
              target="_blank"
              rel="noreferrer noopener"
              className="inline-flex h-[37px] items-center rounded-lg border border-border-surface bg-card px-3.5 py-2 text-[13px] font-semibold leading-[19px] text-primary transition-colors outline-none hover:bg-accent focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
            >
              Open original listing ↗
            </a>
          ) : null}
        </div>
      </header>

      <div className="grid gap-6 xl:grid-cols-[minmax(0,2fr)_minmax(0,1fr)] xl:items-start">
        <div className="min-w-0 space-y-6">
          {match ? (
            <Card>
              <CardHeader>
                {/*
                  The design's verdict slot (node `49:1920`): the card leads
                  with what the match means — derived from the engine's own
                  component verdicts and the recorded gaps, never invented.
                  The type is the card's 20/600/29 Geist, not the display
                  face — a verdict, not a headline.
                */}
                <CardTitle className="font-sans text-[20px] leading-[29px] font-semibold">
                  {fitVerdict(match)}
                </CardTitle>
              </CardHeader>
              <CardContent>
                <MatchReasoning match={match} breakdown="expanded" />
              </CardContent>
            </Card>
          ) : history.isError ? (
            /*
              The read failed, so nothing is known about this profile's match —
              which is NOT "no match history". Saying the latter would claim an
              outcome nobody observed (WS-36 review fix).
            */
            <Card>
              <CardHeader>
                <CardTitle>Why this job ranked</CardTitle>
              </CardHeader>
              <CardContent>
                <div role="status" className="space-y-2">
                  <p className="text-sm font-medium text-foreground">
                    The match for this listing could not be read.
                  </p>
                  <p className="text-sm text-muted-foreground">
                    This is not a score of zero and not a missing match — the
                    stored history did not answer. Trying again is safe.
                  </p>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={() => void history.refetch()}
                  >
                    Try reading it again
                  </Button>
                </div>
              </CardContent>
            </Card>
          ) : (
            <EmptyState
              title="No match history for this job"
              message="The current profile has not been matched against this listing yet. Run a search on Discover — the ranking is built from what the corpus holds."
              action={
                <LinkButton to="/app/matches" variant="outline" size="sm">
                  Open Discover
                </LinkButton>
              }
            />
          )}

          <Card>
            <CardHeader>
              <CardTitle>The listing</CardTitle>
            </CardHeader>
            <CardContent>
              <ListingFields listing={listing} />

              <div className="mt-4 space-y-2">
                <SectionTitle>Description</SectionTitle>
                {listing.description ? (
                  <PlainText className="max-w-[72ch] wrap-anywhere">
                    {listing.description}
                  </PlainText>
                ) : (
                  <p className="text-sm text-muted-foreground">
                    The listing has no description.
                  </p>
                )}
              </div>
            </CardContent>
          </Card>
        </div>

        {/*
          The rail, rebuilt to the design's "Match guardrails" card
          (node `49:1958`): the POSTED chip, the sponsorship guardrails
          (heading, note, and the guardrail sentence), then — after the
          divider — the one step the route hands off to. Sponsorship moved
          here from the reasoning body because a guardrail is what it is:
          a constraint that holds no matter what the match says.
        */}
        <aside className="min-w-0 space-y-3 xl:sticky xl:top-[calc(var(--header-height,7rem)+1rem)]">
          <section className="flex min-w-0 flex-col gap-3.5 rounded-surface bg-forest-soft p-5">
            {listing.posted_at ? (
              <p className="self-start rounded-[6px] px-[9px] py-1 text-[11px] font-semibold uppercase leading-4 tracking-wide text-forest">
                Posted <RelativeTime value={listing.posted_at} />
              </p>
            ) : null}
            {(() => {
              const guardrails = sponsorGuardrails(match)
              return (
                <>
                  <h2 className="text-[19px] font-semibold leading-[28px] text-forest">
                    {guardrails.heading}
                  </h2>
                  {guardrails.note ? (
                    /*
                      The outer box is a div on purpose: PlainText renders a
                      `<p>` by default, and a paragraph inside a paragraph is
                      invalid HTML the browser (and React) will flag.
                    */
                    <div className="text-sm leading-5 text-muted-foreground">
                      <PlainText className="text-sm leading-5">
                        {guardrails.note}
                      </PlainText>
                    </div>
                  ) : null}
                  <div className="text-sm leading-5 text-muted-foreground">
                    <PlainText className="text-sm leading-5">
                      {guardrails.body}
                    </PlainText>
                  </div>
                </>
              )
            })()}
            <div aria-hidden="true" className="h-px bg-border-surface" />
            <h2 className="text-base font-semibold leading-[23px] text-forest">
              Your next step
            </h2>
            <p className="text-sm leading-5 text-muted-foreground">
              Tailor a draft, review the changes, then confirm every required
              employer answer.
            </p>
            <div className="mt-1">
              <LinkButton to={`/app/tailor/${encodeURIComponent(listing.id)}`}>
                Open résumé studio →
              </LinkButton>
            </div>
          </section>
        </aside>
      </div>
    </div>
  )
}
