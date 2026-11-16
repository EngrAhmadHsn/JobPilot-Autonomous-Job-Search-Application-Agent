import { useQueries, useQuery } from "@tanstack/react-query"
import { useMemo } from "react"

import { ErrorNotice } from "@/components/common/error-notice"
import { PageHeader, Section } from "@/components/ui/page-header"
import { RelativeTime } from "@/components/common/relative-time"
import { EmptyState } from "@/components/ui/empty-state"
import { ErrorState } from "@/components/ui/error-state"
import { LinkButton } from "@/components/ui/link-button"

import { useProfileWithFallback } from "@/hooks/use-profile-fallback"
import { api } from "@/lib/api/endpoints"
import { summarizeEvents } from "@/lib/observability"
import { OVERVIEW_POLL_MS } from "@/lib/polling"

import { ActivityFeed } from "@/screens/overview/activity-feed"
import {
  AttentionSection,
  type AttentionApplication,
  type AttentionFailure,
  type AttentionItem,
} from "@/screens/overview/attention-section"
import {
  FeaturedMatch,
  FeaturedMatchMissing,
  FeaturedMatchSkeleton,
} from "@/screens/overview/featured-match"
import { matchFromHistoryEntry } from "@/screens/overview/match-history"
import { Shortlist, type ShortlistEntry } from "@/screens/overview/shortlist"
import { StatCard } from "@/screens/overview/stat-card"
import type { JobListing } from "@/lib/api/types"

/*
  The Home dashboard (WS-35) — the console's answer to "what is my next
  useful action".

  The composition is the reference panel's: a greeting, a strip of four
  compact stat cards, the featured opportunity, the agent-activity column,
  and a shortlist row. Every number is a real value the API returned, with
  its true denominator:

  - the application counts are the **server's totals** (the list response's
    `total` field), not the length of a loaded page — the previous screen
    counted a `limit: 200` page and silently undercounted past it;
  - "need your attention" is applications awaiting a decision — the
    `awaiting_approval` **and** the resting `prepared` statuses, each a
    server total — plus the trail entries that need a human eye; the trail
    part is the **newest 100 events**, because that is the page the audit
    endpoint returns, and the tile and the feed both say so instead of
    implying a whole history;
  - the featured job and the shortlist are the profile's **ranked match
    history** and the listings behind it, or they are not rendered;
  - there is no "Live" badge, no trend deltas, no progress chart, no plan
    name, no logos — nothing the API cannot prove (see the WS-33 audit §7,
    whose grounded-vs-illustrative list this screen follows).

  Polling stays on the shared overview budget: the five application/audit
  reads refetch every `OVERVIEW_POLL_MS` (5 per cycle = 10 requests/minute,
  exactly the console's documented cap for one polled resource), pause while
  the tab is hidden (TanStack's default), and everything else (matches,
  listings, question gaps, the profile) is a per-mount read cached under the
  keys the other screens use.
*/

/**
 * How many ranked matches to ask for.
 *
 * The ranked endpoint deduplicates to the most recent match per job and
 * orders by score, limited after deduplication (max 200). One read serves
 * the strip's count, the featured card and the shortlist, so they can never
 * disagree about "the best match".
 */
const RANKED_SLICE_LIMIT = 200

/**
 * The audit feed's window.
 *
 * `GET /api/audit` returns its newest rows as one page of at most 100 by
 * default (`src/api/routes/audit.py`) — there is no server-side total, so
 * anything the trail feeds count is counted **within this page** and the
 * copy says so.
 */
const AUDIT_PAGE_SIZE = 100

/** How many trail rows the Home feed shows (the full trail is one click away). */
const FEED_ROWS = 6

/** How many awaiting-approval applications render as their own rows. */
const ATTENTION_ROWS = 3

/** The time-of-day greeting, derived locally — no server claim involved. */
export function greetingFor(now: Date): string {
  const hour = now.getHours()
  if (hour < 12) return "Good morning"
  if (hour < 18) return "Good afternoon"
  return "Good evening"
}

/** A poll interval, in the unit a human reads — seconds when whole. */
export function intervalLabel(ms: number): string {
  const seconds = ms / 1000
  return Number.isInteger(seconds) && seconds > 0 ? `${seconds} s` : `${ms} ms`
}

/** The name a greeting may use — the first word of the profile's name. */
function firstName(fullName: string | null | undefined): string | null {
  const first = fullName?.trim().split(/\s+/)[0]
  return first ? first : null
}

/**
 * One ranked match, rebuilt from the persisted row.
 *
 * The history carries `job_id` and a free-form `scores` dictionary; rows
 * that cannot be read safely are skipped rather than rendered with guessed
 * values.
 */
interface RankedEntry {
  jobId: string
  match: NonNullable<ReturnType<typeof matchFromHistoryEntry>>
}

function toRankedEntry(entry: Record<string, unknown>): RankedEntry | null {
  const jobId = typeof entry.job_id === "string" ? entry.job_id : null
  if (!jobId) return null
  const match = matchFromHistoryEntry(entry)
  return match ? { jobId, match } : null
}

export function OverviewScreen() {
  const { profileId, profile, documents } = useProfileWithFallback()

  // -- The polled reads (the shared overview budget; hidden tabs pause). ----
  const tracked = useQuery({
    queryKey: ["applications", "overview", "all"],
    queryFn: ({ signal }) => api.listApplications({ limit: 1 }, signal),
    refetchInterval: OVERVIEW_POLL_MS,
  })
  const awaiting = useQuery({
    queryKey: ["applications", "overview", "awaiting-approval"],
    queryFn: ({ signal }) =>
      api.listApplications(
        { status: ["awaiting_approval"], limit: 10 },
        signal
      ),
    refetchInterval: OVERVIEW_POLL_MS,
  })
  // A `prepared` application rests in that state whenever the transition to
  // `awaiting_approval` did not land (the tracked row is created PREPARED
  // and only then moved, in a separate write that can fail and roll back),
  // and the status vocabulary itself says `prepared` is "waiting for an
  // approval decision" — so it counts toward "need your attention" and
  // renders exactly like the awaiting ones. (A multi-status call cannot
  // merge these: the backend silently ignores a filter with more than one
  // status, so each status is its own single-status read.)
  const prepared = useQuery({
    queryKey: ["applications", "overview", "prepared"],
    queryFn: ({ signal }) =>
      api.listApplications({ status: ["prepared"], limit: 10 }, signal),
    refetchInterval: OVERVIEW_POLL_MS,
  })
  const submitted = useQuery({
    queryKey: ["applications", "overview", "submitted"],
    queryFn: ({ signal }) =>
      api.listApplications({ status: ["submitted"], limit: 1 }, signal),
    refetchInterval: OVERVIEW_POLL_MS,
  })
  const audit = useQuery({
    queryKey: ["audit", "overview"],
    queryFn: ({ signal }) => api.audit(signal),
    refetchInterval: OVERVIEW_POLL_MS,
  })

  // -- Per-mount reads, cached under the keys the other screens use. --------
  const ranked = useQuery({
    queryKey: ["profile-matches-ranked", profileId],
    queryFn: ({ signal }) =>
      api.getProfileMatches(profileId as string, {
        ranked: true,
        limit: RANKED_SLICE_LIMIT,
        signal,
      }),
    enabled: Boolean(profileId),
    retry: false,
  })
  const gaps = useQuery({
    queryKey: ["question-gaps", profileId],
    queryFn: ({ signal }) => api.getQuestionGaps(profileId as string, signal),
    enabled: Boolean(profileId),
    retry: false,
  })

  const rankedEntries = useMemo(() => {
    const matches = ranked.data?.matches ?? []
    return matches
      .map(toRankedEntry)
      .filter((entry): entry is RankedEntry => entry !== null)
  }, [ranked.data])

  // The listings behind the featured card and the shortlist. Each one is a
  // shared `["job", id]` read — the same cache key the job screen uses — so
  // navigating through costs no second request.
  const jobQueries = useQueries({
    queries: rankedEntries.slice(0, 5).map((entry) => ({
      queryKey: ["job", entry.jobId],
      queryFn: ({ signal }) => api.getJob(entry.jobId, signal),
      enabled: Boolean(profileId),
      retry: false,
    })),
  })

  const jobsById = new Map<string, JobListing>()
  rankedEntries.slice(0, 5).forEach((entry, index) => {
    const job = jobQueries[index]?.data?.job
    if (job) jobsById.set(entry.jobId, job)
  })

  // -- Derived, honest numbers. --------------------------------------------
  const events = audit.data?.events ?? []
  const trail = summarizeEvents(events)

  const trackedTotal = tracked.data?.total
  const awaitingTotal = awaiting.data?.total
  const preparedTotal = prepared.data?.total
  const submittedTotal = submitted.data?.total
  const rankedCount = ranked.data?.matches.length
  // The attention count aggregates three real sources. It renders only when
  // **all** have answered — a number built from half its sources would be a
  // made-up number wearing a real one's clothes.
  const attentionReady =
    awaiting.isSuccess && prepared.isSuccess && audit.isSuccess
  const awaitingDecisionTotal = (awaitingTotal ?? 0) + (preparedTotal ?? 0)
  const attentionValue = attentionReady
    ? awaitingDecisionTotal + trail.attention
    : undefined

  const lastRead = Math.max(
    tracked.dataUpdatedAt,
    awaiting.dataUpdatedAt,
    prepared.dataUpdatedAt,
    submitted.dataUpdatedAt,
    audit.dataUpdatedAt,
    0
  )

  // -- "Your attention": every row is real and resolvable. ------------------
  const attentionItems: AttentionItem[] = []
  const hasDocuments = (documents.data?.count ?? 0) > 0
  if (!profileId) {
    attentionItems.push({
      key: "profile",
      title: hasDocuments ? "Choose a résumé to work from" : "Upload a résumé",
      body: hasDocuments
        ? "This account already has documents. Pick the one the agent should work from, so matches and tailoring have a profile."
        : "There is no candidate profile yet, so the agent has nothing to match against.",
      to: "/app/resume",
      label: hasDocuments ? "Choose a document" : "Go to Resume",
    })
  }
  if (awaitingDecisionTotal > 0) {
    attentionItems.push({
      key: "approvals",
      title: `${awaitingDecisionTotal} application${awaitingDecisionTotal === 1 ? "" : "s"} awaiting your approval`,
      body: "Prepared applications are held until a person approves or rejects them. Nothing is submitted without that decision.",
      to: "/app/approvals",
      label: "Review approvals",
    })
  }
  if (trail.attention > 0) {
    attentionItems.push({
      key: "trail",
      title: `${trail.attention} trail event${trail.attention === 1 ? "" : "s"} need${trail.attention === 1 ? "s" : ""} attention`,
      body: `The newest ${AUDIT_PAGE_SIZE} audit rows hold a refusal, a block or a failure a human should read.`,
      to: "/app/activity",
      label: "Open activity",
    })
  }
  const gapCount = gaps.data?.questions.length ?? 0
  if (gapCount > 0) {
    attentionItems.push({
      key: "questions",
      title: `${gapCount} employer question${gapCount === 1 ? "" : "s"} the profile does not answer`,
      body: "The boards ask these most often, and the profile has no answer yet — answering them by hand is the one part the agent will not improvise.",
      to: "/app/profile",
      label: "Open Profile",
    })
  }

  // A source that could not be read is not a clean bill of health: it gets
  // its own failure row (with the way back), and the section's all-clear is
  // withheld until every source has actually answered.
  const attentionFailures: AttentionFailure[] = []
  if (gaps.isError) {
    attentionFailures.push({
      key: "gaps",
      title: "Employer questions couldn't be read",
      body: "The measured question gaps did not answer, so what the boards ask and the profile covers is unknown right now.",
      onRetry: () => void gaps.refetch(),
    })
  }
  // Every attention source answered successfully (a source the account
  // cannot have — the question gaps need a profile — counts as answered).
  const attentionSourcesReady =
    awaiting.isSuccess &&
    prepared.isSuccess &&
    audit.isSuccess &&
    (Boolean(profileId) ? gaps.isSuccess : true)

  const attentionApplications: AttentionApplication[] = [
    ...(awaiting.data?.items ?? []),
    ...(prepared.data?.items ?? []),
  ]
    .slice(0, ATTENTION_ROWS)
    .filter((item) => typeof item.id === "string")
    .map((item) => ({
      id: item.id,
      jobTitle: item.job_title,
      company: item.company_name,
      status: item.status,
    }))

  // -- Featured opportunity and shortlist. ----------------------------------
  const featured = rankedEntries[0] ?? null
  const featuredJobQuery = jobQueries[0]
  const shortlistEntries: ShortlistEntry[] = rankedEntries
    .slice(1, 5)
    .flatMap((entry) => {
      const job = jobsById.get(entry.jobId)
      return job ? [{ job, match: entry.match }] : []
    })

  const applicationsError =
    tracked.error ?? awaiting.error ?? prepared.error ?? submitted.error ?? null

  // The greeting is derived locally (the clock and the profile's name); it
  // is a hello, not a metric, so no server claim rides on it. It leads the
  // header's prose while the `h1` itself stays the screen's name — the
  // document-title contract every console screen shares (`PageHeader` names
  // the tab from the `h1`, and the document-accessibility test pins
  // "Overview · JobPilot" for this route).
  const name = firstName(profile.data?.profile.personal_information.name)
  const greeting = `${greetingFor(new Date())}${name ? `, ${name}` : ""}`

  return (
    <div className="space-y-10">
      <PageHeader
        title="Overview"
        description={
          <span className="block">
            <span className="font-heading text-lg font-semibold text-foreground">
              {greeting}.
            </span>{" "}
            What the agent has done, what is waiting on you, and the next useful
            action.
          </span>
        }
        meta={
          <span>
            Reads every {intervalLabel(OVERVIEW_POLL_MS)} · last read{" "}
            <RelativeTime
              value={lastRead ? new Date(lastRead).toISOString() : null}
            />
          </span>
        }
      />

      {applicationsError ? (
        <ErrorNotice
          error={applicationsError}
          onRetry={() => {
            void tracked.refetch()
            void awaiting.refetch()
            void prepared.refetch()
            void submitted.refetch()
          }}
        />
      ) : null}

      {/* -- The stat strip. Attention first, everywhere: it is the one
             metric a person must resolve, and on mobile it is the first
             tile the reading order meets. */}
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard
          label="Need your attention"
          variant="attention"
          value={attentionValue ?? "—"}
          loading={awaiting.isPending || prepared.isPending || audit.isPending}
          hint={
            attentionReady
              ? `${awaitingDecisionTotal} awaiting a decision · ${trail.attention} in the trail's newest ${AUDIT_PAGE_SIZE}`
              : "Applications awaiting a decision plus trail events that need a human"
          }
          to="/app/approvals"
        />
        <StatCard
          label="Top matches"
          value={ranked.isSuccess ? (rankedCount ?? 0) : "—"}
          loading={Boolean(profileId) && ranked.isPending}
          hint={
            ranked.isError
              ? "The match history could not be read"
              : profileId
                ? rankedCount === RANKED_SLICE_LIMIT
                  ? `Ranked best matches — the first ${RANKED_SLICE_LIMIT} shown`
                  : "Ranked best matches from your searches"
                : "Matches appear once a résumé is added"
          }
          to="/app/matches"
        />
        <StatCard
          label="Submitted, unverified"
          value={submitted.isSuccess ? (submittedTotal ?? 0) : "—"}
          loading={submitted.isPending}
          hint="Sent to a board; the confirmation is still pending (server total)"
          to="/app/tracker"
        />
        <StatCard
          label="Tracked applications"
          value={tracked.isSuccess ? (trackedTotal ?? 0) : "—"}
          loading={tracked.isPending}
          hint="Every application this account tracks (the server's total)"
          to="/app/tracker"
        />
      </div>

      <div className="grid gap-8 lg:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)]">
        {/* -- The opportunity column: featured first, shortlist under it.
               Job/application content leads the page. */}
        <div className="min-w-0 space-y-8">
          <Section
            title="Top match"
            description="The best-ranked opportunity in this profile's match history."
            action={
              (rankedCount ?? 0) > 1 ? (
                <LinkButton to="/app/matches" variant="ghost" size="sm">
                  All matches
                </LinkButton>
              ) : undefined
            }
          >
            {ranked.isPending && profileId ? (
              <FeaturedMatchSkeleton />
            ) : ranked.isError ? (
              <ErrorNotice
                error={ranked.error}
                onRetry={() => void ranked.refetch()}
              />
            ) : !featured ? (
              <EmptyState
                title="No matches yet"
                message="The profile has not been matched against the stored corpus. Run a search on Matches — the ranking is built from what the corpus holds."
                action={
                  <LinkButton to="/app/matches" variant="outline" size="sm">
                    Open Matches
                  </LinkButton>
                }
              />
            ) : featuredJobQuery?.isPending ? (
              <FeaturedMatchSkeleton />
            ) : featuredJobQuery?.isError || !jobsById.has(featured.jobId) ? (
              <FeaturedMatchMissing />
            ) : (
              <FeaturedMatch
                job={jobsById.get(featured.jobId) as JobListing}
                match={featured.match}
              />
            )}
          </Section>

          {shortlistEntries.length > 0 ? (
            <Section
              title="Also strong"
              description="The next best-ranked matches from the same history."
            >
              <Shortlist entries={shortlistEntries} />
            </Section>
          ) : null}
        </div>

        {/* -- The operator's column: what waits on a human, then the trail. */}
        <div className="min-w-0 space-y-8">
          <Section
            title="Your attention"
            description="What is waiting on you, before anything else."
          >
            <AttentionSection
              items={attentionItems}
              applications={attentionApplications}
              failures={attentionFailures}
              sourcesReady={attentionSourcesReady}
            />
          </Section>

          <Section
            title="Recent agent activity"
            description={`The newest ${AUDIT_PAGE_SIZE} events in this account's audit trail — the first page, not the whole history · updated every ${intervalLabel(OVERVIEW_POLL_MS)}.`}
            action={
              <LinkButton to="/app/activity" variant="ghost" size="sm">
                See the full trail
              </LinkButton>
            }
          >
            {audit.isPending ? (
              <p className="text-sm text-muted-foreground" role="status">
                Reading the trail…
              </p>
            ) : audit.isError ? (
              <ErrorState
                error={audit.error}
                onRetry={() => void audit.refetch()}
              />
            ) : events.length === 0 ? (
              <EmptyState
                title="No recorded activity yet"
                message="Upload a résumé or run a search, and the agent's steps will appear here."
              />
            ) : (
              <div className="rounded-xl border border-border bg-card px-4 py-2">
                <ActivityFeed events={events.slice(0, FEED_ROWS)} />
              </div>
            )}
          </Section>
        </div>
      </div>
    </div>
  )
}
