import { useMutation, useQuery } from "@tanstack/react-query"
import { useState } from "react"
import { Link, useParams } from "react-router-dom"

import { Banner } from "@/components/common/banner"
import { ErrorNotice } from "@/components/common/error-notice"
import { FieldList } from "@/components/common/field-list"
import { PlainText } from "@/components/common/plain-text"
import { EmptyState, ProgressState } from "@/components/common/progress-state"
import { StatusBadge, StatusExplainer } from "@/components/common/status-badge"
import { PageHeader } from "@/components/common/page-header"
import { Button } from "@/components/ui/button"
import { LinkButton } from "@/components/ui/link-button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"

import { apiUrl } from "@/lib/api/client"
import { api } from "@/lib/api/endpoints"
import { formatDateTime, pluralize } from "@/lib/format"
import { asString } from "@/lib/safe"
import {
  APPLICATION_STATUS_NAMES,
  HUMAN_OUTCOME_STATUS_NAMES,
  describeStatus,
} from "@/lib/status"
import type { ApplicationDetail, ApplicationEvent } from "@/lib/api/types"

const PAGE_SIZE = 20

/** One event in the application's history. */
function EventRow({ event }: { event: ApplicationEvent }) {
  const metadata = event.metadata ?? {}
  const entries = Object.entries(metadata).filter(
    ([, value]) => value !== null && value !== undefined
  )

  return (
    <li className="border-l-2 border-border pl-4">
      <div className="flex flex-wrap items-baseline gap-2">
        <span className="text-sm font-medium">{event.event_type}</span>
        {event.from_status || event.to_status ? (
          <span className="text-xs text-muted-foreground">
            {event.from_status ?? "—"} → {event.to_status ?? "—"}
          </span>
        ) : null}
        <StatusBadge status={event.to_status} />
      </div>
      <p className="text-xs text-muted-foreground">
        by {event.actor} · {formatDateTime(event.recorded_at)}
      </p>
      {entries.length > 0 ? (
        <dl className="mt-1 text-xs text-muted-foreground">
          {entries.map(([key, value]) => (
            <div key={key} className="flex gap-2">
              <dt>{key}:</dt>
              <dd className="break-words">
                <PlainText as="span">
                  {typeof value === "string" ? value : JSON.stringify(value)}
                </PlainText>
              </dd>
            </div>
          ))}
        </dl>
      ) : null}
    </li>
  )
}

/**
 * The Tracker list.
 *
 * The list is the backend's, filtered and paged by the backend's own
 * parameters — the console does not filter a page of results on its own,
 * because a page that says "3 of 400" has to be the server's count.
 */
export function TrackerScreen() {
  const [statuses, setStatuses] = useState<string[]>([])
  const [offset, setOffset] = useState(0)

  const applications = useQuery({
    queryKey: ["applications", statuses, offset],
    queryFn: ({ signal }) =>
      api.listApplications(
        { status: statuses, limit: PAGE_SIZE, offset },
        signal
      ),
  })

  const toggleStatus = (status: string) => {
    setOffset(0)
    setStatuses((current) =>
      current.includes(status)
        ? current.filter((item) => item !== status)
        : [...current, status]
    )
  }

  const total = applications.data?.total ?? 0
  const items = applications.data?.items ?? []

  return (
    <div className="space-y-6">
      <PageHeader
        title="Track every application"
        description="Every application the agent prepared, its full ordered history, the evidence the browser captured, and the human outcomes you recorded."
      />

      <Card>
        <CardHeader>
          <CardTitle>Tracked applications</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex flex-wrap gap-2">
            {APPLICATION_STATUS_NAMES.map((status) => {
              const presentation = describeStatus(status)
              const active = statuses.includes(status)
              return (
                <button
                  key={status}
                  type="button"
                  aria-pressed={active}
                  onClick={() => toggleStatus(status)}
                  title={presentation.nextStep}
                  className={
                    active
                      ? "rounded-full border border-primary bg-primary px-3 py-1 text-xs font-medium text-primary-foreground"
                      : "rounded-full border border-border px-3 py-1 text-xs font-medium text-muted-foreground hover:bg-muted"
                  }
                >
                  {presentation.label}
                </button>
              )
            })}
          </div>

          {applications.isPending ? (
            <ProgressState
              key="applications"
              title="Loading the applications"
            />
          ) : null}

          {applications.isError ? (
            <ErrorNotice
              error={applications.error}
              onRetry={() => applications.refetch()}
            />
          ) : null}

          {applications.data ? (
            <>
              <p className="text-sm text-muted-foreground">
                {pluralize(total, "application")} · showing {items.length} from{" "}
                {offset + 1}
              </p>

              {items.length === 0 ? (
                <EmptyState
                  title="Nothing tracked yet"
                  description="An application appears here once it has been prepared through the Approvals screen."
                />
              ) : (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Job</TableHead>
                      <TableHead>Company</TableHead>
                      <TableHead>Status</TableHead>
                      <TableHead>Created</TableHead>
                      <TableHead>Submitted</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {items.map((application) => (
                      <TableRow key={application.id}>
                        <TableCell>
                          <Link
                            to={`/tracker/${encodeURIComponent(application.id)}`}
                            className="font-medium underline-offset-4 hover:underline"
                          >
                            {application.job_title}
                          </Link>
                        </TableCell>
                        <TableCell>{application.company_name}</TableCell>
                        <TableCell>
                          <StatusBadge status={application.status} />
                        </TableCell>
                        <TableCell>
                          {formatDateTime(application.created_at)}
                        </TableCell>
                        <TableCell>
                          {formatDateTime(application.submitted_at)}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              )}

              <div className="flex items-center justify-between gap-2">
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  disabled={offset === 0}
                  onClick={() =>
                    setOffset((value) => Math.max(0, value - PAGE_SIZE))
                  }
                >
                  Previous
                </Button>
                <span className="text-xs text-muted-foreground">
                  {total === 0
                    ? "nothing"
                    : `${offset + 1}–${Math.min(offset + PAGE_SIZE, total)}`}{" "}
                  of {total}
                </span>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  disabled={offset + PAGE_SIZE >= total}
                  onClick={() => setOffset((value) => value + PAGE_SIZE)}
                >
                  Next
                </Button>
              </div>
            </>
          ) : null}
        </CardContent>
      </Card>
    </div>
  )
}

/**
 * The Tracker detail: one application, its whole history, its evidence, and
 * the human outcome form.
 *
 * The outcome form sends `human:<name>` and only ever the four statuses a
 * human may set. The agent may not record an offer it was not told about,
 * and the console does not offer a way to pretend otherwise.
 */
export function TrackerDetailScreen() {
  const { applicationId = "" } = useParams()
  // There is no "your name" field (WS-14): the actor is the
  // authenticated principal, so a name typed here would be a value the
  // server ignores. The outcome is recorded against the account the
  // operator is signed in as.
  const [outcome, setOutcome] = useState<string>(HUMAN_OUTCOME_STATUS_NAMES[0])
  const [notes, setNotes] = useState("")

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

  const update = useMutation({
    mutationFn: (values: { status: string; notes?: string }) =>
      api.updateApplicationStatus(applicationId, values),
    onSuccess: () => {
      application.refetch()
    },
  })

  if (application.isPending) {
    return <ProgressState key="application" title="Loading the application" />
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
        actions={
          <LinkButton variant="outline" to="/tracker">
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
          <FieldList
            items={[
              { label: "Job URL", value: record.job_url },
              { label: "Adapter", value: record.adapter_name },
              { label: "Workflow id", value: record.workflow_id },
              { label: "Approval id", value: record.approval_id ?? "—" },
              { label: "Profile", value: record.profile_id ?? "—" },
              {
                label: "Tailored resume",
                value: record.tailored_resume_id ?? "—",
              },
              { label: "Created", value: formatDateTime(record.created_at) },
              {
                label: "Submitted",
                value: formatDateTime(record.submitted_at),
              },
              { label: "Verified", value: formatDateTime(record.verified_at) },
              {
                label: "Application URL",
                value: record.application_url ?? "—",
              },
              { label: "Notes", value: record.notes ?? "—" },
            ]}
          />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Evidence</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          {evidence.isPending ? (
            <ProgressState key="evidence" title="Loading the evidence" />
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
          <CardTitle>History ({record.events.length})</CardTitle>
        </CardHeader>
        <CardContent>
          <ol className="space-y-4">
            {record.events.map((event) => (
              <EventRow key={event.id} event={event} />
            ))}
          </ol>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Record a human outcome</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <Banner tone="neutral" title="A human outcome is recorded by a human">
            <p>
              The agent prepares, submits and verifies. It never decides that an
              employer made an offer. The outcome is recorded against your
              account, so it is attributable to a person and to nobody else.
            </p>
          </Banner>

          <form
            className="grid gap-3 sm:grid-cols-[1fr_2fr_auto] sm:items-end"
            onSubmit={(event) => {
              event.preventDefault()
              update.mutate({
                status: outcome,
                notes: notes.trim() ? notes.trim() : undefined,
              })
            }}
          >
            <label className="space-y-1">
              <span className="text-sm font-medium">Outcome</span>
              <select
                className="h-8 w-full rounded-lg border border-input bg-transparent px-2 text-sm"
                value={outcome}
                onChange={(event) => setOutcome(event.target.value)}
              >
                {HUMAN_OUTCOME_STATUS_NAMES.map((status) => (
                  <option key={status} value={status}>
                    {describeStatus(status).label}
                  </option>
                ))}
              </select>
            </label>
            <label className="space-y-1">
              <span className="text-sm font-medium">Note (optional)</span>
              <Input
                value={notes}
                onChange={(event) => setNotes(event.target.value)}
              />
            </label>
            <Button type="submit" disabled={update.isPending}>
              {update.isPending ? "Recording…" : "Record the outcome"}
            </Button>
          </form>

          {update.isError ? <ErrorNotice error={update.error} /> : null}

          {update.isSuccess ? (
            <Banner tone="success" title="The outcome was recorded">
              <p>
                The application is now{" "}
                <span className="font-medium">
                  {describeStatus(update.data.status).label}
                </span>
                . The history above is the server&apos;s.
              </p>
            </Banner>
          ) : null}
        </CardContent>
      </Card>
    </div>
  )
}
