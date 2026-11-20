import { useMutation, useQueries, useQuery } from "@tanstack/react-query"
import { useRef, useState } from "react"
import { Link, useParams } from "react-router-dom"

import { Banner } from "@/components/common/banner"
import { ErrorNotice } from "@/components/common/error-notice"
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
import { EvidenceRail } from "@/screens/studio/evidence-rail"
import { OriginalDocument } from "@/screens/studio/original-document"
import {
  AtsPanel,
  FactualityReport,
  InsightsPanel,
  RenderPanel,
  StylePanel,
} from "@/screens/studio/report-panels"
import { ResumeDiffView } from "@/screens/studio/resume-diff"

/*
  The Resume Studio (WS-37), rebuilt to the design file's screen `16:82`
  (WS-42).

  The design's composition: the headline "Your experience. Better told.",
  a row of paper pills — Inline diff · Original · Cover letter · Preview
  DOCX · Download DOCX — beside a "Diff review · proposed" status chip,
  then the document on its sage desk mat with the "Make every claim count."
  evidence rail at its right.

  The console's real data adds what the design's example never had to
  carry, and the additions are named, not smuggled in:

  - **Validation** and **Research** pills — the factuality, ATS and style
    reports and the grounded insights are real deliverables of the tailoring
    run; hiding them behind no tab at all would bury the checks the safety
    story depends on. The design's example data passed factuality, so its
    five pills never needed them.
  - **No editor toolbar.** The design draws B / I / U / "Body · 11 pt" on an
    editable canvas. The comparison is read-only — there is no per-change
    revision model behind it (the WS-37 Task 1 audit found none) — and
    formatting controls that change nothing would be a lie about what this
    surface can do. The canvas carries the design's diff legend and a real
    view toggle instead.
  - The **status chip is the design's own copy** ("Diff review · proposed"):
    the tailored wording is the agent's proposal, and it stays a proposal
    until the candidate authorizes the application on Review.
  - "Preview DOCX" and "Download DOCX" name the **real** deliverable format
    (WS-31): a text deliverable says "text version", because promising a
    DOCX that is not there is the exact defect WS-31 fixed.

  Safety lines this screen keeps (master prompt §6.4/§9): the original
  document is immutable and never edited by this screen; a failed factuality
  report is content with visual weight above the tabs, never hidden behind a
  green ATS score; missing keywords stay honest gaps unless the profile
  supports them; and a model failure shows the API's own actionable error.
*/

/**
 * What the deliverable's file is, named for the candidate (WS-31).
 *
 * The tailoring keeps the uploaded format, so a résumé that arrived as plain
 * text comes back as plain text. The pills say which one it is rather than
 * promising a DOCX that may not be there.
 */
function deliverableLabel(path: string): string {
  const lower = path.toLowerCase()
  if (lower.endsWith(".docx")) return "DOCX"
  if (lower.endsWith(".txt")) return "text version"
  if (lower.endsWith(".md")) return "Markdown version"
  return "file"
}

/** The number of facts the validator stripped, for the banner. */
function removedCount(factuality: TailorResponse["factuality"]): number {
  return (
    factuality.removed_skills.length +
    factuality.removed_experience.length +
    factuality.removed_projects.length
  )
}

/** The paper-pill look for the row's non-tab members (design `49:956`). */
const PILL_ANCHOR =
  "inline-flex h-[37px] items-center rounded-lg border border-border-surface bg-card px-3.5 py-2 text-[13px] font-semibold leading-[19px] text-primary transition-colors outline-none hover:bg-accent focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"

/** The design's status chip (node `49:964`): sage, r=6, 11/600. */
const STATUS_CHIP =
  "inline-flex items-center rounded-[6px] bg-forest-soft px-2.5 py-1 text-[11px] font-semibold leading-4 text-primary"

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
          title="Your experience. Better told."
          description="Tailor for one role without changing the facts."
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
  const deliverable = result ? deliverableLabel(result.docx_path) : "DOCX"

  return (
    <div className="space-y-6">
      <PageHeader
        title="Your experience. Better told."
        description="Tailor for one role without changing the facts."
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

      {/*
        The pre-run state, which the design file does not draw: the job
        this run will tailor for, and what the run will do. The header's
        button starts it.
      */}
      {!result && !tailor.isPending && !tailor.isError ? (
        <section className="rounded-surface border border-border-surface bg-card p-6">
          <h2 className="font-heading text-xl font-semibold tracking-tight text-primary">
            {jobData ? jobData.title : "Tailor the resume"}
          </h2>
          {jobData ? (
            <p className="mt-1.5 text-xs text-muted-foreground">
              {[jobData.company, jobData.location, jobData.employment_type]
                .filter(Boolean)
                .join(" · ")}
            </p>
          ) : null}
          <p className="mt-3 max-w-prose text-sm leading-relaxed text-muted-foreground">
            The agent rewrites your résumé for this job using only what it
            already says, then checks every claim against the original and
            scores the result. The original is preserved; nothing is sent to
            the employer from here.
          </p>
        </section>
      ) : null}

      {result ? (
        <>
          {/*
            The factuality verdict rides **above** the pills, on every tab —
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

          <Tabs defaultValue="diff" variant="pill" className="gap-5">
            <div className="flex flex-wrap items-center gap-2.5">
              <TabsList>
                <TabsTrigger value="diff">Inline diff</TabsTrigger>
                <TabsTrigger value="original">Original</TabsTrigger>
                <TabsTrigger value="cover-letter">Cover letter</TabsTrigger>
                <TabsTrigger value="preview">Preview {deliverable}</TabsTrigger>
                <TabsTrigger value="validation">Validation</TabsTrigger>
                <TabsTrigger value="research">Research</TabsTrigger>
              </TabsList>
              {/*
                The design's last pill is an action, not a view (node
                `49:962`), so it is a real download link wearing the pill
                look — never a tab whose switching triggers a file save.
              */}
              <a
                href={apiUrl(
                  `/api/tailored/${encodeURIComponent(result.tailoring_id)}/download`
                )}
                download
                className={PILL_ANCHOR}
              >
                {/* WS-31: the deliverable keeps the uploaded format, so the
                    pill names what it really is rather than assuming DOCX. */}
                Download the {deliverable}
              </a>
              <span className={STATUS_CHIP}>Diff review · proposed</span>
            </div>

            <TabsContent value="diff" keepMounted>
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
                <div className="grid min-w-0 gap-6 xl:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
                  <ResumeDiffView
                    profile={parsedProfile}
                    tailored={result.tailored}
                    render={result.render}
                    jobTitle={jobData ? jobData.title : "Tailored resume"}
                    company={jobData ? jobData.company : "the employer"}
                    claimsVerified={result.factuality.passed}
                  />
                  <EvidenceRail
                    coverage={result.ats_report.keyword_coverage}
                    profile={parsedProfile}
                    factuality={result.factuality}
                    render={result.render}
                  />
                </div>
              )}
            </TabsContent>

            <TabsContent value="original" keepMounted>
              {profile.isPending ? (
                <ProgressState title="Reading your original résumé" />
              ) : profile.isError || !parsedProfile ? (
                <div className="space-y-3">
                  <ErrorNotice error={profile.error} />
                  <p className="text-sm text-muted-foreground">
                    Showing the original needs the parsed profile. The reports
                    are unaffected — see the Validation tab.
                  </p>
                </div>
              ) : (
                <OriginalDocument profile={parsedProfile} />
              )}
            </TabsContent>

            <TabsContent value="cover-letter" keepMounted>
              <CoverLetterPanel
                letter={result.tailored.cover_letter}
                jobTitle={jobData ? jobData.title : "this role"}
                company={jobData ? jobData.company : "the employer"}
              />
            </TabsContent>

            {/*
              The deliverable of record: how the file was produced, and where
              it lives. The design's "Preview DOCX" cannot render a DOCX in a
              browser, so this tab states the facts instead of faking a
              preview.
            */}
            <TabsContent value="preview" keepMounted className="space-y-6">
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
                  . Download it from the pill beside the tabs.
                </p>
              </Banner>
              <RenderPanel render={result.render} />
            </TabsContent>

            <TabsContent value="validation" keepMounted className="space-y-6">
              {/*
                Factuality first: when the check failed, its findings are the
                first thing the Validation tab shows — before any green score.
              */}
              <FactualityReport factuality={result.factuality} />
              <AtsPanel ats={result.ats_report} />
              <StylePanel style={result.style} />
            </TabsContent>

            <TabsContent value="research" keepMounted>
              <InsightsPanel insights={result.insights} />
            </TabsContent>
          </Tabs>
        </>
      ) : null}
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
      title="Your experience. Better told."
      description="Tailor for one role without changing the facts. Pick a job and the agent rewrites your résumé for it, using only what your résumé already says."
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
      <div className="rounded-surface border border-dashed border-border-surface bg-card/60 p-5">
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

      <Card className="rounded-surface">
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
