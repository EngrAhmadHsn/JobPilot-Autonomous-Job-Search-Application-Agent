import { useMutation, useQuery } from "@tanstack/react-query"
import { useState } from "react"

import { Banner } from "@/components/common/banner"
import { ErrorNotice } from "@/components/common/error-notice"
import { FieldList, SectionTitle } from "@/components/common/field-list"
import { EmptyState, ProgressState } from "@/components/common/progress-state"
import { PageHeader, Section } from "@/components/common/page-header"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"

import { api } from "@/lib/api/endpoints"
import type { RunAccepted, RunDetail, RunSummary } from "@/lib/api/types"
import { formatDateTime } from "@/lib/format"

/** Statuses from which nothing else will happen without a human. */
const TERMINAL = new Set(["COMPLETED", "PARTIAL", "FAILED", "CANCELLED"])
const NEEDS_A_HUMAN = new Set(["PAUSED", "RECOVERABLE", "RETRY_WAIT"])

interface RefreshReport {
  found?: number
  deduped?: number
  persisted?: number
  screened_out?: number
  admission_capped?: number
  source_errors?: Record<string, string>
  embedding_run_id?: string | null
  degraded?: boolean
}

/**
 * The Operations screen.
 *
 * The refresh is **queued**, not run in this request. The API writes a
 * durable run and answers `202`; the screen polls that run's persistent
 * state. Closing the browser, reloading the page or losing the connection
 * does not stop the work, and the same run is still there when the operator
 * comes back.
 *
 * Progress is the backend's own counters. The console never invents a
 * percentage or a completion state.
 */
export function OperationsScreen() {
  const [accepted, setAccepted] = useState<RunAccepted | null>(null)

  const refresh = useMutation({
    mutationFn: () => api.refreshJobs(),
    onSuccess: (run) => setAccepted(run),
  })

  const run = useQuery({
    queryKey: ["run", accepted?.run_id],
    queryFn: ({ signal }) => api.getRun(accepted!.run_id, signal),
    enabled: Boolean(accepted?.run_id),
    refetchInterval: (query) => {
      const status = query.state.data?.run.status
      return status && TERMINAL.has(status) ? false : 2_000
    },
  })

  const history = useQuery({
    queryKey: ["runs", "history"],
    queryFn: ({ signal }) => api.listRuns(signal),
    refetchInterval: 10_000,
  })

  const detail: RunDetail | undefined = run.data?.run

  return (
    <div className="space-y-6">
      <PageHeader
        title="Keep the corpus fresh"
        description="A refresh is accepted as durable background work. A separate worker fetches the boards, normalizes, deduplicates, persists and embeds — so the work survives this page, the browser and the API process."
      />

      <Card>
        <CardHeader>
          <CardTitle>Queue a corpus refresh</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <p className="text-sm text-muted-foreground">
            One run: fetch the boards → normalize → deduplicate → persist →
            embed. Only new or changed listings cost an embedding. A refresh
            already queued or running is joined, not duplicated.
          </p>

          <Button disabled={refresh.isPending} onClick={() => refresh.mutate()}>
            {refresh.isPending ? "Queueing..." : "Queue the refresh"}
          </Button>

          {refresh.isError ? <ErrorNotice error={refresh.error} /> : null}

          {accepted ? (
            <Banner
              tone={accepted.existing ? "info" : "success"}
              title={
                accepted.existing
                  ? "A refresh was already in progress"
                  : "Refresh accepted"
              }
            >
              <p>
                Durable run <code>{accepted.run_id}</code> is{" "}
                <strong>{accepted.status}</strong>. The worker executes it
                independently of this page.
              </p>
            </Banner>
          ) : null}
        </CardContent>
      </Card>

      {detail ? (
        <Card>
          <CardHeader>
            <CardTitle>The run</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <RunStatusNotice run={detail} />

            <div
              role="progressbar"
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={Math.round(detail.progress_percent)}
              aria-label="Refresh progress"
              className="h-2 w-full overflow-hidden rounded-full bg-muted"
            >
              <span
                className="block h-full rounded-full bg-primary transition-[width] duration-500"
                style={{ width: `${detail.progress_percent}%` }}
              />
            </div>

            <FieldList
              items={[
                { label: "Status", value: detail.status },
                { label: "Progress", value: `${detail.progress_percent}%` },
                {
                  label: "Items",
                  value: `${detail.completed_items} of ${detail.total_items}`,
                },
                { label: "Failed", value: detail.failed_items },
                { label: "Skipped", value: detail.skipped_items },
                {
                  label: "Last heartbeat",
                  value: detail.heartbeat_at
                    ? formatDateTime(detail.heartbeat_at)
                    : "—",
                },
                { label: "Attempts", value: detail.attempt_count },
              ]}
            />

            {detail.last_error ? (
              <Banner tone="warning" title="The run stopped with an error">
                <p>{detail.last_error}</p>
              </Banner>
            ) : null}

            <RefreshReportView detail={detail} />

            {!TERMINAL.has(detail.status) ? (
              <ProgressState
                title="Working"
                description="The worker is executing this run. The page may be closed; the run continues."
              />
            ) : null}
          </CardContent>
        </Card>
      ) : null}

      <Section
        title="Recent runs"
        description="The account's own durable execution history, newest first."
      >
        {history.isError ? (
          <ErrorNotice error={history.error} onRetry={() => history.refetch()} />
        ) : history.isPending ? (
          <ProgressState
            title="Reading the run history"
            description="Loading the account's executions from the backend."
          />
        ) : (history.data?.runs.length ?? 0) === 0 ? (
          <EmptyState
            title="No runs yet"
            description="Queue a refresh and it appears here, with its durable id and its state."
          />
        ) : (
          <RunsTable runs={history.data!.runs.slice(0, 10)} />
        )}
      </Section>
    </div>
  )
}

function RunStatusNotice({ run }: { run: RunDetail }) {
  if (run.status === "PAUSED") {
    return (
      <Banner tone="warning" title="The run is paused">
        <p>
          The daily embedding budget is spent. The work stays queued; an
          administrator can resume it after the reset (and the same quota
          still applies).
        </p>
      </Banner>
    )
  }
  if (run.status === "RECOVERABLE" || run.status === "RETRY_WAIT") {
    return (
      <Banner tone="warning" title="The run needs an administrator">
        <p>
          The worker stopped while this run still had outstanding work.
          Nothing is lost — the completed work is kept — and an administrator
          resumes only what remains.
        </p>
      </Banner>
    )
  }
  if (run.status === "FAILED" || run.status === "PARTIAL") {
    return (
      <Banner tone="warning" title="The run did not finish cleanly">
        <p>
          Some work failed permanently. The completed work is kept and the
          failure is listed below; an administrator can inspect and retry the
          failed items.
        </p>
      </Banner>
    )
  }
  return null
}

function RefreshReportView({ detail }: { detail: RunDetail }) {
  const report = detail.metadata?.refresh as RefreshReport | undefined
  if (!report) {
    return null
  }
  const errors = report.source_errors ?? {}
  return (
    <div className="space-y-3">
      <SectionTitle>The refresh report</SectionTitle>
      <FieldList
        items={[
          { label: "Found", value: report.found ?? 0 },
          { label: "Deduped", value: report.deduped ?? 0 },
          { label: "Persisted", value: report.persisted ?? 0 },
          { label: "Screened out", value: report.screened_out ?? 0 },
          { label: "Admission capped", value: report.admission_capped ?? 0 },
          {
            label: "Embedding run",
            value: report.embedding_run_id ?? "not needed",
          },
        ]}
      />
      {Object.keys(errors).length > 0 ? (
        <div className="space-y-1">
          <SectionTitle>Sources that failed</SectionTitle>
          <ul className="list-disc space-y-1 pl-5 text-sm">
            {Object.entries(errors).map(([source, message]) => (
              <li key={source}>
                <span className="font-medium">{source}</span>: {message}
              </li>
            ))}
          </ul>
        </div>
      ) : (
        <p className="text-sm text-muted-foreground">Every source answered.</p>
      )}
    </div>
  )
}

function RunsTable({ runs }: { runs: RunSummary[] }) {
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Run</TableHead>
          <TableHead>Type</TableHead>
          <TableHead>Status</TableHead>
          <TableHead>Progress</TableHead>
          <TableHead>Created</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {runs.map((run) => (
          <TableRow key={run.id}>
            <TableCell className="font-mono text-xs">
              {run.id.slice(0, 12)}
            </TableCell>
            <TableCell>{run.job_type}</TableCell>
            <TableCell>
              <span
                className={
                  run.status === "COMPLETED"
                    ? "text-foreground"
                    : NEEDS_A_HUMAN.has(run.status) || run.status === "FAILED"
                      ? "text-terracotta"
                      : "text-muted-foreground"
                }
              >
                {run.status}
              </span>
            </TableCell>
            <TableCell className="tabular-nums">
              {run.progress_percent}%
            </TableCell>
            <TableCell>{formatDateTime(run.created_at)}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  )
}