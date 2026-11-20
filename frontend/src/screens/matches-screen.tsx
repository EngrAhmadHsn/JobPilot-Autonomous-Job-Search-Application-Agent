import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useEffect, useState, type ReactNode } from "react"
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
  JobSearchWorkplace,
} from "@/lib/api/types"

import { matchFromHistoryEntry } from "@/screens/discover/match-history"
import { MatchDetail } from "@/screens/discover/match-detail"
import { ResultsList } from "@/screens/discover/results-list"
import { ResultsSkeleton } from "@/screens/discover/results-skeleton"
import { SearchBanners } from "@/screens/discover/search-banners"
import {
  MAX_TOP_N,
  SearchPanel,
  workplaceLabel,
} from "@/screens/discover/search-panel"

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
 * The filters a search — and the URL that carries it — are made of.
 *
 * WS-44: the design's filter model. `query` is the text filter the search
 * box and the dialog's Skills field both fill; `workplace` and `location`
 * narrow the corpus server-side; `topN` is the ranked slice's size. All of
 * it lives in the URL (`?workplace=…&location=…&skills=…&top_n=…`)
 * alongside `?job=`, so a narrowed search is an address, not a memory.
 */
interface SearchFilters {
  query: string
  workplace: JobSearchWorkplace | ""
  location: string
  topN: number
}

/** The workplace values the URL's `workplace` param may carry. */
const WORKPLACE_PARAM_VALUES: JobSearchWorkplace[] = [
  "remote",
  "hybrid",
  "onsite",
]

function workplaceFromParam(raw: string | null): JobSearchWorkplace | "" {
  return WORKPLACE_PARAM_VALUES.includes(raw as JobSearchWorkplace)
    ? (raw as JobSearchWorkplace)
    : ""
}

/** The ranked slice a `top_n` param asks for, clamped; `undefined` if none. */
function topNFromParam(raw: string | null): number | undefined {
  if (!raw) return undefined
  const parsed = Number(raw)
  if (!Number.isFinite(parsed)) return undefined
  return Math.min(Math.max(1, Math.floor(parsed)), MAX_TOP_N)
}

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
  workplace: JobSearchWorkplace | ""
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
    const parsed = JSON.parse(raw) as Partial<StoredSearch>
    if (!parsed || typeof parsed !== "object" || !parsed.response) return null
    // A record written before WS-44 carries no workplace; absent stays "".
    return {
      query: typeof parsed.query === "string" ? parsed.query : "",
      location: typeof parsed.location === "string" ? parsed.location : "",
      workplace: workplaceFromParam(parsed.workplace ?? null),
      topN: typeof parsed.topN === "number" ? parsed.topN : MAX_TOP_N,
      response: parsed.response,
    }
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
 * Whether the filters a URL addresses are the filters a stored search ran.
 *
 * The stored response may only be presented beside filters it actually ran
 * with. A deep link that carries filter params for a *different* search
 * addresses a ranking this browser does not have — seeding the stored
 * response under those chips would present filters as applied that were
 * never applied to it, so nothing seeds and the screen asks for a search.
 */
function filtersMatchRecord(url: SearchFilters, record: StoredSearch): boolean {
  return (
    url.workplace === record.workplace &&
    url.location === record.location &&
    url.query === record.query &&
    url.topN === record.topN
  )
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
  filters: SearchFilters
): string {
  const corpus = data.stats.stored || data.stats.deduped
  const cap =
    data.results.length >= filters.topN
      ? ` — the first ${filters.topN.toLocaleString()} shown`
      : ""
  const filter = [
    filters.query.trim() ? `matching “${filters.query.trim()}”` : null,
    filters.location.trim() ? `in “${filters.location.trim()}”` : null,
    filters.workplace ? workplaceLabel(filters.workplace) : null,
  ].filter(Boolean)

  const scope =
    data.stats.found > 0
      ? `${data.stats.found} fetched · ${data.stats.dropped} dropped · ${data.stats.deduped} deduplicated · ${data.stats.persisted} persisted`
      : `Ranked against ${corpus.toLocaleString()} stored jobs${cap}.`

  return filter.length > 0 ? `${scope} Filtered ${filter.join(" ")}.` : scope
}

/** What the URL's filter params say, read once at mount. */
function filtersFromParams(searchParams: URLSearchParams): SearchFilters {
  const topN = topNFromParam(searchParams.get("top_n"))
  return {
    workplace: workplaceFromParam(searchParams.get("workplace")),
    location: searchParams.get("location") ?? "",
    query: searchParams.get("skills") ?? "",
    topN: topN ?? MAX_TOP_N,
  }
}

/**
 * The Discover screen (WS-36) — the reference panel 2 split view.
 *
 * Left: the search, the filter row the API actually supports (query/skills,
 * workplace, location, ranked-slice size — the dialog and chips of WS-44)
 * and the ranked results as dense rows. Right: the selected job's detail —
 * the reason for its score, the requirements it credited and the ones it
 * could not, the sponsorship signal as verified or unknown, and the two real
 * actions (Tailor, open the full listing). There is no save/shortlist action
 * because there is no save endpoint to wire it to.
 *
 * The selection lives in the URL (`?job=<id>`), so a refresh or a shared
 * link keeps it — and when ranked results are on screen with no `?job=`
 * addressed, the top-ranked match is selected by default and written to the
 * URL (replaced, not pushed), so the screen's first paint already shows the
 * "why". A selected job that is not in the loaded slice — a deep link, or a
 * selection that survived a new search — is resolved by its own reads: the
 * listing from `GET /api/jobs/{id}` (the same cache key the job route uses)
 * and its match from the persisted match history, rebuilt through the same
 * safe-accessor mirror the job route uses.
 *
 * The search runs against the **stored** corpus (the backend's FU-1
 * store-only search): no board is fetched while the operator is looking at
 * the screen. The screen's job is to show the ranking *and the reason for
 * it*, and to be honest about a degraded run.
 *
 * WS-44, the pane scroll: at `lg`+ the screen is a fixed-height flex under
 * the 68 px top bar — the header block (search row + chips) never scrolls,
 * and the results column and the detail column each scroll internally, so
 * the page itself never scrolls. Below `lg` the stacked layout keeps the
 * page scroll it always had. (`-mt-10 -mb-12` cancels the shell container's
 * desktop vertical padding, which the fixed height spans.)
 */
export function MatchesScreen() {
  const profileId = useCurrentProfileId()
  const queryClient = useQueryClient()
  const [searchParams, setSearchParams] = useSearchParams()
  const selectedId = searchParams.get("job")
  /*
    The boot snapshot: the stored search this browser has for this profile,
    and the filters the URL addresses. The URL is the addressed state — a
    param wins over the stored record's value, and the stored *response*
    only presents when the URL does not contradict it (no filter params at
    all, or params that are exactly what the stored search ran with).
  */
  const [boot] = useState(() => {
    const record = loadStoredSearch(profileId)
    const url = filtersFromParams(searchParams)
    // `top_n`'s presence is its own fact: absent means "the default 50",
    // not "50 was asked for" — and only a present value overrides the
    // stored record's.
    const topNParam = topNFromParam(searchParams.get("top_n"))
    const paramsPresent = Boolean(
      url.workplace || url.location || url.query || topNParam !== undefined
    )
    const response = record
      ? paramsPresent
        ? filtersMatchRecord(url, record)
          ? record.response
          : undefined
        : record.response
      : undefined
    return { record, url, topNParam, response }
  })
  const [query, setQuery] = useState(
    () => boot.url.query || boot.record?.query || ""
  )
  const [workplace, setWorkplace] = useState<JobSearchWorkplace | "">(
    () => boot.url.workplace || boot.record?.workplace || ""
  )
  const [location, setLocation] = useState(
    () => boot.url.location || boot.record?.location || ""
  )
  // The queries this browser has actually run, newest first (WS-42): the
  // suggestions popup's RECENT SEARCHES section reads from here.
  const [recentQueries, setRecentQueries] = useState(() =>
    loadRecentQueries(profileId)
  )
  // Whether the query combobox is showing its suggestions — the one state
  // the design gives its own heading copy to (node `47:333`).
  const [suggesting, setSuggesting] = useState(false)
  // The server ranks a slice of up to 50; the console shows it ten at a time.
  const [topN, setTopN] = useState(
    () => boot.topNParam ?? boot.record?.topN ?? MAX_TOP_N
  )
  const [visibleCount, setVisibleCount] = useState(PAGE_SIZE)

  /*
    The search runs from the button, so it is a mutation; this query never
    fetches. It exists to *carry* the result: seeded from the stored search
    at mount, updated by the mutation, and re-read on every remount — so the
    last ranking survives navigation within the session and a page reload.
  */
  const results = useQuery({
    queryKey: ["job-search", profileId],
    queryFn: async () => {
      throw new Error("searches are triggered by the search button")
    },
    enabled: false,
    staleTime: Infinity,
    initialData: boot.response,
  })

  const search = useMutation({
    mutationFn: (body: {
      profile_id: string
      query?: string
      location?: string
      workplace?: JobSearchWorkplace
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
          workplace: workplaceFromParam(variables.workplace ?? null),
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

  // -- The filters, in the URL. ----------------------------------------------
  /*
    Every search writes its whole filter set to the URL alongside `?job=`:
    absent params mean "no filter" (and `top_n` is written only when it is
    not the default 50), so `?workplace=…&location=…&skills=…&top_n=…` is a
    shareable, reloadable address of exactly what was searched.
  */
  function writeFilterParams(filters: SearchFilters) {
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev)
      const setOrDelete = (key: string, value: string) => {
        if (value) next.set(key, value)
        else next.delete(key)
      }
      setOrDelete("workplace", filters.workplace)
      setOrDelete("location", filters.location)
      setOrDelete("skills", filters.query)
      setOrDelete(
        "top_n",
        filters.topN !== MAX_TOP_N ? String(filters.topN) : ""
      )
      return next
    })
  }

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

  // -- The default selection. ------------------------------------------------
  /*
    When ranked results are on screen and no `?job=` is addressed, the top
    match is the selection: the screen's first paint shows the list *and*
    the "why" beside it, which is what the design's split view is for. The
    write is a **replace**, not a push — landing here is not a navigation
    the operator made, so back must not walk through it. A URL that already
    carries `?job=` is never overridden: a deep link, valid or not, resolves
    by its own reads exactly as it always has.
  */
  const firstRankedId = data?.results[0]?.job.id ?? null
  useEffect(() => {
    if (!firstRankedId || selectedId) return
    setSearchParams(
      (prev) => {
        if (prev.get("job")) return prev
        const next = new URLSearchParams(prev)
        next.set("job", firstRankedId)
        return next
      },
      { replace: true }
    )
  }, [firstRankedId, selectedId, setSearchParams])

  function runSearch(overrides?: Partial<SearchFilters>) {
    if (!profileId) return
    // The UI bounds Top N, and the submit clamps the value again, so the
    // screen never claims a cap the request did not ask for (the server
    // clamps a third time; see MAX_TOP_N above). The overrides exist for
    // the dialog's apply and the chips' removals: the action must run the
    // values it committed, not whatever the fields still hold from before.
    const requested = Math.min(
      Math.max(1, Math.floor(overrides?.topN ?? topN) || 1),
      MAX_TOP_N
    )
    setTopN(requested)
    if (overrides?.workplace !== undefined) setWorkplace(overrides.workplace)
    if (overrides?.location !== undefined) setLocation(overrides.location)
    if (overrides?.query !== undefined) setQuery(overrides.query)
    const filters: SearchFilters = {
      query: (overrides?.query ?? query).trim(),
      workplace: overrides?.workplace ?? workplace,
      location: (overrides?.location ?? location).trim(),
      topN: requested,
    }
    writeFilterParams(filters)
    search.mutate({
      profile_id: profileId,
      query: filters.query || undefined,
      location: filters.location || undefined,
      workplace: filters.workplace || undefined,
      top_n: filters.topN,
      only_embedded: false,
    })
  }

  function pickRecent(term: string) {
    setQuery(term)
    runSearch({ query: term })
  }

  function removeRecent(term: string) {
    setRecentQueries((current) => {
      const next = current.filter((item) => item !== term)
      if (profileId) saveRecentQueries(profileId, next)
      return next
    })
  }

  function applyFilters(draft: {
    workplace: JobSearchWorkplace | ""
    location: string
    skills: string
    topN: number
  }) {
    setQuery(draft.skills)
    setWorkplace(draft.workplace)
    setLocation(draft.location)
    setTopN(draft.topN)
    runSearch({
      query: draft.skills,
      workplace: draft.workplace,
      location: draft.location,
      topN: draft.topN,
    })
  }

  function clearNarrowing() {
    setWorkplace("")
    setLocation("")
    runSearch({ workplace: "", location: "" })
  }

  function clearSkills() {
    setQuery("")
    runSearch({ query: "" })
  }

  function clearTopN() {
    setTopN(MAX_TOP_N)
    runSearch({ topN: MAX_TOP_N })
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
    <div
      data-testid="discover-screen"
      className="space-y-5 lg:-mt-10 lg:-mb-12 lg:flex lg:h-[calc(100dvh-68px)] lg:flex-col lg:gap-5 lg:space-y-0 lg:overflow-hidden"
    >
      {/*
        WS-42: the design leads this screen with its statement, "Find your
        kind of work." (node `47:73`), and gives the suggestions state its
        own copy ("Find the right words.", node `47:333`). The tab keeps the
        stable screen name through `documentTitle` — the accessibility
        contract's "Discover · JobPilot" is unchanged.
      */}
      <PageHeader
        className="lg:shrink-0"
        title={suggesting ? "Find the right words." : "Find your kind of work."}
        documentTitle="Discover"
        description={
          suggesting
            ? "Autocomplete drawn from stored job titles."
            : "Search stored matches. Understand the fit before you commit."
        }
      />

      {/*
        WS-44, the pane scroll: the header block does not scroll. At `lg`+
        everything below it lives in the screen's own height, and the panes
        scroll inside themselves.
      */}
      <div className="lg:shrink-0">
        <SearchPanel
          query={query}
          onQueryChange={setQuery}
          workplace={workplace}
          location={location}
          topN={topN}
          onApplyFilters={applyFilters}
          onClearNarrowing={clearNarrowing}
          onClearSkills={clearSkills}
          onClearTopN={clearTopN}
          onSubmit={() => runSearch()}
          isPending={search.isPending}
          recentSearches={recentQueries}
          onPickRecent={pickRecent}
          onRemoveRecent={removeRecent}
          onSuggestingChange={setSuggesting}
        />
      </div>

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
          className="lg:min-h-0 lg:flex-1 lg:overflow-y-auto"
          title="Ranking your saved jobs"
          description="Scoring every listing against your profile."
        >
          <ResultsSkeleton />
        </Section>
      ) : data && data.results.length > 0 ? (
        <>
          <SearchBanners data={data} />

          {
            <div className="grid gap-6 lg:min-h-0 lg:flex-1 lg:grid-cols-[minmax(0,0.62fr)_minmax(0,1.38fr)] lg:grid-rows-[minmax(0,1fr)]">
              {/*
                The list column. On a phone the columns take turns: the
                results lead, and a selected job replaces the list with a
                full-height panel and a way back — never a squeezed column.

                WS-42: the ratio is the design's (node 49:865 — a ~398 px list
                beside an ~882 px detail, so about 0.62 : 1.38). The earlier
                1 : 1.4 made the list read as wide as the answer it introduces.

                WS-44: at `lg` the column is a fixed pane — its heading stays,
                and the rows scroll inside the pane below it.
              */}
              <section
                className={cn(
                  "min-w-0 lg:flex lg:min-h-0 lg:flex-col lg:overflow-hidden",
                  selectedId ? "hidden" : null
                )}
                aria-label="Ranked matches"
              >
                <div className="mb-3">
                  <h2 className="type-section">
                    {total > 0 ? `${total} matches` : "Ranked matches"}
                  </h2>
                  <p className="type-caption mt-1">
                    {describeSearch(data, { query, workplace, location, topN })}
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
                    <span className="inline-flex h-[37px] items-center rounded-lg px-2.5 text-[13px] leading-[19px] font-semibold text-forest">
                      Best match first ↓
                    </span>
                    <p role="status" className="type-caption tabular-nums">
                      Showing {Math.min(visibleCount, total)} of {total} ranked
                      matches.
                    </p>
                  </div>
                </div>
                <div
                  data-testid="results-scroll"
                  className="lg:min-h-0 lg:flex-1 lg:overflow-y-auto"
                >
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
                </div>
              </section>

              {/*
                The detail column, and its own scroll at `lg`: the answer to
                one job is often taller than the viewport, and the list must
                not lose its place because of it.
              */}
              <section
                className={cn(
                  "min-w-0 lg:min-h-0 lg:overflow-y-auto",
                  selectedId ? null : "hidden lg:block"
                )}
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
        <div className="max-w-[42rem] lg:min-h-0 lg:flex-1 lg:overflow-y-auto">
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
        <div className="max-w-[42rem] lg:min-h-0 lg:flex-1 lg:overflow-y-auto">
          <MatchDetail
            job={lookupListing}
            match={lookupMatch}
            matchReadFailed={lookupHistory.isError}
            onRetryMatch={() => void lookupHistory.refetch()}
            onBack={clearSelection}
          />
        </div>
      ) : data ? (
        <div className="lg:min-h-0 lg:flex-1 lg:overflow-y-auto">
          <EmptyState
            title="No stored jobs match"
            message="No stored listing matches this profile and filter. Try broader terms, or refresh the corpus from Operations to widen what the agent can rank."
            action={
              <LinkButton to="/app/operations" variant="outline" size="sm">
                Open Operations
              </LinkButton>
            }
          />
        </div>
      ) : (
        <div className="lg:min-h-0 lg:flex-1 lg:overflow-y-auto">
          <EmptyState
            title="No search yet"
            message="Run a search to rank the stored corpus against your profile. Every result arrives with the reason for its score."
          />
        </div>
      )}
    </div>
  )
}
