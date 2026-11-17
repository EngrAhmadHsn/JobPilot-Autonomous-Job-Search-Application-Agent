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
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { StatusBadge, StatusExplainer } from "@/components/ui/status-badge"
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs"

import { useMediaQuery } from "@/hooks/use-media-query"
import { apiUrl } from "@/lib/api/client"
import { api } from "@/lib/api/endpoints"
import { formatDateTime } from "@/lib/format"
import { asString } from "@/lib/safe"
import type { ApplicationDetail } from "@/lib/api/types"

import { ApplicationList } from "@/screens/tracker/application-list"
import { BoardView } from "@/screens/tracker/board-view"
import { ApplicationTimeline } from "@/screens/tracker/application-timeline"
import { OutcomeEditor } from "@/screens/tracker/outcome-editor"

/*
  The Tracker (WS-39) — the reference panel 5's Board and List views, plus
  the detail's Timeline.

  Which view is showing lives in the URL (`?view=board`, `?status=<s>`), so
  the board and a filtered list survive a reload and are linkable — the same
  pattern the Discover screen uses for its selection. The default is the
  list: the server-paginated table with the server's own total is the
  tracker's long-standing contract, and it is what a phone falls back to
  when the board is selected on a narrow screen.

  Nothing here polls. The tracker reads when it is opened (and when the
  operator changes the filter or the view); the board is five one-shot
  single-status reads, the list is one read per page.
*/
export function TrackerScreen() {
  const [searchParams, setSearchParams] = useSearchParams()
  const view: "board" | "list" =
    searchParams.get("view") === "board" ? "board" : "list"
  const statusFilter = searchParams.get("status")
  const isDesktop = useMediaQuery("(min-width: 768px)")

  function setView(next: string) {
    const params = new URLSearchParams(searchParams)
    if (next === "board") params.set("view", "board")
    else params.delete("view")
    setSearchParams(params, { replace: true })
  }

  function setStatusFilter(status: string | null) {
    const params = new URLSearchParams(searchParams)
    if (status) params.set("status", status)
    else params.delete("status")
    setSearchParams(params, { replace: true })
  }

  /** A column's "show all" hand-off: the List view, filtered to that stage. */
  function showAllInList(status: string) {
    const params = new URLSearchParams(searchParams)
    params.delete("view")
    params.set("status", status)
    setSearchParams(params, { replace: true })
  }

  const boardFits = isDesktop

  return (
    <div className="space-y-6">
      <PageHeader
        title="Tracker"
        description="Every application the agent prepared, its full ordered history, the evidence the browser captured, and the human outcomes you recorded."
      />

      <Tabs value={view} onValueChange={(value) => setView(String(value))}>
        <TabsList aria-label="Tracker view">
          <TabsTrigger value="board">Board</TabsTrigger>
          <TabsTrigger value="list">List</TabsTrigger>
        </TabsList>
      </Tabs>

      {view === "board" && boardFits ? (
        <BoardView onShowAll={showAllInList} />
      ) : (
        <>
          {/*
            The honest mobile fallback the brief names: the board is
            desktop-first, and a phone gets the list — not a sideways
            scroll of squeezed columns.
          */}
          {view === "board" && !boardFits ? (
            <p
              role="note"
              className="text-sm leading-relaxed text-muted-foreground"
            >
              The board needs more width than this screen has, so the list is
              showing instead — the same applications, server-paged.
            </p>
          ) : null}
          <ApplicationList
            key={statusFilter ?? "all"}
            statusFilter={statusFilter}
            onStatusFilterChange={setStatusFilter}
          />
        </>
      )}
    </div>
  )
}

/*
  The Tracker detail: one application, its whole chronology, its evidence,
  and the human outcome editor.

  The detail is the record the list points at: identity and plain-language
  status first, the timestamps the server actually holds (submitted and
  verified render only when they exist — a dash would imply a fact the
  server never recorded), the associated tailored résumé and its cover
  letter through the safe authorized download endpoint, the browser's
  evidence, the ordered timeline with each event's actor, and the outcome
  form that only ever offers the four human outcomes.
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

  const fields: { label: string; value: ReactNode }[] = [
    { label: "Job URL", value: record.job_url },
    { label: "Adapter", value: record.adapter_name },
    { label: "Workflow id", value: record.workflow_id },
    { label: "Approval id", value: record.approval_id ?? "—" },
    { label: "Profile", value: record.profile_id ?? "—" },
    { label: "Created", value: formatDateTime(record.created_at) },
  ]
  // Only the timestamps the server holds. A "—" in a chronology field
  // reads as "happened, time unknown" — the truth is "never happened".
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
    <div className="space-y-10">
      <PageHeader
        title={record.job_title}
        description={
          <span className="flex flex-wrap items-center gap-2">
            <span>{record.company_name}</span>
            <StatusBadge status={record.status} />
          </span>
        }
        meta={<span>Opened {formatDateTime(record.created_at)}</span>}
        actions={
          <LinkButton variant="outline" to="/app/tracker">
            Back to the list
          </LinkButton>
        }
      />

      <StatusExplainer status={record.status} />

      <Card>
        <CardHeader>
          <CardTitle>The application</CardTitle>
        </CardHeader>
        <CardContent>
          <FieldList items={fields} />
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
              This application has no evidence record. Nothing is claimed about
              what happened on the employer&apos;s side.
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
                      The screenshot the browser captured at the moment of the
                      outcome.
                    </figcaption>
                  </figure>
                ) : null}
              </div>
            )
          })}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Timeline ({record.events.length})</CardTitle>
        </CardHeader>
        <CardContent>
          <ApplicationTimeline events={record.events} />
        </CardContent>
      </Card>

      <OutcomeEditor application={record} />
    </div>
  )
}
