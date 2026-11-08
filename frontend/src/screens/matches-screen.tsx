import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useState } from "react"
import { Link } from "react-router-dom"

import { Banner } from "@/components/common/banner"
import { Disclosure } from "@/components/common/disclosure"
import { SectionTitle } from "@/components/common/field-list"
import { ErrorNotice } from "@/components/common/error-notice"
import { MatchGapChips, SponsorBadge } from "@/components/common/match-gap-chips"
import { Pagination } from "@/components/common/pagination"
import { QueryCombobox } from "@/components/common/query-combobox"
import { EmptyState, ProgressState } from "@/components/common/progress-state"
import { PlainText } from "@/components/common/plain-text"
import { PageHeader, Section } from "@/components/common/page-header"
import { OverallScore, ScoreGrid } from "@/components/common/score-grid"
import { Button } from "@/components/ui/button"
import { LinkButton } from "@/components/ui/link-button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"

import { api } from "@/lib/api/endpoints"
import { stagger } from "@/lib/stagger"
import { useCurrentProfileId } from "@/lib/profile"
import type { JobMatchPair, JobSearchResponse } from "@/lib/api/types"

/**
 * How many matches the console shows at once.
 *
 * The server ranks a slice of up to 50 listings; the console pages it ten at
 * a time, so a broad search is readable without one long scroll.
 */
const PAGE_SIZE = 10

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
 * What the search actually did, in words the operator can act on.
 *
 * The API's counters describe the *pipeline*, and a store-only search runs
 * almost none of it: `found` is zero because no board was contacted, and
 * `dropped` and `persisted` are zero because nothing was fetched or
 * written. Printing them would be noise that reads like a fault. What
 * matters is how much of the stored corpus was scored, and what the
 * filters were.
 */
function describeSearch(
  data: JobSearchResponse,
  query: string,
  location: string
): string {
  const corpus = data.stats.stored || data.stats.deduped
  const filter = [
    query.trim() ? `matching “${query.trim()}”` : null,
    location.trim() ? `in “${location.trim()}”` : null,
  ].filter(Boolean)

  const scope =
    data.stats.found > 0
      ? `${data.stats.found} fetched · ${data.stats.dropped} dropped · ${data.stats.deduped} deduplicated · ${data.stats.persisted} persisted`
      : `Ranked against ${corpus.toLocaleString()} saved jobs.`

  return filter.length > 0 ? `${scope} Filtered ${filter.join(" ")}.` : scope
}

/** One match in the ranked list. */
function MatchCard({
  pair,
  index = 0,
}: {
  pair: JobMatchPair
  index?: number
}) {
  const { job, match } = pair
  return (
    <Card
      {...stagger(
        index,
        "rounded-2xl transition-shadow duration-200 hover:shadow-[var(--shadow-paper)]"
      )}
    >
      <CardHeader>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <CardTitle className="font-heading text-base">
              <Link
                to={`/app/matches/${encodeURIComponent(job.id)}`}
                className="underline-offset-4 hover:underline"
              >
                {job.title}
              </Link>
            </CardTitle>
            <p className="text-sm text-muted-foreground">
              {job.company}
              {job.location ? ` · ${job.location}` : ""}
              {job.remote_policy ? ` · ${job.remote_policy}` : ""}
            </p>
          </div>
          <OverallScore value={match.overall_score} />
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        <Disclosure summary="Why this score" hint="the agent's reasoning">
          {match.explanation ? (
            <div>
              <SectionTitle>Explanation</SectionTitle>
              <PlainText className="mt-1.5 max-w-[72ch] leading-relaxed">
                {match.explanation}
              </PlainText>
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">
              The matching engine returned no explanation for this listing.
            </p>
          )}

          <ScoreGrid match={match} />

          <MatchGapChips
            matched={match.matched_requirements}
            missing={match.missing_requirements}
            className="mt-4"
          />
          <div className="mt-4">
            <SponsorBadge
              status={match.sponsor_status}
              note={match.sponsor_note}
            />
          </div>
        </Disclosure>

        <LinkButton
          variant="outline"
          size="sm"
          to={`/app/matches/${encodeURIComponent(job.id)}`}
        >
          Open the job
        </LinkButton>
      </CardContent>
    </Card>
  )
}

/** The banners that say what went wrong with the corpus, if anything did. */
function SearchBanners({ data }: { data: JobSearchResponse }) {
  const sourceErrors = Object.entries(data.source_errors)
  return (
    <div className="space-y-3">
      {data.degraded ? (
        <Banner tone="warning" title="The scoring was degraded">
          <p>
            Semantic scoring was unavailable for part of the corpus, so the
            scores below are weaker than a full run would be. The listings
            themselves are complete.
          </p>
        </Banner>
      ) : null}

      {sourceErrors.length > 0 ? (
        <Banner
          tone="warning"
          title={`${sourceErrors.length} job source(s) failed`}
        >
          <p>
            A failing source degrades the report, it does not fail the search.
            The corpus below is what the working sources returned.
          </p>
          <ul className="mt-1 list-disc pl-5">
            {sourceErrors.map(([source, message]) => (
              <li key={source}>
                <span className="font-medium">{source}</span>:{" "}
                <PlainText as="span">{message}</PlainText>
              </li>
            ))}
          </ul>
        </Banner>
      ) : null}
    </div>
  )
}

/**
 * The Matches screen.
 *
 * The search runs against the **stored** corpus (the backend's FU-1
 * store-only search): no board is fetched while the operator is looking at
 * the screen. The screen's job is to show the ranking *and the reason for
 * it*, and to be honest about a degraded run.
 */
export function MatchesScreen() {
  const profileId = useCurrentProfileId()
  const queryClient = useQueryClient()
  // The last search this browser made for this profile, if any — read once,
  // at mount, so leaving and returning (or reloading) shows it again.
  const [restored] = useState(() => loadStoredSearch(profileId))
  const [query, setQuery] = useState(restored?.query ?? "")
  const [location, setLocation] = useState(restored?.location ?? "")
  // The server ranks a slice of up to 50; the console shows it ten at a time.
  const [topN, setTopN] = useState(restored?.topN ?? 50)
  const [page, setPage] = useState(0)

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
      if (profileId) {
        saveStoredSearch(profileId, {
          query: variables.query ?? "",
          location: variables.location ?? "",
          topN: variables.top_n,
          response,
        })
      }
    },
  })

  if (!profileId) {
    return (
      <EmptyState
        title="No profile selected"
        description="A search compares your profile with the listings you have stored. Upload a résumé first."
        action={
          <LinkButton to="/app/resume">Go to the Resume screen</LinkButton>
        }
      />
    )
  }

  const data = results.data
  const total = data?.results.length ?? 0
  const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE))
  // Clamp rather than reset: a shorter result set after a new search lands on
  // its last page instead of an empty one, with no effect and no extra state.
  const currentPage = Math.min(page, pageCount - 1)
  const visible = data
    ? data.results.slice(
        currentPage * PAGE_SIZE,
        currentPage * PAGE_SIZE + PAGE_SIZE
      )
    : []

  return (
    <div className="space-y-6">
      <PageHeader
        title="Find the work that fits"
        description="Your saved jobs, ranked against your profile, each with the reason for its score."
      />

      {/*
        WS-21: the query suggestions panel is absolutely positioned from
        under the field and must extend past this card's edge. The shared
        Card clips by default (`overflow-hidden`) and every other screen
        relies on that, so the exception lives here, at the one call site —
        not in card.tsx.
      */}
      <Card className="overflow-visible">
        <CardHeader>
          <CardTitle>Search your saved listings</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <p className="text-sm text-muted-foreground">
            Search the jobs you have already saved. Add more from Operations
            when you want a wider search.
          </p>

          <form
            className="grid gap-3 sm:grid-cols-[2fr_2fr_6rem_auto] sm:items-end"
            onSubmit={(event) => {
              event.preventDefault()
              setPage(0)
              search.mutate({
                profile_id: profileId,
                query: query.trim() || undefined,
                location: location.trim() || undefined,
                top_n: topN,
                only_embedded: false,
              })
            }}
          >
            <div className="space-y-1">
              <label htmlFor="search-query" className="text-sm font-medium">
                Query
              </label>
              <QueryCombobox
                inputId="search-query"
                value={query}
                onChange={setQuery}
              />
            </div>
            <div className="space-y-1">
              <label htmlFor="search-location" className="text-sm font-medium">
                Location
              </label>
              <Input
                id="search-location"
                value={location}
                placeholder="Substring of the location"
                onChange={(event) => setLocation(event.target.value)}
              />
            </div>
            <div className="space-y-1">
              <label htmlFor="search-top-n" className="text-sm font-medium">
                Top N
              </label>
              <Input
                id="search-top-n"
                type="number"
                min={1}
                max={50}
                value={topN}
                onChange={(event) => setTopN(Number(event.target.value) || 1)}
              />
            </div>
            <Button type="submit" disabled={search.isPending}>
              {search.isPending ? "Searching…" : "Search"}
            </Button>
          </form>

          {search.isPending ? (
            <ProgressState
              key="search"
              title="Ranking your saved jobs"
              description="This takes a few seconds."
            />
          ) : null}

          {search.isError ? <ErrorNotice error={search.error} /> : null}
        </CardContent>
      </Card>

      {data ? (
        <Section
          title={`${data.results.length} match${data.results.length === 1 ? "" : "es"}`}
          description={describeSearch(data, query, location)}
        >
          <div className="space-y-4">
            <SearchBanners data={data} />

            {data.results.length === 0 ? (
              <EmptyState
                title="No matches"
                description="No stored listing matches this profile and filter. Refresh on the Operations screen, or widen the filters."
              />
            ) : (
              <div className="space-y-4">
                {visible.map((pair, index) => (
                  <MatchCard
                    key={pair.job.id}
                    pair={pair}
                    index={currentPage * PAGE_SIZE + index}
                  />
                ))}
                <Pagination
                  page={currentPage}
                  pageSize={PAGE_SIZE}
                  total={total}
                  onPageChange={setPage}
                  label="matches"
                />
              </div>
            )}
          </div>
        </Section>
      ) : (
        <EmptyState
          title="No search yet"
          description="Run a search to see the ranked matches for the current profile."
        />
      )}
    </div>
  )
}
