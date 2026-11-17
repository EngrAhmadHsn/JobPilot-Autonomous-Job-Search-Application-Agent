import { useMutation, useQueries, useQuery } from "@tanstack/react-query"
import { useRef, useState } from "react"
import { Link, useParams } from "react-router-dom"

import { Banner } from "@/components/common/banner"
import { ErrorNotice } from "@/components/common/error-notice"
import { FieldList } from "@/components/common/field-list"
import { EmptyState, ProgressState } from "@/components/common/progress-state"
import { OverallScore } from "@/components/common/score-grid"
import { PageHeader } from "@/components/ui/page-header"
import { Button } from "@/components/ui/button"
import { LinkButton } from "@/components/ui/link-button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"

import { ApiError, apiUrl } from "@/lib/api/client"
import { api } from "@/lib/api/endpoints"
import { formatDateTime } from "@/lib/format"
import { useProfileWithFallback } from "@/hooks/use-profile-fallback"
import { asRecord, asString } from "@/lib/safe"
import type { TailorResponse } from "@/lib/api/types"

import { CoverLetterPanel } from "@/screens/studio/cover-letter-panel"
import { coverageIsMeasurable } from "@/screens/studio/diff-model"
import { KeywordPanel } from "@/screens/studio/keyword-panel"
import {
  AtsPanel,
  FactualityReport,
  InsightsPanel,
  RenderPanel,
  StylePanel,
} from "@/screens/studio/report-panels"
import { ResumeDiffView } from "@/screens/studio/resume-diff"

/*
  The Resume Studio (WS-37) — the Application Workspace of reference panel 3.

  One job, one tailoring run, every real report, and the original-versus-
  tailored comparison. The tabs carry the capabilities the tailoring result
  actually holds: Overview (the deliverable and how it was produced), Resume
  (the read-only diff beside keyword matching), Cover Letter (an editable
  draft the server does not store), Research (the grounded insights) and
  Validation (factuality, ATS and style). The reference's Questions tab is
  not here because the tailoring holds no board questions — those exist in
  the prepare/approval flow, and an empty tab would be a promise of data
  this endpoint does not return.

  Safety lines this screen keeps (master prompt §6.4/§9): the original
  document is immutable and never edited by this screen; a failed factuality
  report is content with visual weight above the tabs, never hidden behind a
  green ATS score; the diff is read-only because there is no per-change
  revision model behind it (the Task 1 audit — see the WS-37 report — and
  the lead's decision); missing keywords stay honest gaps unless the profile
  supports them; and a model failure shows the API's own actionable error.
*/

/**
 * What the deliverable's file is, named for the candidate (WS-31).
 *
 * The tailoring keeps the uploaded format, so a résumé that arrived as plain
 * text comes back as plain text. The download link says which one it is rather
 * than promising a DOCX that may not be there.
 */
function deliverableLabel(path: string): string {
  const lower = path.toLowerCase()
  if (lower.endsWith(".docx")) return "DOCX"
  if (lower.endsWith(".txt")) return "text version"
  if (lower.endsWith(".md")) return "Markdown version"
  return "file"
}

/** The number of facts the validator stripped, for the banner and glance. */
function removedCount(factuality: TailorResponse["factuality"]): number {
  return (
    factuality.removed_skills.length +
    factuality.removed_experience.length +
    factuality.removed_projects.length
  )
}

/**
 * The verdicts at a glance, on the Overview tab — each one says what it is
 * and links to the tab that carries the full report.
 */
function AtAGlance({ result }: { result: TailorResponse }) {
  const coverage = result.ats_report.keyword_coverage
  const measurable = coverageIsMeasurable(coverage)
  /*
    A percentage only renders when its own denominator exists — a 0% beside
    a group the listing never stated would read as a measured miss.
  */
  const requiredTotal =
    coverage.required_hit.length + coverage.required_missing.length
  const preferredTotal =
    coverage.preferred_hit.length + coverage.preferred_missing.length
  const coverageParts: string[] = []
  if (requiredTotal > 0) {
    coverageParts.push(
      `required ${coverage.required_hit.length}/${requiredTotal}`
    )
  }
  if (preferredTotal > 0) {
    coverageParts.push(
      `preferred ${coverage.preferred_hit.length}/${preferredTotal}`
    )
  }
  return (
    <Card>
      <CardHeader>
        <CardTitle>Where things stand</CardTitle>
      </CardHeader>
      <CardContent>
        <FieldList
          items={[
            {
              label: "Factuality",
              value: result.factuality.passed
                ? "Passed — every claim is supported by your résumé (Validation tab)"
                : `${removedCount(result.factuality)} unsupported item(s) were stripped — read the findings (Validation tab)`,
            },
            {
              label: "ATS score",
              value: `${result.ats_report.score.toFixed(1)} / 100 · a measurement, not a promise (Validation tab)`,
            },
            {
              label: "Keyword coverage",
              value:
                measurable && coverageParts.length > 0
                  ? `${coverageParts.join(" · ")} — measured against the listing's stated skills (Resume tab)`
                  : "Could not be measured — the listing declares no structured skills (Resume tab)",
            },
            {
              label: "Deliverable",
              value:
                result.render.mode === "in_place"
                  ? `Your own ${result.render.source_format} file, edited in place (details below)`
                  : "A freshly generated document — your original could not be edited (details below)",
            },
          ]}
        />
      </CardContent>
    </Card>
  )
}

/**
 * The Studio for one job.
 *
 * The tailoring run takes about a minute (grounded research, generation, the
 * factuality validator, the render), so the screen shows the elapsed time
 * and offers a Cancel — which abandons the *wait*, not the server's work,
 * and says so.
 */
export function TailorJobScreen() {
  const { jobId = "" } = useParams()
  const { profileId, profile } = useProfileWithFallback()
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

  /*
    Recovery truth (master prompt §9.4): the model's own error text names its
    repair. A "not configured" answer says retrying will not help, so the
    screen does not offer a retry that cannot work; a credential answer
    (409) points at the one place the caller can fix it themselves.
  */
  const runError = tailor.error
  const runErrorDetail = runError instanceof ApiError ? runError.detail : ""
  const retryHelps = !(
    runError instanceof ApiError && runErrorDetail.includes("not configured")
  )
  const needsCredentials =
    runError instanceof ApiError && runError.status === 409

  const jobData = job.data?.job
  const parsedProfile = profile.data?.profile

  return (
    <div className="space-y-8">
      <PageHeader
        title={jobData ? jobData.title : "Tailor the resume"}
        description={
          jobData
            ? `${jobData.company}. Your résumé is rewritten for this job using only what it already says, then checked against the original and scored the way an employer's screening system would.`
            : "The agent rewrites the resume from your profile facts and checks every claim against your document."
        }
        meta={
          jobData ? (
            <>
              <span>{jobData.location}</span>
              {jobData.remote_policy ? (
                <span>{jobData.remote_policy}</span>
              ) : null}
              {jobData.employment_type ? (
                <span>{jobData.employment_type}</span>
              ) : null}
              {jobData.salary ? <span>{jobData.salary}</span> : null}
            </>
          ) : undefined
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
          description="Grounded research, generation, the factuality validator and the render. This takes about a minute."
          onCancel={() => abortRef.current?.abort()}
        >
          <p className="text-xs text-muted-foreground">
            Cancelling stops the console waiting. The server keeps working, and
            the result is stored under its own id.
          </p>
        </ProgressState>
      ) : null}

      {tailor.isError ? (
        <div className="space-y-3">
          <ErrorNotice
            error={runError}
            onRetry={
              retryHelps
                ? () => tailor.mutate({ profile: profileId, job: jobId })
                : undefined
            }
          />
          {needsCredentials ? (
            <p className="text-sm">
              <LinkButton variant="outline" size="sm" to="/app/profile">
                Open Profile → Model credentials
              </LinkButton>
            </p>
          ) : null}
        </div>
      ) : null}

      {result ? (
        <>
          {/*
            The factuality verdict rides **above** the tabs, on every tab —
            a failed check must never hide behind a green ATS score three
            clicks deep. The full findings are on the Validation tab; this
            banner only announces them (worded so it cannot collide with the
            report's own finding list in the tests).
          */}
          {!result.factuality.passed ? (
            <Banner
              tone="warning"
              title="The factuality check changed the resume before delivery"
            >
              <p>
                {removedCount(result.factuality)} item(s) your résumé does not
                state were stripped — the delivered text is the reduced,
                truthful one. The findings are on the Validation tab.
              </p>
            </Banner>
          ) : null}

          <Tabs defaultValue="overview">
            <TabsList>
              <TabsTrigger value="overview">Overview</TabsTrigger>
              <TabsTrigger value="resume">Resume</TabsTrigger>
              <TabsTrigger value="cover-letter">Cover Letter</TabsTrigger>
              <TabsTrigger value="research">Research</TabsTrigger>
              <TabsTrigger value="validation">Validation</TabsTrigger>
            </TabsList>

            <TabsContent value="overview" keepMounted className="space-y-8">
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
                    {/* WS-31: the deliverable keeps the uploaded format, so the
                        link names what it really is rather than assuming DOCX. */}
                    Download the {deliverableLabel(result.docx_path)}
                  </a>
                </p>
              </Banner>

              <AtAGlance result={result} />
              <RenderPanel render={result.render} />
            </TabsContent>

            <TabsContent value="resume" keepMounted>
              {profile.isPending ? (
                <ProgressState title="Reading your original résumé" />
              ) : profile.isError || !parsedProfile ? (
                <div className="space-y-3">
                  <ErrorNotice error={profile.error} />
                  <p className="text-sm text-muted-foreground">
                    The comparison needs the parsed original. The reports are
                    unaffected — see the Validation tab.
                  </p>
                </div>
              ) : (
                <div className="grid min-w-0 gap-8 xl:grid-cols-[minmax(0,1.55fr)_minmax(0,1fr)]">
                  <div className="min-w-0">
                    <ResumeDiffView
                      profile={parsedProfile}
                      tailored={result.tailored}
                      render={result.render}
                    />
                  </div>
                  <aside className="min-w-0 space-y-5 xl:border-l xl:border-border/60 xl:pl-6">
                    <KeywordPanel
                      coverage={result.ats_report.keyword_coverage}
                      profile={parsedProfile}
                    />
                  </aside>
                </div>
              )}
            </TabsContent>

            <TabsContent value="cover-letter" keepMounted>
              <CoverLetterPanel
                letter={result.tailored.cover_letter}
                jobTitle={jobData ? jobData.title : "this role"}
                company={jobData ? jobData.company : "the employer"}
              />
            </TabsContent>

            <TabsContent value="research" keepMounted>
              <InsightsPanel insights={result.insights} />
            </TabsContent>

            <TabsContent value="validation" keepMounted className="space-y-8">
              {/*
                Factuality first: when the check failed, its findings are the
                first thing the Validation tab shows — before any green score.
              */}
              <FactualityReport factuality={result.factuality} />
              <AtsPanel ats={result.ats_report} />
              <StylePanel style={result.style} />
            </TabsContent>
          </Tabs>
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
    // The **ranked** view: the server returns the most recent match per job,
    // best overall score first, limited after deduplication (WS-21).
    queryKey: ["profile-matches", profileId, "ranked"],
    queryFn: ({ signal }) =>
      api.getProfileMatches(profileId as string, {
        ranked: true,
        limit: 25,
        signal,
      }),
    enabled: Boolean(profileId) && !missing,
  })

  const entries = history.data?.matches ?? []

  const jobs = useQueries({
    queries: entries.map((entry) => {
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
            The jobs this profile has been scored against, best match first —
            one row per job, each shown with its most recent score. A tailored
            résumé is produced for one profile and one job at a time.
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
            {entries.map((entry, index) => {
              const job = jobs[index]?.data
              const scores = asRecord(entry.scores)
              const rawOverall = scores.overall_score
              const overall = typeof rawOverall === "number" ? rawOverall : null
              const jobId = asString(entry.job_id)
              return (
                <li
                  key={jobId}
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
                  {overall !== null ? <OverallScore value={overall} /> : null}
                </li>
              )
            })}
          </ul>
        </CardContent>
      </Card>
    </div>
  )
}
