import { useQuery } from "@tanstack/react-query"
import { Link, useParams } from "react-router-dom"

import { ErrorNotice } from "@/components/common/error-notice"
import { FieldList, SectionTitle } from "@/components/common/field-list"
import { PlainText } from "@/components/common/plain-text"
import { EmptyState, ProgressState } from "@/components/common/progress-state"
import { OverallScore, ScoreGrid } from "@/components/common/score-grid"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"

import { api } from "@/lib/api/endpoints"
import { formatDateTime, formatList } from "@/lib/format"
import { useCurrentProfileId } from "@/lib/profile"
import { asNumber, asRecord, asStringArray } from "@/lib/safe"
import type { JobMatchResult } from "@/lib/api/types"

/**
 * The match of one job, rebuilt from the persisted match history.
 *
 * The history stores the component scores in a free-form dictionary (the
 * table has no schema for them), so the console reads them through the safe
 * accessors and rebuilds the same shape the search response uses.
 */
function matchFromHistory(
  entry: { scores: unknown; explanation: unknown } | undefined
): JobMatchResult | null {
  if (!entry) return null
  const scores = asRecord(entry.scores)
  return {
    overall_score: asNumber(scores.overall_score),
    semantic_score: asNumber(scores.semantic_score),
    skill_score: asNumber(scores.skill_score),
    experience_score: asNumber(scores.experience_score),
    seniority_score: asNumber(scores.seniority_score),
    location_score: asNumber(scores.location_score),
    preference_score: asNumber(scores.preference_score),
    missing_requirements: asStringArray(scores.missing_requirements),
    matched_requirements: asStringArray(scores.matched_requirements),
    explanation: typeof entry.explanation === "string" ? entry.explanation : "",
  }
}

/**
 * One job listing, with the match the current profile scored against it.
 *
 * Every value here came from a third party (a job board) or from the
 * matching engine, and every one of them is rendered as plain text.
 */
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
    queryFn: ({ signal }) => api.getProfileMatches(profileId as string, signal),
    enabled: Boolean(profileId),
  })

  if (job.isPending) {
    return <ProgressState key="job" title="Loading the job listing" />
  }

  if (job.isError) {
    return <ErrorNotice error={job.error} onRetry={() => job.refetch()} />
  }

  const listing = job.data.job
  const match = matchFromHistory(
    history.data?.matches.find((entry) => entry.job_id === listing.id) as
      { scores: unknown; explanation: unknown } | undefined
  )

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="font-heading text-xl font-semibold">
            {listing.title}
          </h2>
          <p className="text-sm text-muted-foreground">
            {listing.company}
            {listing.location ? ` · ${listing.location}` : ""}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {match ? <OverallScore value={match.overall_score} /> : null}
          <Button
            nativeButton={false}
            render={<Link to={`/tailor/${encodeURIComponent(listing.id)}`} />}
          >
            Tailor for this job
          </Button>
        </div>
      </div>

      {match ? (
        <Card>
          <CardHeader>
            <CardTitle>Why this job ranked</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            {match.explanation ? (
              <PlainText>{match.explanation}</PlainText>
            ) : (
              <p className="text-sm text-muted-foreground">
                The matching engine returned no explanation for this listing.
              </p>
            )}
            <ScoreGrid match={match} />
            <div className="grid gap-3 sm:grid-cols-2">
              <div>
                <SectionTitle>Matched requirements</SectionTitle>
                <PlainText>{formatList(match.matched_requirements)}</PlainText>
              </div>
              <div>
                <SectionTitle>Missing requirements</SectionTitle>
                <PlainText>{formatList(match.missing_requirements)}</PlainText>
              </div>
            </div>
          </CardContent>
        </Card>
      ) : (
        <EmptyState
          title="No match history for this job"
          description="The current profile has not been matched against this listing yet. Run a search on the Matches screen."
        />
      )}

      <Card>
        <CardHeader>
          <CardTitle>The listing</CardTitle>
        </CardHeader>
        <CardContent>
          <FieldList
            items={[
              { label: "Company", value: listing.company },
              { label: "Location", value: listing.location || "—" },
              { label: "Remote policy", value: listing.remote_policy || "—" },
              {
                label: "Employment type",
                value: listing.employment_type || "—",
              },
              {
                label: "Salary",
                value: listing.salary
                  ? `${listing.salary}${listing.currency ? ` ${listing.currency}` : ""}`
                  : "—",
              },
              { label: "Seniority", value: listing.seniority || "—" },
              {
                label: "Required skills",
                value: formatList(listing.required_skills),
              },
              {
                label: "Preferred skills",
                value: formatList(listing.preferred_skills),
              },
              {
                label: "Experience",
                value: listing.experience_requirements || "—",
              },
              {
                label: "Education",
                value: listing.education_requirements || "—",
              },
              { label: "Posted", value: formatDateTime(listing.posted_at) },
              {
                label: "Source",
                value: `${listing.source}${listing.source_job_id ? ` · ${listing.source_job_id}` : ""}`,
              },
              {
                label: "Apply at",
                value: listing.application_url ? (
                  <a
                    href={listing.application_url}
                    target="_blank"
                    rel="noreferrer noopener"
                    className="break-all underline underline-offset-4"
                  >
                    {listing.application_url}
                  </a>
                ) : (
                  "—"
                ),
              },
            ]}
          />

          <div className="mt-4 space-y-2">
            <SectionTitle>Description</SectionTitle>
            {listing.description ? (
              <PlainText>{listing.description}</PlainText>
            ) : (
              <p className="text-sm text-muted-foreground">
                The listing has no description.
              </p>
            )}
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
