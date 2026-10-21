import { useMutation } from "@tanstack/react-query"
import { useState } from "react"
import { Link } from "react-router-dom"

import { Banner } from "@/components/common/banner"
import { Disclosure } from "@/components/common/disclosure"
import { SectionTitle } from "@/components/common/field-list"
import { ErrorNotice } from "@/components/common/error-notice"
import { EmptyState, ProgressState } from "@/components/common/progress-state"
import { PlainText } from "@/components/common/plain-text"
import { PageHeader, Section } from "@/components/common/page-header"
import { OverallScore, ScoreGrid } from "@/components/common/score-grid"
import { Button } from "@/components/ui/button"
import { LinkButton } from "@/components/ui/link-button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"

import { api } from "@/lib/api/endpoints"
import { formatList } from "@/lib/format"
import { useCurrentProfileId } from "@/lib/profile"
import type { JobMatchPair, JobSearchResponse } from "@/lib/api/types"

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
      : `Scored against ${corpus.toLocaleString()} stored listings. This search never called a job board.`

  return filter.length > 0 ? `${scope} Filtered ${filter.join(" ")}.` : scope
}

/** One match in the ranked list. */
function MatchCard({ pair }: { pair: JobMatchPair }) {
  const { job, match } = pair
  return (
    <Card className="rounded-2xl transition-shadow duration-200 hover:shadow-[var(--shadow-paper)]">
      <CardHeader>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <CardTitle className="font-heading text-base">
              <Link
                to={`/matches/${encodeURIComponent(job.id)}`}
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

          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <SectionTitle>Matched requirements</SectionTitle>
              <PlainText className="mt-1.5">
                {formatList(match.matched_requirements)}
              </PlainText>
            </div>
            <div>
              <SectionTitle>Missing requirements</SectionTitle>
              <PlainText className="mt-1.5">
                {formatList(match.missing_requirements)}
              </PlainText>
            </div>
          </div>
        </Disclosure>

        <LinkButton
          variant="outline"
          size="sm"
          to={`/matches/${encodeURIComponent(job.id)}`}
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
  const [query, setQuery] = useState("")
  const [location, setLocation] = useState("")
  const [topN, setTopN] = useState(10)

  const search = useMutation({
    mutationFn: (body: {
      profile_id: string
      query?: string
      location?: string
      top_n: number
    }) => api.searchJobs(body),
  })

  if (!profileId) {
    return (
      <EmptyState
        title="No profile selected"
        description="A search matches a candidate profile against the stored job corpus. Upload a resume first."
        action={<LinkButton to="/resume">Go to the Resume screen</LinkButton>}
      />
    )
  }

  const data = search.data

  return (
    <div className="space-y-6">
      <PageHeader
        title="Find the work that fits"
        description="The search scores every listing the backend has stored against your profile. It never calls a job board — run a refresh on the Operations screen to bring new listings in."
      />

      <Card>
        <CardHeader>
          <CardTitle>Search the stored corpus</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <p className="text-sm text-muted-foreground">
            The search reads the jobs the backend has already stored — it does
            not call any job board. Run a refresh on the Operations screen to
            bring new listings in.
          </p>

          <form
            className="grid gap-3 sm:grid-cols-[2fr_2fr_6rem_auto] sm:items-end"
            onSubmit={(event) => {
              event.preventDefault()
              search.mutate({
                profile_id: profileId,
                query: query.trim() || undefined,
                location: location.trim() || undefined,
                top_n: topN,
              })
            }}
          >
            <div className="space-y-1">
              <label htmlFor="search-query" className="text-sm font-medium">
                Query
              </label>
              <Input
                id="search-query"
                value={query}
                placeholder="Any token in the title or description"
                onChange={(event) => setQuery(event.target.value)}
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
              title="Matching the profile against the corpus"
              description="The search embeds the profile once and scores the stored listings. This takes a few seconds."
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
                description="The corpus holds no listing that matches this profile and filter. Run a refresh on the Operations screen, or widen the filters."
              />
            ) : (
              <div className="space-y-4">
                {data.results.map((pair) => (
                  <MatchCard key={pair.job.id} pair={pair} />
                ))}
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
