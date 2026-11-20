import { useQuery } from "@tanstack/react-query"
import type { ReactNode } from "react"
import { useParams, useSearchParams } from "react-router-dom"

import { ErrorNotice } from "@/components/common/error-notice"
import { FieldList } from "@/components/common/field-list"
import { PlainText } from "@/components/common/plain-text"
import { ProgressState } from "@/components/common/progress-state"
import { Skeleton } from "@/components/ui/skeleton"
import { PageHeader } from "@/components/ui/page-header"
import { LinkButton } from "@/components/ui/link-button"
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { StatusExplainer } from "@/components/ui/status-badge"

import { apiUrl } from "@/lib/api/client"
import { api } from "@/lib/api/endpoints"
import { formatDateTime, formatTimeOfDay, pluralize } from "@/lib/format"
import { asString } from "@/lib/safe"
import { describeStatus, type StatusTone } from "@/lib/status"
import type { ApplicationDetail } from "@/lib/api/types"

import { ApplicationList } from "@/screens/tracker/application-list"
import { BoardView } from "@/screens/tracker/board-view"
import type { StageGroup } from "@/screens/tracker/stage-groups"
import { ApplicationTimeline } from "@/screens/tracker/application-timeline"
import { OutcomeEditor } from "@/screens/tracker/outcome-editor"
import { isLocalTestBoard } from "@/screens/review/in-control-notice"

/*
  The Tracker (WS-39, rebuilt to the design file's screens 05/18 in WS-42).

  Which view is showing lives in the URL (`?view=board`, `?status=<s>`), so
  the board and a filtered list survive a reload and are linkable — the same
  pattern the Discover screen uses for its selection. The default is the
  board: the design file's screen 05 opens on it, and the four stages side
  by side are the answer to "where does everything stand"; the list is the
  drill-in with the server's one real status filter.

  The board is the design's horizontal Kanban at **every** width — four full
  columns that share the row when it fits and swipe sideways under their
  headers when it does not (the design draws both, 16:162 and 49:10846).
  There is no squeezed grid and no separate mobile surface.

  Nothing here polls. The tracker reads when it is opened (and when the
  operator changes the filter or the view); the board is four one-shot
  group reads, the list is one read per page.
*/
export function TrackerScreen() {
  const [searchParams, setSearchParams] = useSearchParams()
  const requestedView = searchParams.get("view")
  const view: "board" | "list" = requestedView === "list" ? "list" : "board"
  const statusFilter = searchParams.get("status")

  function setView(next: string) {
    const params = new URLSearchParams(searchParams)
    if (next === "list") params.set("view", "list")
    else params.delete("view")
    setSearchParams(params, { replace: true })
  }

  function setStatusFilter(status: string | null) {
    const params = new URLSearchParams(searchParams)
    if (status) params.set("status", status)
    else params.delete("status")
    setSearchParams(params, { replace: true })
  }

  /**
   * A column's "show all" hand-off: the List view, filtered to that stage's
   * statuses.
   *
   * The filter is the **group**, so a click on "Show all 26 in the list" from
   * Awaiting review shows the same 26 the column counted — not the 21 one
   * status alone holds. `status` is comma-joined because that is the spelling
   * the API accepts for several values.
   */
  function showAllInList(group: StageGroup) {
    const params = new URLSearchParams(searchParams)
    params.set("view", "list")
    params.set("status", group.statuses.join(","))
    setSearchParams(params, { replace: true })
  }

  /*
    The Board/List pair (design 49:1134–49:1137) belongs to the **screen**,
    not to the board: the design draws it as the toolbar's first pills, and
    the view it switches must always be reachable *from* the other view — a
    List view with no way back to the board would be a dead end the design
    does not draw. The pills travel with the active view; the board renders
    them first in its toolbar row, the list renders them alone above the
    table (the Filters pill, the board's own total and "Find another role →"
    are the board toolbar's — the list has its filter chips and its own
    total in the body).
  */
  const viewTabs = (
    <Tabs variant="pill" value={view} onValueChange={(value) => setView(value)}>
      <TabsList aria-label="Applications view" className="gap-2.5">
        <TabsTrigger value="board">Board</TabsTrigger>
        <TabsTrigger value="list">List</TabsTrigger>
      </TabsList>
    </Tabs>
  )

  return (
    <div className="space-y-5">
      {/*
        The statement heading is the design's (47:184/47:185); the tab still
        carries the stable screen name the accessibility contract pins.
      */}
      <PageHeader
        title="Every application, in context."
        documentTitle="Applications"
        description="Know what is waiting, what needs you, and what happened next."
      />

      {view === "board" ? (
        <BoardView
          tabs={viewTabs}
          onShowAll={showAllInList}
          onOpenList={() => setView("list")}
        />
      ) : (
        <div className="space-y-5">
          <div className="flex flex-wrap items-center gap-2.5">{viewTabs}</div>
          <ApplicationList
            key={statusFilter ?? "all"}
            statusFilter={statusFilter}
            onStatusFilterChange={setStatusFilter}
          />
        </div>
      )}
    </div>
  )
}

/*
  The Tracker detail: one application, its whole chronology, its evidence,
  and the human outcome editor.

  The design file's screen 18 (node 47:640) leads with the statement "Every
  step, with evidence.", then an execution card whose body is **state fact
  rows** — Approval, Execution, Form interaction, Submission, Evidence —
  each a fact the server actually holds, and an "Ordered history" trail of
  time + actor + human-voiced rows. The ids and URLs the console holds for
  auditability stay on the page too, in a quieter "Record" card below —
  provenance is not decoration, but it is also not the headline.
*/
export function TrackerDetailScreen() {
  const { applicationId = "" } = useParams()

  const application = useQuery({
    queryKey: ["application", applicationId],
    queryFn: ({ signal }) => api.getApplication(applicationId, signal),
    enabled: Boolean(applicationId),
  })

  const evidence = useQuery({
    queryKey: ["application-evidence", applicationId],
    queryFn: ({ signal }) => api.listApplicationEvidence(applicationId, signal),
    enabled: Boolean(applicationId),
    retry: false,
  })

  /*
    The tailoring behind this application's tailored résumé, when the row
    carries one. The cover letter travels inside the tailoring record — the
    application row has no cover-letter field of its own, so without this
    read the console would have to claim there is none, which it cannot know.
  */
  const tailoringId = application.data?.tailored_resume_id ?? null
  const tailoring = useQuery({
    queryKey: ["tailored", tailoringId],
    queryFn: ({ signal }) => api.getTailored(tailoringId as string, signal),
    enabled: Boolean(tailoringId),
    retry: false,
  })

  if (application.isPending) {
    return <ProgressState title="Loading the application" />
  }

  if (application.isError) {
    return (
      <ErrorNotice
        error={application.error}
        onRetry={() => application.refetch()}
      />
    )
  }

  const record: ApplicationDetail = application.data
  const records = evidence.data?.evidence ?? []

  /*
    The state fact rows (design nodes 49:2120–49:2143). Every value below is
    derived from a field or an event the server sent — never from the
    status's name alone, and never invented to fill a row.
  */
  const approvalEvent =
    record.events.find((event) => event.event_type === "approval_granted") ??
    null
  const declinedEvent =
    record.events.find((event) => event.event_type === "approval_rejected") ??
    null

  /** "at 09:42" for today's decisions; a full stamp for older ones. */
  const decisionStamp = (iso: string) => {
    const parsed = new Date(iso)
    return parsed.toDateString() === new Date().toDateString()
      ? `at ${formatTimeOfDay(iso)}`
      : `on ${formatDateTime(iso)}`
  }

  const approvalValue = approvalEvent
    ? `Recorded by you ${decisionStamp(approvalEvent.recorded_at)}`
    : declinedEvent
      ? `Declined by you ${decisionStamp(declinedEvent.recorded_at)}`
      : "Waiting for your decision"

  const executed = Boolean(record.submitted_at)
  const executionValue = executed
    ? "Executed"
    : approvalEvent
      ? "Queued · waiting for a worker"
      : "Not started"

  const formInteractionValue =
    executed || record.verified_at ? "Form filled" : "Not started"

  const submissionValue = record.submitted_at
    ? `Submitted ${formatDateTime(record.submitted_at)}`
    : record.verified_at
      ? "Submitted · confirmed by evidence"
      : "Not submitted"

  const evidenceValue = records.length
    ? `${pluralize(records.length, "artifact")} captured`
    : "No artifacts available yet"

  const factRows: { label: string; value: string }[] = [
    { label: "Approval", value: approvalValue },
    { label: "Execution", value: executionValue },
    { label: "Form interaction", value: formInteractionValue },
    { label: "Submission", value: submissionValue },
    { label: "Evidence", value: evidenceValue },
  ]

  /*
    The intro line names the adapter honestly (the design's sentence,
    "Real-board assist · final submission stays with you.", is written for
    the real-board path — a fake-ATS run is the local playground and says
    so, in the same slot).
  */
  const introLine = isLocalTestBoard(record.adapter_name)
    ? "Fake ATS playground · the flow runs end to end against the local test board."
    : "Real-board assist · final submission stays with you."

  /*
    The record card's fields: the ids and paths this console holds for
    auditability. Only the timestamps the server holds render — a "—" in a
    chronology field reads as "happened, time unknown", and the truth is
    "never happened".
  */
  const fields: { label: string; value: ReactNode }[] = [
    { label: "Job URL", value: record.job_url },
    { label: "Adapter", value: record.adapter_name },
    { label: "Workflow id", value: record.workflow_id },
    { label: "Approval id", value: record.approval_id ?? "—" },
    { label: "Profile", value: record.profile_id ?? "—" },
    { label: "Created", value: formatDateTime(record.created_at) },
  ]
  if (record.submitted_at) {
    fields.push({
      label: "Submitted",
      value: formatDateTime(record.submitted_at),
    })
  }
  if (record.verified_at) {
    fields.push({
      label: "Verified",
      value: formatDateTime(record.verified_at),
    })
  }
  fields.push({
    label: "Application URL",
    value: record.application_url ?? "—",
  })
  fields.push({
    label: "Tailored résumé",
    value: tailoringId ? (
      // The tailored record's own authorized download endpoint — the same
      // route the Tailor screen uses. A server-side path is not a URL.
      <a
        href={apiUrl(
          `/api/tailored/${encodeURIComponent(tailoringId)}/download`
        )}
        className="font-medium underline underline-offset-4"
      >
        Download the tailored résumé (DOCX)
      </a>
    ) : (
      "—"
    ),
  })
  fields.push({
    label: "Cover letter",
    value: tailoringId ? (
      tailoring.isPending ? (
        "Reading the tailored record…"
      ) : tailoring.data?.tailored.cover_letter ? (
        <span
          title={tailoring.data.tailored.cover_letter}
          className="line-clamp-3 block"
        >
          <PlainText as="span">
            {tailoring.data.tailored.cover_letter}
          </PlainText>
        </span>
      ) : (
        "The tailored record holds no cover letter."
      )
    ) : (
      "No tailored résumé is associated with this application."
    ),
  })
  fields.push({ label: "Notes", value: record.notes ?? "—" })

  return (
    <div className="space-y-6">
      <PageHeader
        title="Every step, with evidence."
        documentTitle="Application details"
        description={`${record.company_name} · ${record.job_title} · ${describeStatus(record.status).label}`}
        meta={<span>Opened {formatDateTime(record.created_at)}</span>}
      />

      {/*
        The tools row (design 49:2112–49:2118): the way back, the status as
        the design's chip, and the audit trail. The chip's tint follows the
        status's tone; its text is the status's own label.
      */}
      <div className="flex flex-wrap items-center gap-2.5">
        <LinkButton variant="outline" to="/app/tracker">
          ← Applications
        </LinkButton>
        <span
          title={describeStatus(record.status).nextStep}
          className={`inline-block rounded-md px-[9px] py-1 text-[11px] leading-4 font-semibold text-primary ${STATUS_PILL_TONE[describeStatus(record.status).tone]}`}
        >
          {describeStatus(record.status).label}
        </span>
        <LinkButton variant="outline" to="/app/activity">
          Open activity →
        </LinkButton>
        {/*
          WS-45: an application that is still waiting for the human's
          decision is the one state where its questions can still be
          answered in the console — after a decision, the Review screen is
          not where the application lives. The link goes to the Review
          screen itself, which renders the real question state.
        */}
        {record.status === "awaiting_approval" ||
        record.status === "prepared" ? (
          <LinkButton variant="outline" to="/app/approvals">
            Review the questions →
          </LinkButton>
        ) : null}
      </div>

      <div className="grid gap-6 xl:grid-cols-[minmax(0,2fr)_minmax(0,1fr)] xl:items-start">
        <div className="min-w-0 space-y-6">
          <StatusExplainer status={record.status} />

          {/*
            The execution detail card (design 49:2120): the heading is the
            application itself, the intro names the adapter's world, and the
            body is the five state facts.
          */}
          <Card>
            <CardHeader>
              <CardTitle className="text-xl leading-[29px]">
                {record.company_name} · {record.job_title}
              </CardTitle>
              <p className="mt-1 text-sm leading-5 text-muted-foreground">
                {introLine}
              </p>
            </CardHeader>
            <CardContent>
              <dl>
                {factRows.map((row) => (
                  <div
                    key={row.label}
                    className="flex items-baseline justify-between gap-6 border-b border-border-surface py-2.5 last:border-b-0"
                  >
                    <dt className="shrink-0 text-xs leading-[17px] text-muted-foreground">
                      {row.label}
                    </dt>
                    <dd className="min-w-0 text-right text-sm leading-5 font-semibold text-primary">
                      {row.value}
                    </dd>
                  </div>
                ))}
              </dl>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Evidence</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              {evidence.isPending ? (
                /*
                  A read inside a card that already has its heading, so the bones
                  fill the card rather than replacing it with a progress panel.
                */
                <div className="space-y-2.5" aria-busy="true">
                  <Skeleton className="h-4 w-[min(24rem,78%)]" />
                  <Skeleton className="h-4 w-[min(18rem,52%)]" />
                  <Skeleton className="h-4 w-[min(14rem,40%)]" />
                </div>
              ) : null}

              {records.length === 0 && !evidence.isPending ? (
                <p className="text-sm text-muted-foreground">
                  This application has no evidence record. Nothing is claimed
                  about what happened on the employer&apos;s side.
                </p>
              ) : null}

              {records.map((entry, index) => {
                const screenshotPath = asString(entry.screenshot_path)
                const separator = Math.max(
                  screenshotPath.lastIndexOf("/"),
                  screenshotPath.lastIndexOf(String.fromCharCode(92))
                )
                const fileName =
                  separator >= 0
                    ? screenshotPath.slice(separator + 1)
                    : screenshotPath
                return (
                  <div key={index} className="space-y-2">
                    <FieldList
                      items={[
                        {
                          label: "Confirmation",
                          value: entry.confirmation_text ? (
                            <PlainText as="span">
                              {entry.confirmation_text}
                            </PlainText>
                          ) : (
                            "—"
                          ),
                        },
                        { label: "Evidence status", value: entry.status },
                        {
                          label: "Recorded",
                          value: formatDateTime(entry.recorded_at),
                        },
                        { label: "Screenshot", value: screenshotPath || "—" },
                        { label: "Trace", value: entry.trace_path ?? "—" },
                      ]}
                    />
                    {screenshotPath && fileName ? (
                      <figure className="space-y-1">
                        <img
                          src={apiUrl(
                            `/api/applications/${encodeURIComponent(record.id)}/evidence/${encodeURIComponent(fileName)}`
                          )}
                          alt="The screenshot captured as evidence of the submission"
                          className="max-w-full rounded-lg border border-border"
                        />
                        <figcaption className="text-xs text-muted-foreground">
                          The screenshot the browser captured at the moment of
                          the outcome.
                        </figcaption>
                      </figure>
                    ) : null}
                  </div>
                )
              })}
            </CardContent>
          </Card>

          {/*
            The design's "Ordered history" (49:2152): the chronology in the
            trail's human voice — a time, an actor chip, and rows that say
            what happened, with the server's own metadata kept below for the
            run ids and decision records it carries.
          */}
          <Card>
            <CardHeader>
              <CardTitle>Ordered history</CardTitle>
            </CardHeader>
            <CardContent>
              <ApplicationTimeline events={record.events} />
            </CardContent>
          </Card>

          <OutcomeEditor application={record} />

          {/*
            The record card: the ids, URLs and document links this console
            holds for auditability. The design's execution card keeps the
            headline, and the provenance stays one scroll away — removed
            entirely would orphan the workflow and approval ids the audit
            trail and the uncertain-outcome path refer to.
          */}
          <Card>
            <CardHeader>
              <CardTitle>Record</CardTitle>
            </CardHeader>
            <CardContent>
              <FieldList items={fields} />
            </CardContent>
          </Card>
        </div>

        {/*
          The design's proof rail (node `49:2144`, "Proof, not
          assumptions."): the evidence rule this screen exists to enforce. A
          queued application has neither screenshot nor confirmation, and an
          outcome that cannot be proven is escalated as uncertain — never
          assumed.
        */}
        <aside className="min-w-0 space-y-3 xl:sticky xl:top-[calc(var(--header-height,7rem)+1rem)]">
          {/*
            The rail is the design's panel (49:2144–49:2151): the state chip
            (the design tints it with the panel's own sage, so it reads as a
            quiet mark), the 22/600 statement, the two paragraphs, and the
            ghost action — no border, no fill, exactly as the design draws
            it.
          */}
          <section className="flex min-w-0 flex-col gap-3.5 rounded-surface bg-forest-soft p-5">
            <p>
              <span className="inline-block rounded-md bg-forest-soft px-[9px] py-1 text-[11px] leading-4 font-semibold tracking-wide text-primary">
                {records.length === 0
                  ? "EVIDENCE PENDING"
                  : `${pluralize(records.length, "ARTIFACT")}`}
              </span>
            </p>
            <h2 className="text-[22px] leading-8 font-semibold text-primary">
              Proof, not assumptions.
            </h2>
            <p className="text-sm leading-5 text-muted-foreground">
              Screenshots and confirmation artifacts appear after work actually
              happens. A queued application has neither.
            </p>
            <p className="text-[13px] leading-[19px] text-muted-foreground">
              If submission cannot be proven, the outcome is escalated as
              uncertain instead of assumed successful.
            </p>
            <div>
              <LinkButton to="/app/activity" variant="ghost" size="sm">
                View latest execution →
              </LinkButton>
            </div>
          </section>
        </aside>
      </div>
    </div>
  )
}

/*
  The status chip's tint, by tone (design 49:2116's lime chip is the
  progress tone; the rest map to the same two soft tints the console
  already uses — lime for the machine's states, terracotta for the human's
  attention, sage for quiet).
*/
const STATUS_PILL_TONE: Record<StatusTone, string> = {
  neutral: "bg-muted",
  info: "bg-forest-soft",
  progress: "bg-lime-soft",
  success: "bg-lime-soft",
  warning: "bg-terracotta-soft",
  danger: "bg-terracotta-soft",
}
