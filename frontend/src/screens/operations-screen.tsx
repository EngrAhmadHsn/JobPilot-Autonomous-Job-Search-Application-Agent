import { useMutation, useQuery } from "@tanstack/react-query"
import { useState } from "react"

import { Banner } from "@/components/common/banner"
import { ErrorNotice } from "@/components/common/error-notice"
import { EmptyState, ProgressState } from "@/components/common/progress-state"
import { PageHeader, Section } from "@/components/common/page-header"
import { RunProgress, isRunTerminal, runStatusCopy } from "@/components/observability/run-progress"
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

/**
 * The Operations screen.
 *
 * The refresh is **queued**, not run in this request. The API writes a
 * durable run and answers `202`; this screen reads that run's persistent
 * state. Two consequences the screen is careful about:
 *
 * - **A reload does not lose the run.** The detail panel follows the newest
 *   run that is still going, whether this browser started it or the last
 *   one did, or a schedule did. There is nothing to remember client-side.
 * - **The progress is the backend's.** Counts, the percentage and the status
 *   all come from the run row; the panel never invents a percentage and
 *   never shows a console-side stopwatch as if it were the server's work.
 *
 * A refresh enqueues a *second* run for the embedding (the child), so the
 * child's progress is shown too — that is where a corpus refresh actually
 * spends its time.
 */
export function OperationsScreen() {
  /** A run the operator pinned by hand (or queued just now). */
  const [pickedId, setPickedId] = useState<string | null>(null)

  const history = useQuery({
    queryKey: ["runs", "history"],
    queryFn: ({ signal }) => api.listRuns(signal),
    refetchInterval: 10_000,
  })

  /*
    Which run the panel shows, **derived** — nothing is remembered in the
    browser, which is what makes the panel survive a reload:

    1. the run the operator pinned (or just queued);
    2. otherwise the newest run that is still going;
    3. otherwise the most recent run at all, so a finished run stays visible
       with its result instead of the panel vanishing at the end.
  */
  const runs = history.data?.runs ?? []
  const trackedId =
    pickedId ?? runs.find((run) => !isRunTerminal(run.status))?.id ?? runs[0]?.id ?? null

  const refresh = useMutation({
    mutationFn: () => api.refreshJobs(),
    onSuccess: (accepted: RunAccepted) => {
      setPickedId(accepted.run_id)
      history.refetch()
    },
  })

  const tracked = useQuery({
    queryKey: ["run", trackedId],
    queryFn: ({ signal }) => api.getRun(trackedId as string, signal),
    enabled: Boolean(trackedId),
    refetchInterval: (query) => {
      const status = query.state.data?.run.status
      return status && isRunTerminal(status) ? false : 2_000
    },
  })

  const detail: RunDetail | undefined = tracked.data?.run

  /*
    A refresh run finishes quickly (it fetches and persists); the embedding
    it started is the long part. Its id is on the parent's metadata, so the
    screen can show both without a second endpoint.
  */
  const childId =
    (detail?.metadata?.refresh as { embedding_run_id?: string | null } | undefined)
      ?.embedding_run_id ?? null
  const child = useQuery({
    queryKey: ["run", childId],
    queryFn: ({ signal }) => api.getRun(childId as string, signal),
    enabled: Boolean(childId),
    refetchInterval: (query) => {
      const status = query.state.data?.run.status
      return status && isRunTerminal(status) ? false : 2_000
    },
  })

  return (
    <div className="space-y-6">
      <PageHeader
        title="Keep the corpus fresh"
        description="Start a refresh and leave the page — the work continues in the background. Every figure below comes from the server, so what you see is the real state of the run."
      />

      <Card>
        <CardHeader>
          <CardTitle>Queue a corpus refresh</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <p className="text-sm text-muted-foreground">
            Fetches the boards, drops duplicates, stores the new listings and
            indexes them for matching. Only new or changed listings are
            embedded, and a second click joins the run already going.
          </p>

          <Button disabled={refresh.isPending} onClick={() => refresh.mutate()}>
            {refresh.isPending ? "Queueing…" : "Queue the refresh"}
          </Button>

          {refresh.isError ? <ErrorNotice error={refresh.error} /> : null}

          {refresh.data ? (
            <Banner
              tone={refresh.data.existing ? "info" : "success"}
              title={
                refresh.data.existing
                  ? "A refresh was already in progress"
                  : "Refresh accepted"
              }
            >
              <p>
                Run <code>{refresh.data.run_id}</code> is accepted and{" "}
                <strong>{refresh.data.status}</strong>. It runs in the
                background — you can close this page.
              </p>
            </Banner>
          ) : null}
        </CardContent>
      </Card>

      {detail ? (
        <Card>
          <CardHeader>
            <CardTitle>Latest run</CardTitle>
          </CardHeader>
          <CardContent className="space-y-5">
            {tracked.isError ? (
              <ErrorNotice
                error={tracked.error}
                onRetry={() => tracked.refetch()}
              />
            ) : (
              <RunProgress run={detail} events={detail.events} />
            )}

            {childId ? (
              <div className="rounded-xl border border-border bg-muted/30 p-4">
                <p className="text-xs font-medium tracking-wide text-muted-foreground uppercase">
                  The embedding pass this refresh started
                </p>
                <div className="mt-3">
                  {child.data ? (
                    <RunProgress
                      run={child.data.run}
                      events={child.data.run.events}
                    />
                  ) : child.isError ? (
                    <ErrorNotice
                      error={child.error}
                      onRetry={() => child.refetch()}
                    />
                  ) : (
                    <ProgressState title="Reading the embedding run" />
                  )}
                </div>
              </div>
            ) : null}
          </CardContent>
        </Card>
      ) : null}

      <Section
        title="Recent runs"
        description="Everything this account has run, newest first. Reopen the page and the state is still here."
      >
        {history.isError ? (
          <ErrorNotice error={history.error} onRetry={() => history.refetch()} />
        ) : history.isPending ? (
          <ProgressState
            title="Reading the run history"
            description="Loading this account's executions from the backend."
          />
        ) : (history.data?.runs.length ?? 0) === 0 ? (
          <EmptyState
            title="No runs yet"
            description="Queue a refresh and it appears here, with its durable id and its state."
          />
        ) : (
          <RunsTable
            runs={history.data!.runs}
            trackedId={trackedId}
            onTrack={setPickedId}
          />
        )}
      </Section>
    </div>
  )
}

function RunsTable({
  runs,
  trackedId,
  onTrack,
}: {
  runs: RunSummary[]
  trackedId: string | null
  onTrack: (runId: string) => void
}) {
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Run</TableHead>
          <TableHead>Type</TableHead>
          <TableHead>Status</TableHead>
          <TableHead>Progress</TableHead>
          <TableHead>Created</TableHead>
          <TableHead className="text-right">Progress</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {runs.map((run) => (
          <TableRow key={run.id}>
            <TableCell className="font-mono text-xs">
              {run.id.slice(0, 12)}
            </TableCell>
            <TableCell>{run.job_type}</TableCell>
            <TableCell className={runStatusCopy(run.status).tone}>
              {runStatusCopy(run.status).label}
            </TableCell>
            <TableCell className="tabular-nums">
              {run.progress_percent}%
            </TableCell>
            <TableCell>{formatDateTime(run.created_at)}</TableCell>
            <TableCell className="text-right">
              <Button
                type="button"
                variant="outline"
                size="sm"
                aria-pressed={trackedId === run.id}
                onClick={() => onTrack(run.id)}
              >
                {trackedId === run.id ? "Showing" : "Show"}
              </Button>
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  )
}