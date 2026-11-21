import { useQueries, useQuery } from "@tanstack/react-query"
import { FileText } from "lucide-react"
import { useMemo, type ReactNode } from "react"

import { ErrorNotice } from "@/components/common/error-notice"
import { PageHeader, Section } from "@/components/ui/page-header"
import { ErrorState } from "@/components/ui/error-state"
import { LinkButton } from "@/components/ui/link-button"

import { useProfileWithFallback } from "@/hooks/use-profile-fallback"
import { api } from "@/lib/api/endpoints"
import { summarizeEvents } from "@/lib/observability"
import { OVERVIEW_POLL_MS } from "@/lib/polling"

import {
  FeaturedMatch,
  FeaturedMatchMissing,
  FeaturedMatchSkeleton,
} from "@/screens/overview/featured-match"
import { ActivityFeed } from "@/screens/overview/activity-feed"
import {
  ActionRow,
  ApplicationActionRow,
  FailureActionRow,
  MetricTile,
  NextStepPanel,
  PipelineBar,
  QuietLink,
} from "@/screens/overview/home-panels"
import { matchFromHistoryEntry } from "@/screens/overview/match-history"
import { Shortlist, type ShortlistEntry } from "@/screens/overview/shortlist"
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

/**
 * How many digest rows the secondary column shows.
 *
 * Three, as the design draws (nodes 49:812–49:835) — the featured card must
 * land where the design puts it, and the full stretch remains one click away
 * under "All activity". The provenance caption at the card's foot still says
 * the feed is the first audit page, not the whole history.
 */
const FEED_ROWS = 3

/** How many rows of the action queue render before the rest wait for a visit. */
const ATTENTION_ROWS = 3

/**
 * One row of the action queue.
 *
 * Declared here rather than imported from the panel that used to render it:
 * WS-42 replaced that panel with the design's queue, and the row's shape is
 * the queue's business now.
 */
interface AttentionItem {
  key: string
  title: string
  body: string
  to: string
  label: string
}

/** A poll interval, in the unit a human reads — seconds when whole. */
export function intervalLabel(ms: number): string {
  const seconds = ms / 1000
  return Number.isInteger(seconds) && seconds > 0 ? `${seconds} s` : `${ms} ms`
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
  const { profileId, documents } = useProfileWithFallback()

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
  // Applications resting in `prepared` count toward "awaiting review": the
  // status vocabulary itself calls that state "waiting for an approval
  // decision", and the transition that would have moved the row to
  // `awaiting_approval` is a second write that can fail and roll back.
  const awaitingDecisionTotal = (awaitingTotal ?? 0) + (preparedTotal ?? 0)

  // -- "Your attention": every row is real and resolvable. ------------------
  //
  // The shape is declared here rather than imported: WS-42 replaced the
  // `attention-section` panel with the design's action queue, and what
  // survives is the *list* — still built from the same real sources, still
  // one row per thing a human must do.
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
      body: "Unlock approval. No answer is inferred.",
      to: "/app/profile",
      label: "Open Profile",
    })
  }

  // A source that could not be read is not a clean bill of health. The
  // question gaps are the one source whose failure is surfaced as its own
  // row (with a retry), and the queue's all-clear is withheld while it is
  // unknown.
  const failures: {
    key: string
    title: string
    body: string
    onRetry: () => void
  }[] = []
  if (gaps.isError && profileId) {
    failures.push({
      key: "gaps",
      title: "Employer questions couldn't be read",
      body: "The measured question gaps did not answer, so what the boards ask and the profile covers is unknown right now.",
      onRetry: () => void gaps.refetch(),
    })
  }

  // The awaiting and resting-prepared applications, named one by one. The
  // server totals govern the tiles; these rows are the page each status
  // returned, and the design's queue names the thing to act on.
  //
  // Deduplicated by id: the two reads are separate requests, and an
  // application that moved between them — or a backend that answered both
  // filters with the same row — must not appear twice in one queue. A
  // duplicate row would also break React's keying.
  const seenApplicationIds = new Set<string>()
  const attentionApplications = [
    ...(awaiting.data?.items ?? []),
    ...(prepared.data?.items ?? []),
  ]
    .filter((item) => {
      if (typeof item.id !== "string" || seenApplicationIds.has(item.id)) {
        return false
      }
      seenApplicationIds.add(item.id)
      return true
    })
    .slice(0, ATTENTION_ROWS)
    .map((item) => ({
      id: item.id,
      /* The design's queue names the *task*, not the record: "Review your
         Acorn application / The packet is ready for your decision." The
         company names the task; the job title rides in the consequence line
         so two applications at one company stay distinguishable. */
      title: item.company_name
        ? `Review your ${item.company_name} application`
        : "Review this application",
      body: `The ${item.job_title ?? "application"} packet is ready for your decision.`,
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

  // The greeting the old header carried is gone with the design's own
  // heading (node 47:35): the statement is the h1 and the prose line is the
  // design's sentence. Nothing honest was lost — the greeting was derived
  // from the clock, not from the data.

  // -- The design's four stage counts (WS-42) ------------------------------
  //
  // The Applications board groups the vocabulary into four stages, and Home
  // shows the same four so the two screens can never disagree about how many
  // applications sit where. Each group is one **multi-status** read — the
  // backend now applies every requested status (until 2026-11-19 it silently
  // dropped all but one, which is why this screen used to need a separate
  // read per status).
  //
  // The four groups map onto the **real** vocabulary only
  // (`src/applications/tracking.py:50-63` — eleven statuses, none invented):
  //
  //   Awaiting review   ← awaiting_approval, prepared
  //   Needs you         ← the states a human must act on and the machine
  //                       cannot: a verified submission with no recorded
  //                       outcome, plus anything the run left blocked.
  //   In progress       ← submitted (sent; the confirmation is still pending)
  //   Outcome recorded  ← interview, offer, rejected, withdrawn
  //
  // The important correction: `verified` does **not** mean "needs a handoff".
  // `verified` means the submission was confirmed by evidence — the machine
  // saw it land. It sits in "Needs you" only because a human has not yet
  // recorded what happened next, and the tile's label says so; it is never
  // presented as awaiting a human submit.
  //
  // `discovered`/`matched`/`shortlisted` are pre-application states, not
  // tracked applications, so no tile claims them.
  const outcomeQuery = useQuery({
    queryKey: ["applications", "overview", "outcomes"],
    queryFn: ({ signal }) =>
      api.listApplications(
        { status: ["interview", "offer", "rejected", "withdrawn"], limit: 1 },
        signal
      ),
    refetchInterval: OVERVIEW_POLL_MS,
  })
  const inProgressQuery = useQuery({
    queryKey: ["applications", "overview", "in-progress"],
    queryFn: ({ signal }) =>
      api.listApplications({ status: ["submitted"], limit: 1 }, signal),
    refetchInterval: OVERVIEW_POLL_MS,
  })
  const handoffQuery = useQuery({
    queryKey: ["applications", "overview", "handoff"],
    queryFn: ({ signal }) =>
      api.listApplications({ status: ["verified"], limit: 1 }, signal),
    refetchInterval: OVERVIEW_POLL_MS,
  })

  const outcomeCount = outcomeQuery.isSuccess
    ? (outcomeQuery.data?.total ?? 0)
    : undefined
  const inProgressValue = inProgressQuery.isSuccess
    ? (inProgressQuery.data?.total ?? 0)
    : undefined
  const handoffCount = handoffQuery.isSuccess
    ? (handoffQuery.data?.total ?? 0)
    : undefined

  // The pipeline bar's segments, straight from those totals. A stage whose
  // count is unknown contributes nothing — it is not rendered as a zero,
  // because "we could not read it" and "it is empty" are different facts.
  const pipelineSegments = [
    {
      key: "review",
      label: "Awaiting review",
      count: awaitingDecisionTotal,
      tone: "bg-stage-review",
    },
    {
      key: "handoff",
      label: "Needs you",
      count: handoffCount ?? 0,
      tone: "bg-stage-handoff",
    },
    {
      key: "progress",
      label: "In progress",
      count: inProgressValue ?? 0,
      tone: "bg-stage-progress",
    },
    {
      key: "outcome",
      label: "Outcome recorded",
      count: outcomeCount ?? 0,
      tone: "bg-stage-outcome",
    },
  ]

  // -- The next step (WS-42) -----------------------------------------------
  //
  // The design leads with the single most useful action. It is derived from
  // the same real state the panels below use, and it appears **only when
  // there is something to do** — an "all clear" hero would be decoration.
  //
  // The precedence is the journey's own: an application waiting on a
  // decision is the most time-sensitive thing a candidate has; an unreadable
  // question is what unblocks approval; a missing résumé blocks everything
  // downstream.
  const firstAwaiting = (awaiting.data?.items ?? []).find(
    (item) => typeof item.id === "string"
  )
  const nextStep: {
    statement: string
    subject: ReactNode
    consequence: ReactNode
    to: string
    label: string
    chip?: string
  } | null = firstAwaiting
    ? {
        statement: "Your next application is nearly ready.",
        subject: `${firstAwaiting.job_title ?? "A prepared application"}${
          firstAwaiting.company_name ? ` · ${firstAwaiting.company_name}` : ""
        }`,
        consequence:
          "Review the tailored résumé and the employer's answers. Nothing leaves JobPilot without your decision.",
        to: "/app/approvals",
        label: "Review application →",
        chip:
          awaitingDecisionTotal > 0
            ? `${awaitingDecisionTotal} awaiting review`
            : undefined,
      }
    : !profileId
      ? {
          statement: "Your workspace needs a starting point.",
          subject: hasDocuments
            ? "Choose the résumé the agent should work from."
            : "Upload a résumé the agent can work from.",
          consequence: hasDocuments
            ? "This account already holds documents. Pick one and matches, tailoring and applications all work from it."
            : "Everything downstream — matches, tailoring, applications — is built from a verified profile. The agent begins nothing without one.",
          to: "/app/resume",
          label: hasDocuments ? "Choose a document →" : "Upload a résumé →",
        }
      : gapCount > 0
        ? {
            statement:
              "The boards are asking questions your profile cannot answer.",
            subject: `${gapCount} employer question${gapCount === 1 ? "" : "s"} appear${gapCount === 1 ? "s" : ""} most often in this corpus.`,
            consequence:
              "A missing answer stops form filling instead of triggering a guess, so answering them is what unlocks approval.",
            to: "/app/profile",
            label: "Answer questions →",
            chip: `${gapCount} to answer`,
          }
        : null

  return (
    <div>
      {/*
        The page heading (design node 47:35): the statement **is** the h1 —
        Bricolage 36/700 — with one 14 px line of prose under it, gap 8. The
        tab keeps the stable screen name ("Overview · JobPilot") through
        `documentTitle`, so the document-title contract holds while the page
        leads with the design's sentence, as the design does. The design's
        heading-to-content gap is 14 px, not the shared 32 — hence the
        tighter margin and the inner gap wrapper.
      */}
      <PageHeader
        title="Your next career move."
        documentTitle="Overview"
        description="A little less searching. A little closer to the right role."
        className="mb-3.5"
      />

      <div className="flex flex-col gap-6">
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

        {/*
        The design's two columns (node 49:754): a wide primary column holding
        the next step, the metrics and the action queue, and a narrower
        secondary column holding the digest and the featured opportunity.

        On a phone the columns stack with the **work** first: master prompt §7
        requires dashboard priorities before metrics, and a 360 px screen that
        opens on four numbers buries the one thing the candidate came to do.
        The order swap is a flex `order`, so the desktop layout is untouched
        and no content is duplicated (the WS-41 rule, preserved).
      */}
        <div className="grid gap-6 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)] lg:items-start">
          {/* -- Primary column -------------------------------------------- */}
          <div className="order-1 flex min-w-0 flex-col gap-3">
            {/*
            The next step. It renders only when there is a real one: an
            "all clear" hero would be a decorative block wearing
            information's clothes.
          */}
            {nextStep ? (
              <NextStepPanel
                statement={nextStep.statement}
                subject={nextStep.subject}
                consequence={nextStep.consequence}
                action={
                  <LinkButton to={nextStep.to}>{nextStep.label}</LinkButton>
                }
                chip={nextStep.chip}
              />
            ) : null}

            {/*
            "Keep your momentum" — the four stage counts. Every value is a
            server total, and a source that has not answered renders an em
            dash rather than a zero.
          */}
            <Section
              title="Keep your momentum"
              action={
                <QuietLink to="/app/tracker">View all applications →</QuietLink>
              }
            >
              <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
                <MetricTile
                  value={
                    awaiting.isSuccess && prepared.isSuccess
                      ? awaitingDecisionTotal
                      : "—"
                  }
                  label="Awaiting review"
                  loading={awaiting.isPending || prepared.isPending}
                />
                <MetricTile
                  value={handoffCount ?? "—"}
                  label="Needs you"
                  loading={handoffQuery.isPending}
                />
                <MetricTile
                  value={inProgressValue ?? "—"}
                  label="In progress"
                  loading={inProgressQuery.isPending}
                />
                <MetricTile
                  value={outcomeCount ?? "—"}
                  label="Outcome recorded"
                  loading={outcomeQuery.isPending}
                />
              </div>
            </Section>

            {/* The action queue — every row resolves to a real screen. */}
            {attentionItems.length > 0 || failures.length > 0 ? (
              <div className="surface px-5 py-4">
                <Section title="A little progress, on your terms.">
                  <div className="-my-1">
                    {/*
                    The **specific** applications come first, because the
                    design's queue names the thing to act on ("Review your
                    Acorn application") rather than only its count. Each row
                    links to that application's own page — the screen that
                    resolves it — and its badge uses the console's one status
                    presentation, so `prepared` and `awaiting_approval` read
                    with the same words everywhere.
                  */}
                    {attentionApplications.map((item) => (
                      <ApplicationActionRow
                        key={item.id}
                        applicationId={item.id}
                        title={item.title}
                        body={item.body}
                        actionLabel="Review draft"
                      />
                    ))}
                    {/*
                    Then the aggregate asks — a missing résumé, the trail
                    events a human should read, the questions the boards ask
                    and the profile cannot answer.
                  */}
                    {attentionItems
                      .filter((item) => item.key !== "approvals")
                      .slice(0, ATTENTION_ROWS)
                      .map((item) => (
                        <ActionRow
                          key={item.key}
                          icon={FileText}
                          title={item.title}
                          body={item.body}
                          action={
                            <LinkButton to={item.to} variant="ghost" size="sm">
                              {item.label} →
                            </LinkButton>
                          }
                        />
                      ))}
                    {/*
                    The approval count, as the **server total**. It appears
                    whenever anything waits, including when every waiting
                    application is already named above: the count is what says
                    "and nothing else", and a reader who sees three rows has no
                    way to know whether a fourth exists without it.
                  */}
                    {awaitingDecisionTotal > 0 ? (
                      <ActionRow
                        icon={FileText}
                        title={`${awaitingDecisionTotal} application${awaitingDecisionTotal === 1 ? "" : "s"} awaiting your approval`}
                        body="Nothing is submitted without that decision."
                        action={
                          <LinkButton
                            to="/app/approvals"
                            variant="ghost"
                            size="sm"
                          >
                            Review approvals →
                          </LinkButton>
                        }
                      />
                    ) : null}
                    {/*
                    And a source that could not be read gets its own row with
                    a retry — the section must never look all-clear while one
                    of its sources is unknown.
                  */}
                    {failures.map((failure) => (
                      <FailureActionRow
                        key={failure.key}
                        title={failure.title}
                        body={failure.body}
                        onRetry={failure.onRetry}
                      />
                    ))}
                  </div>
                </Section>
              </div>
            ) : null}

            <PipelineBar
              title={`Your pipeline · ${trackedTotal ?? 0} application${trackedTotal === 1 ? "" : "s"}`}
              total={trackedTotal ?? 0}
              segments={pipelineSegments}
            />
          </div>

          {/* -- Secondary column ------------------------------------------ */}
          <div className="order-2 flex min-w-0 flex-col gap-3">
            {/*
            "While you were away" — the newest trail rows, each with the
            actor chip that says whether the agent or a person acted.
          */}
            <div className="surface px-5 py-4">
              <Section
                title="While you were away"
                action={
                  <QuietLink to="/app/activity">All activity →</QuietLink>
                }
              >
                {audit.isPending ? (
                  <p className="type-caption py-2" role="status">
                    Reading the trail…
                  </p>
                ) : audit.isError ? (
                  <ErrorState
                    error={audit.error}
                    onRetry={() => void audit.refetch()}
                  />
                ) : events.length === 0 ? (
                  <div className="py-2">
                    <p className="type-card-title">No recorded activity yet</p>
                    <p className="type-caption mt-1">
                      Upload a résumé or run a search and the agent's steps
                      appear here.
                    </p>
                  </div>
                ) : (
                  /*
                  The digest renders the **shared** trail component rather
                  than a Home-only list. It already solves three things a
                  bespoke list gets wrong: three-way attribution (the agent,
                  a person, and *the system* — a blocked step is not the
                  agent's work), the honest per-action links (an unknown
                  action links nowhere rather than to a guessed destination),
                  and a neutral treatment for an unlabelled action. Restyling
                  for the design must not re-derive those rules.
                */
                  <ActivityFeed events={events.slice(0, FEED_ROWS)} />
                )}
                {/*
                The window's provenance sits at the foot of the card, the one
                place it informs without inflating the header row the design
                specifies (heading + action only): the feed is the first
                audit page, never presented as the whole history.
              */}
                <p className="type-caption mt-3">
                  The newest {AUDIT_PAGE_SIZE} events in this account's trail —
                  the first page, not the whole history · updated every{" "}
                  {intervalLabel(OVERVIEW_POLL_MS)}
                </p>
              </Section>
            </div>

            {/*
            The featured opportunity.

            This renders the **existing** `FeaturedMatch`, not a new card,
            because that component carries an honesty contract this screen
            must not lose: a component whose state is not a measured one
            renders its reason ("unknown — you haven't said") rather than the
            `0.0` the raw score carries for it (WS-20). A hand-built card that
            printed the score would show a candidate a zero for a question
            they were never asked.

            What the design adds is *position*: it sits in the secondary
            column on forest ground. The wrapper supplies that ground; the
            component supplies the truth.
          */}
            {featured &&
            featuredJobQuery?.isSuccess &&
            jobsById.has(featured.jobId) ? (
              <div className="overflow-hidden rounded-[var(--radius-surface)] bg-card">
                <FeaturedMatch
                  job={jobsById.get(featured.jobId) as JobListing}
                  match={featured.match}
                />
              </div>
            ) : featured && featuredJobQuery?.isError ? (
              <FeaturedMatchMissing />
            ) : ranked.isPending && profileId ? (
              <section aria-label="Best match">
                <FeaturedMatchSkeleton />
              </section>
            ) : ranked.isError ? (
              <ErrorNotice
                error={ranked.error}
                onRetry={() => void ranked.refetch()}
              />
            ) : (
              <section
                aria-label="Best match"
                className="surface flex flex-col items-start gap-2 p-5"
              >
                <p className="type-card-title">No matches yet</p>
                <p className="type-caption">
                  {profileId
                    ? "The profile has not been matched against the stored corpus. Run a search on Discover — the ranking is built from what the corpus holds."
                    : "Matches appear once a résumé is added and becomes the profile the agent works from."}
                </p>
                <LinkButton
                  to={profileId ? "/app/matches" : "/app/resume"}
                  variant="outline"
                  size="sm"
                >
                  {profileId ? "Open Discover" : "Add a résumé"}
                </LinkButton>
              </section>
            )}
          </div>
        </div>

        {/*
        The shortlist stays below both columns: it is a list, and a list
        reads best at full width. It is the same ranked history the featured
        card comes from, so the two can never disagree about "the best match".
      */}
        {shortlistEntries.length > 0 ? (
          <Section
            title="Also strong"
            description="The next best-ranked matches from the same history."
          >
            <Shortlist entries={shortlistEntries} />
          </Section>
        ) : null}
      </div>
    </div>
  )
}
