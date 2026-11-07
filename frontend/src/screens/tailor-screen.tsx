import { useMutation, useQueries, useQuery } from "@tanstack/react-query"
import { useRef, useState } from "react"
import { Link, useParams } from "react-router-dom"

import { Banner } from "@/components/common/banner"
import { ErrorNotice } from "@/components/common/error-notice"
import { FieldList, SectionTitle } from "@/components/common/field-list"
import { PlainText } from "@/components/common/plain-text"
import { EmptyState, ProgressState } from "@/components/common/progress-state"
import { OverallScore } from "@/components/common/score-grid"
import { PageHeader } from "@/components/common/page-header"
import { Button } from "@/components/ui/button"
import { LinkButton } from "@/components/ui/link-button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"

import { ApiError, apiUrl } from "@/lib/api/client"
import { api } from "@/lib/api/endpoints"
import { formatDateTime, formatList } from "@/lib/format"
import { useProfileWithFallback } from "@/hooks/use-profile-fallback"
import { asNumber, asRecord, asString } from "@/lib/safe"
import type { TailorResponse } from "@/lib/api/types"

/**
 * The factuality report.
 *
 * A factuality failure is **not** an error: the stripped content plus the
 * violations is the product. The report is rendered as a warning with the
 * removed items listed, never as a failure.
 */
function FactualityReport({
  factuality,
}: {
  factuality: TailorResponse["factuality"]
}) {
  const removed =
    factuality.removed_skills.length +
    factuality.removed_experience.length +
    factuality.removed_projects.length

  return (
    <Card>
      <CardHeader>
        <CardTitle>Factuality report</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        {factuality.passed ? (
          <Banner tone="success" title="Every claim is supported by the résumé">
            <p>
              The validator found nothing to strip: every skill, role and
              project in the tailored resume is stated by the document.
            </p>
          </Banner>
        ) : (
          <Banner
            tone="warning"
            title={`${removed} unsupported item(s) were removed`}
          >
            <p>
              The validator stripped what the resume does not state. The
              tailored resume below is the <em>reduced</em> one — the truthful
              one.
            </p>
          </Banner>
        )}

        <FieldList
          items={[
            {
              label: "Removed skills",
              value: formatList(factuality.removed_skills),
            },
            {
              label: "Removed experience",
              value: formatList(factuality.removed_experience),
            },
            {
              label: "Removed projects",
              value: formatList(factuality.removed_projects),
            },
          ]}
        />

        {factuality.violations.length > 0 ? (
          <div className="space-y-1">
            <SectionTitle>Violations</SectionTitle>
            <ul className="list-disc space-y-1 pl-5 text-sm">
              {factuality.violations.map((violation) => (
                <li key={violation}>
                  <PlainText as="span">{violation}</PlainText>
                </li>
              ))}
            </ul>
          </div>
        ) : null}
      </CardContent>
    </Card>
  )
}

/** The ATS analysis of the tailored resume. */
function AtsPanel({ ats }: { ats: TailorResponse["ats_report"] }) {
  const coverage = ats.keyword_coverage
  return (
    <Card>
      <CardHeader>
        <CardTitle>ATS report</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="flex items-baseline gap-3">
          <span className="text-2xl font-semibold tabular-nums">
            {ats.score.toFixed(1)}
          </span>
          <span className="text-xs text-muted-foreground">/ 100 ATS score</span>
          <span className="text-xs text-muted-foreground">
            title alignment {ats.title_alignment.toFixed(1)}
          </span>
        </div>

        <FieldList
          items={[
            {
              label: "Required keywords hit",
              value: `${coverage.required_hit.length} of ${coverage.required_hit.length + coverage.required_missing.length} (${(coverage.required_coverage * 100).toFixed(0)}%)`,
            },
            {
              label: "Required missing",
              value: formatList(coverage.required_missing),
            },
            {
              label: "Preferred hit",
              value: formatList(coverage.preferred_hit),
            },
            {
              label: "Preferred missing",
              value: formatList(coverage.preferred_missing),
            },
            {
              label: "Sections present",
              value:
                Object.entries(ats.section_completeness)
                  .map(
                    ([section, present]) =>
                      `${section}: ${present ? "yes" : "no"}`
                  )
                  .join(", ") || "none reported",
            },
            { label: "Format risks", value: formatList(ats.format_risks) },
            { label: "Notes", value: formatList(ats.notes) },
          ]}
        />
      </CardContent>
    </Card>
  )
}

/** The grounded insights about the job. */
function InsightsPanel({ insights }: { insights: TailorResponse["insights"] }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Grounded job insights</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <p className="text-xs text-muted-foreground">
          Every insight below is grounded in the listing text. Nothing here was
          fetched from the web, and nothing here was inferred.
        </p>
        {insights.summary ? <PlainText>{insights.summary}</PlainText> : null}
        <FieldList
          items={[
            {
              label: "Responsibilities",
              value: formatList(insights.responsibilities),
            },
            { label: "Tech stack", value: formatList(insights.tech_stack) },
            {
              label: "Seniority signals",
              value: formatList(insights.seniority_signals),
            },
            {
              label: "Culture flags",
              value: formatList(insights.culture_flags),
            },
          ]}
        />
      </CardContent>
    </Card>
  )
}

/** The tailored resume itself. */
function TailoredResumePanel({
  tailored,
}: {
  tailored: TailorResponse["tailored"]
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>The tailored resume</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div>
          <SectionTitle>Summary</SectionTitle>
          <PlainText>{tailored.summary}</PlainText>
        </div>

        <div>
          <SectionTitle>Highlighted skills</SectionTitle>
          <PlainText>{formatList(tailored.highlighted_skills)}</PlainText>
        </div>

        <div>
          <SectionTitle>Experience</SectionTitle>
          {tailored.experience.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              No experience entries.
            </p>
          ) : (
            tailored.experience.map((entry, index) => (
              <div key={`${entry.title}-${index}`} className="mt-2 text-sm">
                <p className="font-medium">
                  {entry.title}
                  {entry.company ? ` · ${entry.company}` : ""}
                </p>
                <ul className="list-disc pl-5 text-muted-foreground">
                  {entry.bullets.map((bullet, bulletIndex) => (
                    <li key={bulletIndex}>
                      <PlainText as="span">{bullet}</PlainText>
                    </li>
                  ))}
                </ul>
              </div>
            ))
          )}
        </div>

        {tailored.projects.length > 0 ? (
          <div>
            <SectionTitle>Projects</SectionTitle>
            {tailored.projects.map((project, index) => (
              <div key={`${project.name}-${index}`} className="mt-2 text-sm">
                <p className="font-medium">{project.name}</p>
                <ul className="list-disc pl-5 text-muted-foreground">
                  {project.bullets.map((bullet, bulletIndex) => (
                    <li key={bulletIndex}>
                      <PlainText as="span">{bullet}</PlainText>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        ) : null}

        <div>
          <SectionTitle>Cover letter</SectionTitle>
          <PlainText>{tailored.cover_letter}</PlainText>
        </div>
      </CardContent>
    </Card>
  )
}

/**
 * The Tailor screen for one job.
 *
 * The tailoring run takes about a minute (grounded research, generation, the
 * factuality validator, the DOCX render), so the screen shows the elapsed
 * time and offers a Cancel — which abandons the *wait*, not the server's
 * work, and says so.
 */
export function TailorJobScreen() {
  const { jobId = "" } = useParams()
  const { profileId } = useProfileWithFallback()
  const [run, setRun] = useState(0)
  const abortRef = useRef<AbortController | null>(null)

  const job = useQuery({
    queryKey: ["job", jobId],
    queryFn: ({ signal }) => api.getJob(jobId, signal),
    enabled: Boolean(jobId),
  })

  const tailor = useMutation({
    mutationFn: ({ profile, job }: { profile: string; job: string }) => {
      const controller = new AbortController()
      abortRef.current = controller
      return api.tailor({ profile_id: profile, job_id: job }, controller.signal)
    },
  })

  if (!profileId) {
    return (
      <EmptyState
        title="Tailoring needs a résumé first"
        description="A tailored résumé is built from your profile facts. Upload your résumé, then come back to this job."
        action={
          <div className="flex flex-wrap justify-center gap-2">
            <LinkButton to="/app/resume">Add your résumé</LinkButton>
            <LinkButton variant="outline" to="/app/matches">
              Find jobs that suit you
            </LinkButton>
          </div>
        }
      />
    )
  }

  if (job.error instanceof ApiError && job.error.status === 404) {
    return (
      <div className="space-y-10">
        <PageHeader
          title="Tailor the résumé for a job"
          description="Your résumé is rewritten for this job using only what it already says, then checked against the original and scored."
        />
        <EmptyState
          title="That job is not in your matched list"
          description="Pick one of your matched jobs and we will rewrite your résumé for it."
          action={
            <LinkButton to="/app/matches">Find jobs that suit you</LinkButton>
          }
        />
      </div>
    )
  }

  const result = tailor.data

  return (
    <div className="space-y-10">
      <PageHeader
        title={job.data ? job.data.job.title : "Tailor the resume"}
        description={
          job.data
            ? `${job.data.job.company}. Your résumé is rewritten for this job using only what it already says, then checked against the original and scored the way an employer's screening system would.`
            : "The agent rewrites the resume from your profile facts and checks every claim against your document."
        }
        actions={
          <Button
            disabled={tailor.isPending}
            onClick={() => {
              setRun((value) => value + 1)
              tailor.mutate({ profile: profileId, job: jobId })
            }}
          >
            {tailor.isPending
              ? "Tailoring…"
              : tailor.data
                ? "Tailor again"
                : "Tailor this resume"}
          </Button>
        }
      />

      {tailor.isPending ? (
        <ProgressState
          key={`tailor-${run}`}
          title="Tailoring the resume"
          description="Grounded research, generation, the factuality validator and the DOCX render. This takes about a minute."
          onCancel={() => abortRef.current?.abort()}
        >
          <p className="text-xs text-muted-foreground">
            Cancelling stops the console waiting. The server keeps working, and
            the result is stored under its own id.
          </p>
        </ProgressState>
      ) : null}

      {tailor.isError ? <ErrorNotice error={tailor.error} /> : null}

      {result ? (
        <>
          <Banner tone="success" title="The tailored resume is ready">
            <p>
              Stored as{" "}
              <code className="rounded bg-muted px-1 py-0.5 font-mono text-[11px]">
                {result.tailoring_id}
              </code>
              . The rendered file is on the server at{" "}
              <code className="rounded bg-muted px-1 py-0.5 font-mono text-[11px]">
                {result.docx_path}
              </code>
              .
            </p>
            <p className="mt-1">
              <a
                href={apiUrl(
                  `/api/tailored/${encodeURIComponent(result.tailoring_id)}/download`
                )}
                className="font-medium underline underline-offset-4"
                download
              >
                Download the DOCX
              </a>
            </p>
          </Banner>

          <FactualityReport factuality={result.factuality} />
          <TailoredResumePanel tailored={result.tailored} />
          <AtsPanel ats={result.ats_report} />
          <InsightsPanel insights={result.insights} />
        </>
      ) : (
        <EmptyState
          title="No tailoring yet"
          description="Run the tailoring to get a tailored résumé, its factuality report, the ATS analysis and the grounded insights."
        />
      )}
    </div>
  )
}

/**
 * The Tailor index: the jobs the current profile has been matched against.
 *
 * The API has no "list the jobs" endpoint, so the list is built from the
 * profile's **match history** — the jobs the profile was actually scored
 * against, which is the honest set to offer.
 */
export function TailorIndexScreen() {
  const { profileId, missing } = useProfileWithFallback()

  const history = useQuery({
    queryKey: ["profile-matches", profileId],
    queryFn: ({ signal }) => api.getProfileMatches(profileId as string, signal),
    enabled: Boolean(profileId) && !missing,
  })

  const entries = history.data?.matches ?? []

  const jobs = useQueries({
    queries: entries.slice(0, 25).map((entry) => {
      const jobId = asString(entry.job_id)
      return {
        queryKey: ["job", jobId],
        queryFn: ({ signal }: { signal: AbortSignal }) =>
          api.getJob(jobId, signal),
      }
    }),
  })

  /*
    The heading comes first, always. A screen that only shows an empty
    state with no heading reads as a broken screen; the heading says what
    the screen is for, and the empty state says what to do next.
  */
  const heading = (
    <PageHeader
      title="Tailor the résumé for a job"
      description="Pick a job and the agent rewrites your résumé for it, using only what your résumé already says. Every claim is checked against the original, and the result is scored the way an employer's screening system would."
    />
  )

  if (!profileId) {
    return (
      <div className="space-y-10">
        {heading}
        <EmptyState
          title="Tailoring needs a résumé first"
          description="A tailored résumé is built from your profile facts. Upload your résumé, then come back and pick the job to tailor for."
          action={
            <div className="flex flex-wrap justify-center gap-2">
              <LinkButton to="/app/resume">Add your résumé</LinkButton>
              <LinkButton variant="outline" to="/app/matches">
                Find jobs that suit you
              </LinkButton>
            </div>
          }
        />
      </div>
    )
  }

  return (
    <div className="space-y-8">
      {heading}

      {/*
        The way in for anyone who arrived here without a job: tailoring is
        per listing, and the listing comes from a search.
      */}
      <div className="rounded-2xl border border-dashed border-border bg-card/60 p-5">
        <p className="font-heading text-base font-semibold tracking-tight text-foreground">
          Find jobs that suit you
        </p>
        <p className="mt-1.5 max-w-prose text-sm leading-relaxed text-muted-foreground">
          Tailoring works on one job at a time. If you have not searched yet —
          or you want a different role — score the stored listings against your
          résumé first, then come back and tailor for the one you want.
        </p>
        <div className="mt-4">
          <LinkButton to="/app/matches">Find jobs that suit you</LinkButton>
        </div>
      </div>

      <Card className="rounded-2xl">
        <CardHeader>
          <CardTitle className="font-heading text-base font-semibold tracking-tight">
            Jobs already matched to this profile
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <p className="text-sm text-muted-foreground">
            The jobs this profile has been scored against, newest search first.
            A tailored résumé is produced for one profile and one job at a time.
          </p>

          {history.isPending && !missing ? (
            <ProgressState key="history" title="Loading the match history" />
          ) : null}

          {history.isError ? (
            <ErrorNotice
              error={history.error}
              onRetry={() => history.refetch()}
            />
          ) : null}

          {history.data && entries.length === 0 ? (
            <EmptyState
              title="No matches for this profile yet"
              description="Every job you have been matched against appears here."
              action={
                <LinkButton variant="outline" to="/app/matches">
                  Find jobs that suit you
                </LinkButton>
              }
            />
          ) : null}

          <ul className="divide-y divide-border/60">
            {entries.slice(0, 25).map((entry, index) => {
              const job = jobs[index]?.data
              const scores = asRecord(entry.scores)
              const overall = asNumber(scores.overall_score)
              const jobId = asString(entry.job_id)
              return (
                <li
                  key={`${jobId}-${index}`}
                  className="flex items-center justify-between gap-3 py-2"
                >
                  <div className="min-w-0">
                    <Link
                      to={`/app/tailor/${encodeURIComponent(jobId)}`}
                      className="font-medium underline-offset-4 hover:underline"
                    >
                      {job ? job.job.title : jobId}
                    </Link>
                    <p className="text-xs text-muted-foreground">
                      {job ? job.job.company : jobId} · matched{" "}
                      {formatDateTime(asString(entry.created_at) || null)}
                    </p>
                  </div>
                  {overall > 0 ? <OverallScore value={overall} /> : null}
                </li>
              )
            })}
          </ul>
        </CardContent>
      </Card>
    </div>
  )
}
