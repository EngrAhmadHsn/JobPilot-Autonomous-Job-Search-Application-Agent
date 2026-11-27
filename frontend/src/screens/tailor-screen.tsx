import {
  useMutation,
  useQueries,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query"
import { useRef, useState } from "react"
import { Link, useParams, useSearchParams } from "react-router-dom"

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
import { preparePath } from "@/lib/api/posting-application"
import { formatDateTime } from "@/lib/format"
import { useProfileWithFallback } from "@/hooks/use-profile-fallback"
import { asRecord, asString } from "@/lib/safe"
import type { TailorResponse, TailoredEditRequest } from "@/lib/api/types"

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
import { ResumeEditor } from "@/screens/studio/resume-editor"

/* Resume Studio (Figma 16:82). The draft ID in the URL, not the active
   résumé or the last mutation in memory, names the document on screen. The
   diff always uses that draft's own parsed source; Review is navigation,
   not an application action. */

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

/** The paper-pill look for the row's non-tab members (design `49:956`). */
const PILL_ANCHOR =
  "inline-flex h-[39px] shrink-0 items-center rounded-[8px] border border-border-surface bg-card px-3.5 py-2 text-[13px] font-semibold leading-[19px] text-primary transition-colors outline-none hover:bg-accent focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"

/** The design's status chip (node `49:964`): sage, r=6, 11/600. */
const STATUS_CHIP =
  "inline-flex items-center rounded-[6px] bg-forest-soft px-[9px] py-1 text-[11px] font-semibold leading-4 text-primary"

type StudioRecord = TailorResponse & { edited_at?: string | null }

export function TailorJobScreen() {
  const { jobId = "" } = useParams()
  const [searchParams, setSearchParams] = useSearchParams()
  const draftId = searchParams.get("draft")

  return (
    <TailorWorkspace
      key={JSON.stringify([jobId, draftId])}
      jobId={jobId}
      draftId={draftId}
      openDraft={(id) => {
        const next = new URLSearchParams(searchParams)
        next.set("draft", id)
        setSearchParams(next, { replace: draftId === null })
      }}
    />
  )
}

function TailorWorkspace({
  jobId,
  draftId,
  openDraft,
}: {
  jobId: string
  draftId: string | null
  openDraft: (id: string) => void
}) {
  const current = useProfileWithFallback()
  const queryClient = useQueryClient()
  const [editing, setEditing] = useState(false)
  const abortRef = useRef<AbortController | null>(null)

  const job = useQuery({
    queryKey: ["job", jobId],
    queryFn: ({ signal }) => api.getJob(jobId, signal),
    enabled: Boolean(jobId),
  })

  // POST and PUT can seed this view immediately. A direct link or reload
  // reads the persisted record, and never starts generation as a side effect.
  const draft = useQuery<StudioRecord>({
    queryKey: ["studio-draft", draftId],
    queryFn: ({ signal }) => api.getTailored(draftId!, signal),
    enabled: Boolean(draftId),
  })
  const result =
    draft.data?.job_id === jobId && draft.data?.tailoring_id === draftId
      ? draft.data
      : undefined
  const sourceId = result?.profile_id ?? current.profileId
  const sourceProfile = useQuery({
    queryKey: ["profile", result?.profile_id ?? null],
    queryFn: ({ signal }) => api.getResume(result!.profile_id, signal),
    enabled: Boolean(result),
  })
  const profile = result ? sourceProfile : current.profile

  const tailor = useMutation({
    mutationFn: ({ profile, job }: { profile: string; job: string }) => {
      const controller = new AbortController()
      abortRef.current = controller
      return api.tailor({ profile_id: profile, job_id: job }, controller.signal)
    },
    onSuccess: (record) => {
      queryClient.setQueryData(["studio-draft", record.tailoring_id], record)
      void queryClient.invalidateQueries({ queryKey: ["documents"] })
    },
  })

  const edit = useMutation({
    mutationFn: ({
      tailoringId,
      body,
    }: {
      tailoringId: string
      body: TailoredEditRequest
    }) => api.editTailored(tailoringId, body),
    onSuccess: (record) => {
      queryClient.setQueryData(["studio-draft", record.tailoring_id], record)
      void queryClient.invalidateQueries({ queryKey: ["documents"] })
      void queryClient.invalidateQueries({
        queryKey: ["tailored", record.tailoring_id],
      })
      setEditing(false)
    },
  })

  const draftUnavailable =
    draftId === "" ||
    (draft.isError &&
      draft.error instanceof ApiError &&
      draft.error.status === 404) ||
    (draft.isSuccess && !result)
  const edited = Boolean(result?.edited_at)
  const runError = tailor.error
  const runErrorDetail = runError instanceof ApiError ? runError.detail : ""
  const needsCredentials =
    runError instanceof ApiError && runError.status === 409
  const retryHelps =
    !needsCredentials &&
    !/not configured|retrying will not help|daily quota/i.test(runErrorDetail)
  const canRun =
    Boolean(sourceId && job.isSuccess && profile.isSuccess) &&
    (draftId === null || Boolean(result)) &&
    !tailor.isPending &&
    !editing &&
    retryHelps
  const startTailoring = () => {
    if (!sourceId || !canRun) return
    // The mutation-level callback caches the record; only this still-mounted
    // workspace may navigate to it. Leaving the route need not cancel the API.
    tailor.mutate(
      { profile: sourceId, job: jobId },
      {
        onSuccess: (record) => openDraft(record.tailoring_id),
      }
    )
  }

  /*
    A failed save keeps the edits on screen. Without a server response, we
    cannot know whether the save completed.
  */
  const editErrorDetail = edit.error
    ? edit.error instanceof ApiError && edit.error.detail
      ? edit.error.detail
      : "Studio did not receive a save confirmation. Your edits are still open; check the saved draft before retrying."
    : null

  const jobData = job.data?.job
  const parsedProfile = profile.data?.profile
  const deliverable = result ? deliverableLabel(result.docx_path) : "DOCX"
  const jobNotFound = job.error instanceof ApiError && job.error.status === 404
  const waitingForDocuments = current.missing && current.documents.isPending
  const waitingForDraft =
    draftId !== null && !draftUnavailable && draft.isPending
  const loadingPrerequisites =
    waitingForDocuments ||
    (Boolean(sourceId) && !job.isError && (job.isPending || profile.isPending))
  const preflight = draftId === null && !tailor.isPending && !tailor.isError
  const runButton = (
    <Button disabled={!canRun} onClick={startTailoring}>
      {tailor.isPending
        ? "Tailoring…"
        : result
          ? "Tailor again"
          : "Tailor this resume"}
    </Button>
  )

  const heading = (
    <PageHeader
      title="Your experience. Better told."
      description="Tailor for one role without changing the facts."
      className="-mt-2 lg:-mt-1.5 [&_h1]:text-wrap [&_h1+div]:leading-5"
      actions={
        draftId === null && jobData ? (
          <>
            <LinkButton variant="outline" to={preparePath(jobId)}>
              Use your original résumé
            </LinkButton>
            {profile.isSuccess ? runButton : null}
          </>
        ) : undefined
      }
    />
  )

  if (draftUnavailable) {
    return (
      <div className="space-y-6">
        {heading}
        <EmptyState
          title="Draft not available"
          description="This draft may have been removed or the link may be wrong. Open another version from Profile & documents."
          action={
            <LinkButton to="/app/profile">Open your documents</LinkButton>
          }
        />
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {heading}

      {waitingForDraft || (preflight && loadingPrerequisites) ? (
        <ProgressState
          title={
            waitingForDraft
              ? "Opening your saved draft"
              : "Getting Resume Studio ready"
          }
        />
      ) : null}

      {draftId !== null && draft.isError ? (
        <ErrorNotice error={draft.error} onRetry={() => void draft.refetch()} />
      ) : null}

      {preflight && jobNotFound ? (
        <EmptyState
          title="That job is not in your matched list"
          description="Pick one of your matched jobs and we will rewrite your résumé for it."
          action={
            <LinkButton to="/app/matches">Find jobs that suit you</LinkButton>
          }
        />
      ) : preflight && job.isError ? (
        <ErrorNotice error={job.error} onRetry={() => void job.refetch()} />
      ) : preflight && !sourceId && !waitingForDocuments ? (
        <EmptyState
          title="Tailoring needs a résumé first"
          description="A tailored résumé is built from your profile facts. Upload your résumé, then come back to this job."
          action={<LinkButton to="/app/resume">Add your résumé</LinkButton>}
        />
      ) : preflight && profile.isError ? (
        <ErrorNotice
          error={profile.error}
          onRetry={() => void profile.refetch()}
        />
      ) : null}

      {tailor.isPending ? (
        <ProgressState
          title="Tailoring the resume"
          description="The model drafts wording for this role, then Studio checks the claims and prepares your file."
          onCancel={() => abortRef.current?.abort()}
        >
          <p className="text-xs text-muted-foreground">
            Cancelling only stops the wait. If the draft finishes, it will
            appear in Profile &amp; documents.
          </p>
        </ProgressState>
      ) : null}

      {tailor.isError ? (
        <div className="space-y-3">
          <ErrorNotice
            error={runError}
            onRetry={canRun ? startTailoring : undefined}
          />
          {needsCredentials ? (
            <LinkButton
              variant="outline"
              size="sm"
              to="/app/account?tab=credentials"
            >
              Open Account → Model credentials
            </LinkButton>
          ) : null}
        </div>
      ) : null}

      {/*
        The pre-run state, which the design file does not draw: the job
        this run will tailor for, and what the run will do. The header's
        button starts it.
      */}
      {preflight && current.profile.isSuccess && job.isSuccess ? (
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
            scores the result. The original is preserved; nothing is sent to the
            employer from here.
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
                The validator corrected unsupported wording or removed
                unsupported items. Review its findings on the Validation tab
                before using this draft.
              </p>
            </Banner>
          ) : null}

          <Tabs defaultValue="diff" variant="pill" className="gap-5">
            <div className="flex flex-wrap items-center gap-2 min-[1024px]:gap-3">
              <TabsList
                aria-label="Resume Studio views"
                className="min-w-0 gap-2 min-[1024px]:gap-3 [&_[role=tab]]:rounded-[8px] [&_[role=tab]:not([aria-selected=true])]:h-[39px]"
              >
                <TabsTrigger value="diff">Inline diff</TabsTrigger>
                <TabsTrigger value="original">Original</TabsTrigger>
                <TabsTrigger value="cover-letter">Cover letter</TabsTrigger>
                <TabsTrigger value="preview">Preview {deliverable}</TabsTrigger>
                <TabsTrigger
                  value="validation"
                  className="border-transparent bg-transparent px-1.5"
                >
                  Validation
                </TabsTrigger>
                <TabsTrigger
                  value="research"
                  className="border-transparent bg-transparent px-1.5"
                >
                  Research
                </TabsTrigger>
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
                className={PILL_ANCHOR}
              >
                {/* WS-31: the deliverable keeps the uploaded format, so the
                    pill names what it really is rather than assuming DOCX. */}
                {deliverable === "DOCX"
                  ? "Download DOCX"
                  : `Download the ${deliverable}`}
              </a>
              {/*
                The status chip tells the truth about whose words these are:
                the run's proposal, or the candidate's saved edit (the
                record's `edited_at` — server state, so a reload keeps it).
              */}
              <span className={STATUS_CHIP}>
                {edited
                  ? "Diff review · edited by you"
                  : "Diff review · proposed"}
              </span>
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
                <div className="grid min-w-0 items-start gap-6 lg:grid-cols-[minmax(0,2.12fr)_minmax(0,1fr)]">
                  {editing ? (
                    <ResumeEditor
                      tailored={result.tailored}
                      render={result.render}
                      jobTitle={jobData ? jobData.title : "Tailored resume"}
                      company={jobData ? jobData.company : "the employer"}
                      saving={edit.isPending}
                      error={editErrorDetail}
                      onSave={(body) =>
                        edit.mutate({ tailoringId: result.tailoring_id, body })
                      }
                      onDiscard={() => {
                        edit.reset()
                        setEditing(false)
                      }}
                    />
                  ) : (
                    <ResumeDiffView
                      profile={parsedProfile}
                      tailored={result.tailored}
                      render={result.render}
                      jobTitle={jobData ? jobData.title : "Tailored resume"}
                      company={jobData ? jobData.company : "the employer"}
                      claimsVerified={result.factuality.passed}
                      onStartEdit={
                        tailor.isPending
                          ? undefined
                          : () => {
                              edit.reset()
                              setEditing(true)
                            }
                      }
                    />
                  )}
                  <EvidenceRail
                    coverage={result.ats_report.keyword_coverage}
                    profile={parsedProfile}
                    factuality={result.factuality}
                    render={result.render}
                    reviewPath={
                      result.factuality.passed
                        ? `${preparePath(jobId)}?draft=${encodeURIComponent(result.tailoring_id)}`
                        : preparePath(jobId)
                    }
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
                key={result.tailored.cover_letter}
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
          {job.isSuccess ? (
            <div className="flex flex-wrap justify-end gap-2">
              <LinkButton variant="outline" to={preparePath(jobId)}>
                Use your original résumé
              </LinkButton>
              {profile.isSuccess ? runButton : null}
            </div>
          ) : null}
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
