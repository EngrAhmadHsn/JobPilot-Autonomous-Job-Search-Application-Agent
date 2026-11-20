import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useState, type ReactNode } from "react"
import { useSearchParams } from "react-router-dom"
import { cn } from "cn"

import { CardSkeleton } from "@/components/common/card-skeleton"
import { ErrorNotice } from "@/components/common/error-notice"
import { EmptyState } from "@/components/ui/empty-state"
import { ErrorState } from "@/components/ui/error-state"
import { LinkButton } from "@/components/ui/link-button"
import { PageHeader, Section } from "@/components/ui/page-header"
import { MousePointerClickIcon } from "lucide-react"

import { api } from "@/lib/api/endpoints"
import { useCurrentProfileId } from "@/lib/profile"
import type {
  JobListing,
  JobMatchResult,
  JobSearchResponse,
} from "@/lib/api/types"

import { matchFromHistoryEntry } from "@/screens/discover/match-history"
import { MatchDetail } from "@/screens/discover/match-detail"
import { ResultsList } from "@/screens/discover/results-list"
import { ResultsSkeleton } from "@/screens/discover/results-skeleton"
import { SearchBanners } from "@/screens/discover/search-banners"
import { SearchPanel } from "@/screens/discover/search-panel"

/**
 * How many matches the console shows at once.
 *
 * The server ranks a slice of up to `MAX_TOP_N` listings and returns it in
 * one response; the console shows that slice ten rows at a time and extends
 * the window with "Show more". The count line always states the slice's
 * whole size — a loaded window is never presented as the total.
 */
const PAGE_SIZE = 10

/**
 * The largest ranked slice the server will return.
 *
 * Mirrors `MAX_TOP_N` in `src/graph/job_executor.py`; the server clamps
 * again, so this bound only keeps the screen's own "the first N shown"
 * wording true about a request it actually made.
 */
const MAX_TOP_N = 50

/**
 * The last search, kept across navigation and reloads (WS-21 follow-up).
 *
 * A search is a **mutation**: its result lived in the component, so leaving
 * the screen discarded it — and with a slow search that meant paying the
 * whole cost again just to look at what you already had. The result is
 * therefore written to the query cache under a per-profile key (navigation
 * keeps it) and mirrored to localStorage (a reload keeps it). Only listings
 * are stored, and only in the operator's own browser.
 */
interface StoredSearch {
  query: string
  location: string
  topN: number
  response: JobSearchResponse
}

function storedSearchKey(profileId: string): string {
  return `ajp.lastSearch.${profileId}`
}

function loadStoredSearch(profileId: string | null): StoredSearch | null {
  if (!profileId) return null
  try {
    const raw = window.localStorage.getItem(storedSearchKey(profileId))
    if (!raw) return null
    const parsed = JSON.parse(raw) as StoredSearch
    if (!parsed || typeof parsed !== "object" || !parsed.response) return null
    return parsed
  } catch {
    return null
  }
}

function saveStoredSearch(profileId: string, record: StoredSearch): void {
  try {
    window.localStorage.setItem(
      storedSearchKey(profileId),
      JSON.stringify(record)
    )
  } catch {
    // A storage refusal (quota, private mode) must never fail the search.
  }
}

/**
 * The recent queries this browser searched for, newest first (WS-42, node
 * `49:1559` — the suggestions popup's RECENT SEARCHES section).
 *
 * The stored search above keeps the last *result*; this keeps the last
 * *words*, so the popup can offer them back. Only the operator's own past
 * queries, only in their own browser — and every entry is a query the
 * operator actually ran, never a suggestion invented for them.
 */
const RECENT_QUERIES_LIMIT = 4

function recentQueriesKey(profileId: string): string {
  return `ajp.recentQueries.${profileId}`
}

function loadRecentQueries(profileId: string | null): string[] {
  if (!profileId) return []
  try {
    const raw = window.localStorage.getItem(recentQueriesKey(profileId))
    const parsed: unknown = raw ? JSON.parse(raw) : null
    if (!Array.isArray(parsed)) return []
    return parsed
      .filter((item): item is string => typeof item === "string")
      .slice(0, RECENT_QUERIES_LIMIT)
  } catch {
    return []
  }
}

function saveRecentQueries(profileId: string, queries: string[]): void {
  try {
    window.localStorage.setItem(
      recentQueriesKey(profileId),
      JSON.stringify(queries.slice(0, RECENT_QUERIES_LIMIT))
    )
  } catch {
    // A storage refusal (quota, private mode) must never fail the search.
  }
}

/**
 * What the search actually did, in words the operator can act on.
 *
 * The API's counters describe the *pipeline*, and a store-only search runs
 * almost none of it: `found` is zero because no board was contacted, and
 * `dropped` and `persisted` are zero because nothing was fetched or
 * written. Printing them would be noise that reads like a fault. What
 * matters is how much of the stored corpus was scored, what the filters
 * were — and, when the ranked slice came back full, that the slice is a
 * slice: the honest "the first N shown" cap label (the same pattern the
 * Home screen uses for its ranked-slice reads).
 */
function describeSearch(
  data: JobSearchResponse,
  query: string,
  location: string,
  topN: number
): string {
  const corpus = data.stats.stored || data.stats.deduped
  const cap =
    data.results.length >= topN
      ? ` — the first ${topN.toLocaleString()} shown`
      : ""
  const filter = [
    query.trim() ? `matching “${query.trim()}”` : null,
    location.trim() ? `in “${location.trim()}”` : null,
  ].filter(Boolean)

  const scope =
    data.stats.found > 0
      ? `${data.stats.found} fetched · ${data.stats.dropped} dropped · ${data.stats.deduped} deduplicated · ${data.stats.persisted} persisted`
      : `Ranked against ${corpus.toLocaleString()} stored jobs${cap}.`

  return filter.length > 0 ? `${scope} Filtered ${filter.join(" ")}.` : scope
}

/**
 * The Discover screen (WS-36) — the reference panel 2 split view.
 *
 * Left: the search, the filter row the API actually supports (query, location
 * substring, ranked-slice size) and the ranked results as dense rows. Right:
 * the selected job's detail — the reason for its score, the requirements it
 * credited and the ones it could not, the sponsorship signal as verified or
 * unknown, and the two real actions (Tailor, open the full listing). There is
 * no save/shortlist action because there is no save endpoint to wire it to.
 *
 * The selection lives in the URL (`?job=<id>`), so a refresh or a shared link
 * keeps it. A selected job that is not in the loaded slice — a deep link, or
 * a selection that survived a new search — is resolved by its own reads: the
 * listing from `GET /api/jobs/{id}` (the same cache key the job route uses)
 * and its match from the persisted match history, rebuilt through the same
 * safe-accessor mirror the job route uses.
 *
 * The search runs against the **stored** corpus (the backend's FU-1
 * store-only search): no board is fetched while the operator is looking at
 * the screen. The screen's job is to show the ranking *and the reason for
 * it*, and to be honest about a degraded run.
 */
export function MatchesScreen() {
  const profileId = useCurrentProfileId()
  const queryClient = useQueryClient()
  const [searchParams, setSearchParams] = useSearchParams()
  const selectedId = searchParams.get("job")
  // The last search this browser made for this profile, if any — read once,
  // at mount, so leaving and returning (or reloading) shows it again.
  const [restored] = useState(() => loadStoredSearch(profileId))
  const [query, setQuery] = useState(restored?.query ?? "")
  const [location, setLocation] = useState(restored?.location ?? "")
  // The queries this browser has actually run, newest first (WS-42): the
  // suggestions popup's RECENT SEARCHES section reads from here.
  const [recentQueries, setRecentQueries] = useState(() =>
    loadRecentQueries(profileId)
  )
  // Whether the query combobox is showing its suggestions — the one state
  // the design gives its own heading copy to (node `47:333`).
  const [suggesting, setSuggesting] = useState(false)
  // The server ranks a slice of up to 50; the console shows it ten at a time.
  const [topN, setTopN] = useState(restored?.topN ?? MAX_TOP_N)
  const [visibleCount, setVisibleCount] = useState(PAGE_SIZE)

  /*
    The search runs from the button, so it is a mutation; this query never
    fetches. It exists to *carry* the result: seeded from the stored search at
    mount, updated by the mutation, and re-read on every remount — so the
    last ranking survives navigation within the session and a page reload.
  */
  const results = useQuery({
    queryKey: ["job-search", profileId],
    queryFn: async () => {
      throw new Error("searches are triggered by the search button")
    },
    enabled: false,
    staleTime: Infinity,
    initialData: restored?.response,
  })

  const search = useMutation({
    mutationFn: (body: {
      profile_id: string
      query?: string
      location?: string
      top_n: number
      only_embedded: boolean
    }) => api.searchJobs(body),
    onSuccess: (response, variables) => {
      queryClient.setQueryData(["job-search", profileId], response)
      setVisibleCount(PAGE_SIZE)
      if (profileId) {
        saveStoredSearch(profileId, {
          query: variables.query ?? "",
          location: variables.location ?? "",
          topN: variables.top_n,
          response,
        })
        // The words that were actually run lead the recent list (WS-42).
        const term = (variables.query ?? "").trim()
        if (term) {
          setRecentQueries((current) => {
            const next = [
              term,
              ...current.filter((item) => item !== term),
            ].slice(0, RECENT_QUERIES_LIMIT)
            saveRecentQueries(profileId, next)
            return next
          })
        }
      }
    },
  })

  const data = results.data

  // -- The selected job, resolved. ------------------------------------------
  // In the loaded slice, the pair carries everything; outside it (a deep
  // link, or a selection that survived a new search), the listing and the
  // persisted match are looked up under the same cache keys the job route
  // uses, so navigating on costs no second request.
  const selectedPair = data
    ? data.results.find((pair) => pair.job.id === selectedId)
    : undefined
  const needsLookup = Boolean(selectedId) && !selectedPair
  const lookupJob = useQuery({
    queryKey: ["job", selectedId],
    queryFn: ({ signal }) => api.getJob(selectedId as string, signal),
    enabled: needsLookup,
    retry: false,
  })
  const lookupHistory = useQuery({
    queryKey: ["profile-matches", profileId],
    queryFn: ({ signal }) =>
      api.getProfileMatches(profileId as string, { signal }),
    enabled: needsLookup && Boolean(profileId),
    retry: false,
  })
  const lookupMatch: JobMatchResult | null = needsLookup
    ? matchFromHistoryEntry(
        lookupHistory.data?.matches.find(
          (entry) => (entry.job_id as string) === selectedId
        )
      )
    : null
  const lookupListing: JobListing | null = lookupJob.data?.job ?? null

  function runSearch(override?: string) {
    if (!profileId) return
    // The UI bounds Top N, and the submit clamps the value again, so the
    // screen never claims a cap the request did not ask for (the server
    // clamps a third time; see MAX_TOP_N above). The override exists for
    // the recent-search chips: the click must run the chip's words, not
    // whatever the field still holds from before.
    const requested = Math.min(Math.max(1, Math.floor(topN) || 1), MAX_TOP_N)
    setTopN(requested)
    const term = (override ?? query).trim()
    search.mutate({
      profile_id: profileId,
      query: term || undefined,
      location: location.trim() || undefined,
      top_n: requested,
      only_embedded: false,
    })
  }

  function pickRecent(term: string) {
    setQuery(term)
    runSearch(term)
  }

  function removeRecent(term: string) {
    setRecentQueries((current) => {
      const next = current.filter((item) => item !== term)
      if (profileId) saveRecentQueries(profileId, next)
      return next
    })
  }

  function selectJob(jobId: string) {
    setSearchParams({ job: jobId })
  }

  function clearSelection() {
    setSearchParams({})
  }

  const total = data?.results.length ?? 0

  let detail: ReactNode = null
  if (!selectedId) {
    detail = (
      <EmptyState
        icon={MousePointerClickIcon}
        title="Select a job"
        message="Pick a result to see why it matches — the reasoning, the requirements and the sponsorship signal, beside the list."
      />
    )
  } else if (selectedPair) {
    detail = (
      <MatchDetail
        job={selectedPair.job}
        match={selectedPair.match}
        onBack={clearSelection}
      />
    )
  } else if (lookupJob.isPending) {
    // A deep-linked job whose listing is on the way: bones of the panel,
    // not a blank column.
    detail = <CardSkeleton rows={4} />
  } else if (lookupJob.isError) {
    detail = (
      <ErrorState
        error={lookupJob.error}
        onRetry={() => void lookupJob.refetch()}
      />
    )
  } else if (lookupListing) {
    detail = (
      <MatchDetail
        job={lookupListing}
        match={lookupMatch}
        matchReadFailed={lookupHistory.isError}
        onRetryMatch={() => void lookupHistory.refetch()}
        onBack={clearSelection}
      />
    )
  }

  if (!profileId) {
    return (
      <div className="space-y-5">
        <PageHeader
          title="Find your kind of work."
          documentTitle="Discover"
          description="Search stored matches. Understand the fit before you commit."
        />
        <EmptyState
          title="No profile selected"
          message="A search compares your profile with the listings you have stored. Upload a résumé first."
          action={
            <LinkButton to="/app/resume">Go to the Resume screen</LinkButton>
          }
        />
      </div>
    )
  }

  return (
    <div className="space-y-5">
      {/*
        WS-42: the design leads this screen with its statement, "Find your
        kind of work." (node `47:73`), and gives the suggestions state its
        own copy ("Find the right words.", node `47:333`). The tab keeps the
        stable screen name through `documentTitle` — the accessibility
        contract's "Discover · JobPilot" is unchanged.
      */}
      <PageHeader
        title={suggesting ? "Find the right words." : "Find your kind of work."}
        documentTitle="Discover"
        description={
          suggesting
            ? "Autocomplete drawn from stored job titles."
            : "Search stored matches. Understand the fit before you commit."
        }
      />

      <SearchPanel
        query={query}
        onQueryChange={setQuery}
        location={location}
        onLocationChange={setLocation}
        topN={topN}
        onTopNChange={setTopN}
        onSubmit={runSearch}
        isPending={search.isPending}
        recentSearches={recentQueries}
        onPickRecent={pickRecent}
        onRemoveRecent={removeRecent}
        onSuggestingChange={setSuggesting}
      />

      {search.isError ? <ErrorNotice error={search.error} /> : null}

      {/*
        A running search shows the **shape** of the answer, not a stopwatch.
        The skeleton reserves the space, so the list does not jump when the
        ranking lands.

        `search.isPending` wins over `data`: a re-search must not stack a
        placeholder over the previous ranking, which would read as "these are
        last time's numbers, still updating".
      */}
      {search.isPending ? (
        <Section
          title="Ranking your saved jobs"
          description="Scoring every listing against your profile."
        >
          <ResultsSkeleton />
        </Section>
      ) : data && data.results.length > 0 ? (
        <>
          <SearchBanners data={data} />

          {
            <div className="grid gap-6 lg:grid-cols-[minmax(0,0.62fr)_minmax(0,1.38fr)] lg:items-start">
              {/*
                The list column. On a phone the columns take turns: the
                results lead, and a selected job replaces the list with a
                full-height panel and a way back — never a squeezed column.

                WS-42: the ratio is the design's (node 49:865 — a ~398 px list
                beside an ~882 px detail, so about 0.62 : 1.38). The earlier
                1 : 1.4 made the list read as wide as the answer it introduces.
              */}
              <section
                className={cn("min-w-0", selectedId ? "hidden lg:block" : null)}
                aria-label="Ranked matches"
              >
                <div className="mb-3">
                  <h2 className="type-section">
                    {total > 0 ? `${total} matches` : "Ranked matches"}
                  </h2>
                  <p className="type-caption mt-1">
                    {describeSearch(data, query, location, topN)}
                  </p>
                  {/*
                    The sort affordance, as the design draws it (node `49:869`:
                    "Best match first ↓" under the count heading). The console
                    has exactly one ordering — the server always returns the
                    slice ranked best first, and no endpoint offers another —
                    so the affordance states that fact rather than offering a
                    menu of sorts that do not exist. The window line beside it
                    stays the honest "Showing X of Y".
                  */}
                  <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1">
                    <span className="inline-flex h-[37px] items-center rounded-lg px-2.5 text-[13px] font-semibold leading-[19px] text-forest">
                      Best match first ↓
                    </span>
                    <p
                      role="status"
                      className="type-caption tabular-nums"
                    >
                      Showing {Math.min(visibleCount, total)} of {total} ranked
                      matches.
                    </p>
                  </div>
                </div>
                <ResultsList
                  pairs={data.results}
                  visibleCount={visibleCount}
                  onShowMore={() => {
                    setVisibleCount((count) => count + PAGE_SIZE)
                  }}
                  selectedId={selectedId}
                  onSelect={selectJob}
                  pageSize={PAGE_SIZE}
                />
              </section>

              <section
                className={cn("min-w-0", selectedId ? null : "hidden lg:block")}
                aria-label="The selected job"
              >
                {detail}
              </section>
            </div>
          }
        </>
      ) : selectedId && lookupJob.isPending ? (
        // A deep link into this screen (or a selection whose slice is gone):
        // the listing is on the way, so the panel's bones reserve the shape.
        <div className="max-w-[42rem]">
          <CardSkeleton rows={4} />
        </div>
      ) : selectedId && lookupJob.isError ? (
        <ErrorState
          error={lookupJob.error}
          onRetry={() => void lookupJob.refetch()}
        />
      ) : selectedId && lookupListing ? (
        // The deep-linked job outside any loaded slice: the detail stands on
        // its own until a search gives it a list to sit beside.
        <div className="max-w-[42rem]">
          <MatchDetail
            job={lookupListing}
            match={lookupMatch}
            matchReadFailed={lookupHistory.isError}
            onRetryMatch={() => void lookupHistory.refetch()}
            onBack={clearSelection}
          />
        </div>
      ) : data ? (
        <EmptyState
          title="No stored jobs match"
          message="No stored listing matches this profile and filter. Try broader terms, or refresh the corpus from Operations to widen what the agent can rank."
          action={
            <LinkButton to="/app/operations" variant="outline" size="sm">
              Open Operations
            </LinkButton>
          }
        />
      ) : (
        <EmptyState
          title="No search yet"
          message="Run a search to rank the stored corpus against your profile. Every result arrives with the reason for its score."
        />
      )}
    </div>
  )
}
