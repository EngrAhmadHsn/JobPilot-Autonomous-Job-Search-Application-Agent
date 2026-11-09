import { useMutation, useQuery } from "@tanstack/react-query"
import type { UseQueryResult } from "@tanstack/react-query"
import { Fragment, useState } from "react"

import { Banner } from "@/components/common/banner"
import { EmptyState, ProgressState } from "@/components/common/progress-state"
import {
  RunProgress,
  isRunTerminal,
  runStatusCopy,
} from "@/components/observability/run-progress"
import { ErrorNotice } from "@/components/common/error-notice"
import { PageHeader, Section } from "@/components/common/page-header"
import { Pagination } from "@/components/common/pagination"
import { RelativeTime } from "@/components/common/relative-time"
import { StatTile } from "@/components/common/stat-tile"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"

import { ApiError } from "@/lib/api/client"
import { api } from "@/lib/api/endpoints"
import type {
  AdminOverview,
  RunDetailResponse,
  RunSummary,
  WorkerHealthEntry,
  WorkerHealthResponse,
} from "@/lib/api/types"
import { formatDateTime } from "@/lib/format"
import {
  adminRunsPollInterval,
  runPollInterval,
  WORKER_HEALTH_POLL_MS,
} from "@/lib/polling"
import { describeStatus } from "@/lib/status"
import {
  describeWorkerStatus,
  workerStatusToneClass,
} from "@/lib/worker-status"

/**
 * The administration screen.
 *
 * Platform-level oversight: how many accounts exist, how applications are
 * distributed, how the audit trail splits, and how large the shared corpus
 * is. It is **not** an expanded operator dashboard and it is **not** a
 * tenant view — every figure is a platform total.
 *
 * The screen holds no authority of its own. The route behind it is guarded
 * on the **server** by the caller's own `is_superuser` flag, so a
 * non-superuser is refused (403) no matter what this file renders. The
 * client only decides whether it is worth *asking*; the server decides
 * whether to answer. Aggregates only: no e-mail, no résumé, no application
 * body crosses this endpoint.
 */
export function AdminScreen() {
  const identity = useQuery({
    queryKey: ["identity"],
    queryFn: ({ signal }) => api.identity(signal),
    retry: false,
  })

  const isSuperuser = Boolean(identity.data?.is_superuser)

  const overview = useQuery({
    queryKey: ["admin", "overview"],
    queryFn: ({ signal }) => api.adminOverview(signal),
    enabled: isSuperuser,
    refetchInterval: 30_000,
  })

  return (
    <div className="space-y-8">
      <PageHeader
        title="Administration"
        description="Platform-wide totals across every account. This is the one surface that deliberately reads across owners, and the server authorizes it with the caller's own administrator flag."
      />

      {identity.isPending ? (
        <ProgressState
          title="Checking your account"
          description="Reading the authenticated principal before asking for platform data."
          onCancel={undefined}
        />
      ) : !isSuperuser ? (
        <Banner tone="warning" title="This account is not an administrator">
          <p>
            The administration view is a platform-wide, cross-account read, so
            it is reserved for administrator accounts. The server refuses every
            request for these figures from an ordinary account — this message
            reflects that decision, it does not make it.
          </p>
        </Banner>
      ) : overview.isError ? (
        overview.error instanceof ApiError && overview.error.status === 403 ? (
          <Banner tone="warning" title="The server refused this view (403)">
            <p>{overview.error.detail}</p>
          </Banner>
        ) : (
          <ErrorNotice
            error={overview.error}
            onRetry={() => overview.refetch()}
            verbose
          />
        )
      ) : overview.isPending || !overview.data ? (
        <ProgressState
          title="Counting the platform"
          description="Reading accounts, applications, the audit trail and the job listings."
        />
      ) : (
        <div className="space-y-10">
          <AdminOverviewBody data={overview.data} />
          <BackgroundRuns />
        </div>
      )}
    </div>
  )
}

function AdminOverviewBody({ data }: { data: AdminOverview }) {
  return (
    <div className="space-y-8">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <StatTile
          label="Accounts"
          value={data.accounts.total}
          hint={`${data.accounts.active} active · ${data.accounts.superusers} administrator${data.accounts.superusers === 1 ? "" : "s"}`}
        />
        <StatTile
          label="Tracked applications"
          value={data.applications.total}
          hint={`Across ${data.workflows.total} workflow${data.workflows.total === 1 ? "" : "s"}`}
        />
        <StatTile
          label="Audit rows"
          value={data.audit.total}
          hint="Every recorded platform action"
        />
        <StatTile
          label="Job corpus"
          value={data.corpus.jobs}
          hint="Shared listings (not per-account)"
        />
      </div>

      <p className="text-xs text-muted-foreground">
        Counted at {formatDateTime(data.generated_at)}.
      </p>

      <div className="grid gap-6 lg:grid-cols-2">
        <Section
          title="Applications by status"
          description="Where every tracked application currently sits."
        >
          {Object.keys(data.applications.by_status).length === 0 ? (
            <EmptyState
              title="No applications yet"
              description="Once any account prepares an application, it appears here by status."
            />
          ) : (
            <Distribution
              data={data.applications.by_status}
              labelFormat={(key) => describeStatus(key).label}
            />
          )}
        </Section>

        <Section
          title="Audit by actor"
          description="Who is doing the work across the platform."
        >
          <Distribution
            data={data.audit.by_actor_kind}
            labelFormat={(key) =>
              key === "agent"
                ? "The agent"
                : key === "user"
                  ? "People"
                  : key === "system"
                    ? "The system"
                    : key
            }
            tone="actor"
          />
        </Section>
      </div>

      <Section
        title="Audit by outcome"
        description="The health of the platform's actions at a glance."
      >
        {Object.keys(data.audit.by_outcome).length === 0 ? (
          <EmptyState
            title="Nothing recorded yet"
            description="The audit trail is empty."
          />
        ) : (
          <Distribution
            data={data.audit.by_outcome}
            labelFormat={(key) => key.charAt(0).toUpperCase() + key.slice(1)}
            tone="outcome"
          />
        )}
      </Section>
    </div>
  )
}

/** A horizontal distribution: a label, a count and a proportional bar. */
function Distribution({
  data,
  labelFormat,
  tone = "plain",
}: {
  data: Record<string, number>
  labelFormat: (key: string) => string
  tone?: "plain" | "actor" | "outcome"
}) {
  const entries = Object.entries(data).sort((a, b) => b[1] - a[1])
  const max = Math.max(1, ...entries.map(([, value]) => value))

  return (
    <Card>
      <CardContent className="space-y-2.5">
        {entries.map(([key, value]) => (
          <div key={key} className="flex items-center gap-3">
            <span className="w-40 shrink-0 truncate text-sm text-foreground">
              {labelFormat(key)}
            </span>
            <span
              aria-hidden="true"
              className="h-2 flex-1 overflow-hidden rounded-full bg-muted"
            >
              <span
                className="block h-full rounded-full"
                style={{
                  width: `${(value / max) * 100}%`,
                  backgroundColor: barColor(tone, key),
                }}
              />
            </span>
            <span className="w-10 shrink-0 text-right text-sm text-muted-foreground tabular-nums">
              {value}
            </span>
          </div>
        ))}
      </CardContent>
    </Card>
  )
}

function barColor(tone: "plain" | "actor" | "outcome", key: string): string {
  if (tone === "actor") {
    if (key === "agent") return "var(--color-lime)"
    if (key === "user") return "var(--color-terracotta)"
    return "var(--color-border)"
  }
  if (tone === "outcome") {
    if (key === "success") return "var(--color-lime)"
    if (key === "error") return "var(--color-destructive)"
    return "var(--color-terracotta)"
  }
  return "var(--color-primary)"
}

/**
 * The platform's background executions (WS-18).
 *
 * This is the recovery surface: an interrupted run is visible here with its
 * checkpoint, its remaining work, its embedding model and its last error, and
 * an administrator resumes it explicitly. The screen holds no authority —
 * the server checks `is_superuser` and validates the run's state, the model
 * and the dimension. A confirmation is shown before the resume because the
 * action changes durable state.
 */
/** The run types, as the filter offers them. */
const RUN_TYPE_FILTERS = [
  { value: "", label: "Everything" },
  { value: "refresh", label: "Refreshes" },
  { value: "embedding", label: "Embeddings" },
  { value: "reconcile", label: "Reconciliations" },
] as const

/**
 * The platform's background executions (WS-18).
 *
 * This is the recovery and oversight surface, and it reads like the
 * operator's own Operations screen on purpose: the same numbers, the same
 * status wording, the same progress panel — because both read the same rows.
 * Two things an administrator needs that an operator does not:
 *
 * - **Every type of run**, not just the embedding passes: a refresh and a
 *   reconciliation are queued work too, and one that never appears in the
 *   list looks like a button that did nothing.
 * - **Whether a worker is alive.** A queued run is not a failing run; it is
 *   a run waiting for a process. The banner says which, and names the
 *   command.
 *
 * The screen holds no authority: the server checks `is_superuser`, validates
 * the transition, the model and the dimension, and audits the act.
 */
function BackgroundRuns() {
  const [confirming, setConfirming] = useState<RunSummary | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [typeFilter, setTypeFilter] = useState<string>("")
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [activePage, setActivePage] = useState(0)
  const [inactivePage, setInactivePage] = useState(0)

  const runs = useQuery({
    queryKey: ["admin", "runs", typeFilter],
    queryFn: ({ signal }) =>
      api.adminRuns(typeFilter ? { job_type: typeFilter } : {}, signal),
    refetchInterval: (query) => adminRunsPollInterval(query.state.data?.runs),
  })

  const workers = useQuery({
    queryKey: ["admin", "workers"],
    queryFn: ({ signal }) => api.adminWorkerHealth(signal),
    refetchInterval: WORKER_HEALTH_POLL_MS,
  })

  const detail = useQuery({
    queryKey: ["admin", "run", expandedId],
    queryFn: ({ signal }) => api.adminRun(expandedId as string, signal),
    enabled: Boolean(expandedId),
    refetchInterval: (query) => runPollInterval(query.state.data?.run),
  })

  const resume = useMutation({
    mutationFn: (runId: string) => api.resumeEmbeddingRun(runId),
    onSuccess: (result) => {
      setConfirming(null)
      setNotice(
        `Run ${result.run_id} is ${result.status}. The worker resumes only the outstanding work.`
      )
      runs.refetch()
    },
  })

  const reconcile = useMutation({
    mutationFn: () => api.reconcileEmbeddings(),
    onSuccess: (result) => {
      setNotice(
        `Reconciliation ${result.queued ? "queued" : "already active"} as run ${result.run_id}.`
      )
      setTypeFilter("")
      setExpandedId(result.run_id)
      runs.refetch()
    },
  })

  const items = runs.data?.runs ?? []
  const waiting = items.filter((run) => !isRunTerminal(run.status)).length

  // Two groups, because they answer two different questions: "what is the
  // machine doing" and "what did it do". A settled run is history; a run in
  // flight is work. Mixing them in one list (and one long scroll) is what
  // made a 30-row queue look unreadable. "Active" is every status something
  // can still change from, which is deliberately wider than the terminal
  // set — a RECOVERABLE run is quiet but unfinished, and it belongs with the
  // work, where its Resume button is.
  const active = items.filter((run) => !isRunTerminal(run.status))
  const inactive = items.filter((run) => isRunTerminal(run.status))

  return (
    <Section
      title="Background runs"
      description="Every background job on the platform, of every type. A job keeps running when you close this page, and its state is stored on the server — not remembered here."
    >
      <div className="space-y-4">
        <WorkerControl
          health={workers.data}
          waiting={waiting}
          onChanged={() => workers.refetch()}
        />

        <div className="flex flex-wrap items-center justify-between gap-3">
          <div
            role="group"
            aria-label="Filter by run type"
            className="inline-flex rounded-lg border border-border bg-card p-0.5"
          >
            {RUN_TYPE_FILTERS.map((filter) => (
              <button
                key={filter.value || "all"}
                type="button"
                onClick={() => {
                  setTypeFilter(filter.value)
                  setExpandedId(null)
                  setActivePage(0)
                  setInactivePage(0)
                }}
                aria-pressed={typeFilter === filter.value}
                className={
                  typeFilter === filter.value
                    ? "rounded-md bg-primary px-3 py-1 text-xs font-medium text-primary-foreground"
                    : "rounded-md px-3 py-1 text-xs font-medium text-muted-foreground hover:text-foreground"
                }
              >
                {filter.label}
              </button>
            ))}
          </div>

          <Button
            variant="outline"
            disabled={reconcile.isPending}
            onClick={() => reconcile.mutate()}
          >
            {reconcile.isPending
              ? "Queueing the repair…"
              : "Repair the search index"}
          </Button>
        </div>

        {notice ? (
          <Banner tone="success" title="Accepted">
            <p>{notice}</p>
          </Banner>
        ) : null}
        {/* The administration screen is where the raw status and the
            server's own words are read: everything else says it in the
            product's voice (see src/lib/errors.ts). */}
        {resume.isError ? <ErrorNotice error={resume.error} verbose /> : null}
        {reconcile.isError ? (
          <ErrorNotice error={reconcile.error} verbose />
        ) : null}

        {runs.isError ? (
          <ErrorNotice
            error={runs.error}
            onRetry={() => runs.refetch()}
            verbose
          />
        ) : runs.isPending ? (
          <ProgressState
            title="Reading the background runs"
            description="Loading the platform's executions."
          />
        ) : items.length === 0 ? (
          <EmptyState
            title="No runs of this type"
            description="A refresh that finds new or changed listings creates one, and so does a reconciliation. Interrupted runs appear here with a Resume action."
          />
        ) : (
          <div className="space-y-8">
            <RunGroup
              title="Active"
              description="Work the machine can still change: queued, running, retrying, or interrupted and waiting for an administrator."
              runs={active}
              emptyText="Nothing is running or waiting. Every run below has finished."
              page={activePage}
              onPageChange={setActivePage}
              expandedId={expandedId}
              onToggleExpand={(id) =>
                setExpandedId(expandedId === id ? null : id)
              }
              onResume={setConfirming}
              detail={detail}
            />
            <RunGroup
              title="Inactive"
              description="Runs that have settled: finished, failed, cancelled. Kept for the record; nothing here changes on its own."
              runs={inactive}
              emptyText="No run has finished yet."
              page={inactivePage}
              onPageChange={setInactivePage}
              expandedId={expandedId}
              onToggleExpand={(id) =>
                setExpandedId(expandedId === id ? null : id)
              }
              onResume={setConfirming}
              detail={detail}
            />
          </div>
        )}

        <Dialog
          open={confirming !== null}
          onOpenChange={(open) => {
            if (!open) setConfirming(null)
          }}
        >
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Resume this embedding run?</DialogTitle>
              <DialogDescription>
                Only the outstanding work is queued; completed vectors are kept,
                the daily embedding budget still applies, and the action is
                audited against your account.
              </DialogDescription>
            </DialogHeader>
            {confirming ? (
              <dl className="grid grid-cols-2 gap-2 text-sm">
                <dt className="text-muted-foreground">Run</dt>
                <dd className="font-mono text-xs">{confirming.id}</dd>
                <dt className="text-muted-foreground">Status</dt>
                <dd>{runStatusCopy(confirming.status).label}</dd>
                <dt className="text-muted-foreground">Progress</dt>
                <dd>
                  {confirming.completed_items} of {confirming.total_items}{" "}
                  completed, {confirming.remaining_items} remaining
                </dd>
                <dt className="text-muted-foreground">Embedding model</dt>
                <dd>
                  {confirming.embedding_model ?? "—"} (
                  {confirming.embedding_dimension ?? "—"}-dimensional)
                </dd>
                <dt className="text-muted-foreground">Last error</dt>
                <dd className="text-xs">{confirming.last_error ?? "—"}</dd>
              </dl>
            ) : null}
            <DialogFooter>
              <Button variant="outline" onClick={() => setConfirming(null)}>
                Cancel
              </Button>
              <Button
                disabled={resume.isPending}
                onClick={() => {
                  if (confirming) resume.mutate(confirming.id)
                }}
              >
                {resume.isPending ? "Resuming…" : "Resume outstanding work"}
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </div>
    </Section>
  )
}

/** Rows per group page — five, so a group never becomes a long scroll. */
const RUNS_PER_PAGE = 5

/**
 * One group of runs: a heading, at most five rows, and its own page control.
 *
 * Active and inactive work are separated because they are read for different
 * reasons, and each group pages on its own so paging through history does not
 * move what is running. The backend returns the list in one call (the console
 * pages what it has); the day it outgrows that, only this slice changes.
 */
function RunGroup({
  title,
  description,
  runs,
  emptyText,
  page,
  onPageChange,
  expandedId,
  onToggleExpand,
  onResume,
  detail,
}: {
  title: string
  description: string
  runs: RunSummary[]
  emptyText: string
  page: number
  onPageChange: (page: number) => void
  expandedId: string | null
  onToggleExpand: (id: string) => void
  onResume: (run: RunSummary) => void
  detail: UseQueryResult<RunDetailResponse, Error>
}) {
  const pages = Math.max(1, Math.ceil(runs.length / RUNS_PER_PAGE))
  // Clamp rather than trust: a poll can shrink the list under a page the
  // operator is standing on, and an out-of-range slice would render empty.
  const current = Math.min(page, pages - 1)
  const visible = runs.slice(
    current * RUNS_PER_PAGE,
    current * RUNS_PER_PAGE + RUNS_PER_PAGE
  )

  return (
    <section className="space-y-3">
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <h3 className="text-sm font-semibold text-foreground">
          {title}
          <span className="ml-2 font-normal text-muted-foreground tabular-nums">
            {runs.length}
          </span>
        </h3>
        <p className="text-xs text-muted-foreground">{description}</p>
      </div>

      {runs.length === 0 ? (
        <p className="rounded-lg border border-dashed border-border px-3 py-6 text-center text-sm text-muted-foreground">
          {emptyText}
        </p>
      ) : (
        <>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Run</TableHead>
                <TableHead>Type</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Progress</TableHead>
                <TableHead>Created</TableHead>
                <TableHead>Heartbeat</TableHead>
                <TableHead>Last error</TableHead>
                {/* The action column is pinned twice over: `w-px` holds it at
                    the buttons' own width so a long neighbour cannot squeeze
                    it, and `sticky right-0` keeps it on screen while the
                    table scrolls. Sticky needs an opaque background, and it
                    must be the **page's** surface (`bg-background`), not the
                    card's: the table sits directly on the ivory page, so
                    `bg-card` painted a permanently lighter paper strip down
                    the right edge that read as a detached panel. The table
                    row is a `group`, so the pinned cells tint with the row on
                    hover instead of staying flat. */}
                <TableHead className="sticky right-0 z-10 w-px bg-background text-right">
                  Actions
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {visible.map((run) => (
                <Fragment key={run.id}>
                  <TableRow className="group">
                    <TableCell
                      className="cursor-help font-mono text-xs"
                      title={run.id}
                    >
                      {run.id.slice(0, 8)}
                    </TableCell>
                    <TableCell>{run.job_type}</TableCell>
                    {/* The status prose is informative and gets room — but a bounded
                        amount, and it clips rather than spills: a table cell is
                        `whitespace-nowrap`, so a long label would otherwise
                        paint over the Progress column beside it. The full text
                        is one hover (or one row expansion) away. */}
                    <TableCell
                      className={`max-w-52 truncate ${runStatusCopy(run.status).tone}`}
                      title={runStatusCopy(run.status).label}
                    >
                      {runStatusCopy(run.status).label}
                    </TableCell>
                    <TableCell className="tabular-nums">
                      {run.progress_percent}% ({run.completed_items}/
                      {run.total_items})
                    </TableCell>
                    {/* Relative, with the exact timestamp in the tooltip: an
                        operator reads "37s ago" for liveness, and the two
                        absolute timestamps cost 316px of a table that does
                        not fit its container. */}
                    <TableCell>
                      <RelativeTime value={run.created_at} />
                    </TableCell>
                    <TableCell>
                      <RelativeTime value={run.heartbeat_at} />
                    </TableCell>
                    {/* The error text is unbounded (a Node double reports
                        megabytes of it), so it is clamped to one line of a
                        capped block: max-width on a table cell is only a
                        hint, and the cell would otherwise widen the whole
                        table. The full text stays reachable on hover and in
                        the run's own panel. */}
                    <TableCell className="text-xs text-muted-foreground">
                      {run.last_error ? (
                        <div className="max-w-48 truncate" title={run.last_error}>
                          {run.last_error}
                        </div>
                      ) : (
                        "—"
                      )}
                    </TableCell>
                    <TableCell className="sticky right-0 z-10 w-px bg-background text-right group-hover:bg-muted">
                      <div className="flex justify-end gap-2">
                        <Button
                          size="sm"
                          variant="outline"
                          aria-expanded={expandedId === run.id}
                          onClick={() => onToggleExpand(run.id)}
                        >
                          {expandedId === run.id ? "Hide" : "Progress"}
                        </Button>
                        {run.resumable ? (
                          <Button
                            size="sm"
                            variant="outline"
                            onClick={() => onResume(run)}
                          >
                            Resume
                          </Button>
                        ) : null}
                      </div>
                    </TableCell>
                  </TableRow>
                  {expandedId === run.id ? (
                    <TableRow>
                      <TableCell colSpan={8} className="bg-muted/30">
                        {detail.isPending ? (
                          <ProgressState title="Reading the run" />
                        ) : detail.isError ? (
                          <ErrorNotice
                            error={detail.error}
                            onRetry={() => detail.refetch()}
                            verbose
                          />
                        ) : detail.data ? (
                          <RunProgress
                            run={detail.data.run}
                            events={detail.data.run.events}
                            verbose
                          />
                        ) : null}
                      </TableCell>
                    </TableRow>
                  ) : null}
                </Fragment>
              ))}
            </TableBody>
          </Table>
          <Pagination
            page={current}
            pageSize={RUNS_PER_PAGE}
            total={runs.length}
            onPageChange={onPageChange}
            label="runs"
          />
        </>
      )}
    </section>
  )
}

/**
 * The workers, and the two things you can do to them.
 *
 * The background work does not run inside a web request — it runs in these
 * processes. When the queue is backed up, or nothing is moving at all, this is
 * where you start another one, or stop one that is no longer wanted.
 *
 * Stopping is gentle: a worker finishes the item it is on and then leaves, so
 * nothing is dropped. The bound and the on/off switch are the server's, and
 * this only reports them — the buttons cannot exceed a limit the server
 * enforces anyway.
 */
function WorkerControl({
  health,
  waiting,
  onChanged,
}: {
  health?: WorkerHealthResponse
  waiting: number
  onChanged: () => void
}) {
  const [notice, setNotice] = useState<string | null>(null)

  const start = useMutation({
    mutationFn: () => api.startWorker(),
    onSuccess: (result) => {
      setNotice(
        `Starting ${result.worker_id}. It will pick up queued work shortly.`
      )
      onChanged()
    },
  })
  const stop = useMutation({
    mutationFn: (workerId: string) => api.stopWorker(workerId),
    onSuccess: (result) => {
      setNotice(`${result.worker_id} will stop after the job it is running.`)
      onChanged()
    },
  })

  const state = health?.workers
  const control = health?.control
  const workers = state?.workers ?? []
  const running = state?.healthy ?? 0
  // Rows that are not alive are kept apart from the live ones: a dead
  // worker's heartbeat row is history, and listing it beside a running
  // process is what made "running" and "stopped" read as the same thing.
  const live = workers.filter((worker) => worker.healthy)
  const departed = workers.filter((worker) => !worker.healthy)
  const atLimit = control ? running >= control.max_concurrent : false
  const canStart = Boolean(control?.enabled) && !atLimit

  return (
    <Card>
      <CardContent className="space-y-4 pt-6">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="space-y-1">
            <h3 className="text-sm font-medium text-foreground">
              {running === 0
                ? "No worker is running"
                : `${running} worker${running === 1 ? "" : "s"} running`}
              {departed.length > 0
                ? ` · ${departed.length} not running`
                : ""}
            </h3>
            <p className="text-sm text-muted-foreground">
              {running === 0
                ? "Queued work waits until a worker is running."
                : "These processes do the fetching, indexing and repairs."}
              {waiting > 0
                ? ` ${waiting} job${waiting === 1 ? "" : "s"} waiting.`
                : ""}
            </p>
          </div>
          <Button
            disabled={!canStart || start.isPending}
            onClick={() => {
              setNotice(null)
              start.mutate()
            }}
          >
            {start.isPending ? "Starting…" : "Start a worker"}
          </Button>
        </div>

        {control && !control.enabled ? (
          <p className="text-xs text-muted-foreground">
            This deployment manages its workers outside the app. Start one with{" "}
            <span className="font-mono">
              {"env\\Scripts\\python.exe scripts\\run_worker.py"}
            </span>
            .
          </p>
        ) : control ? (
          <p className="text-xs text-muted-foreground">
            Up to {control.max_concurrent} at once. A second worker helps when
            the queue is long; they share the search index, so start one only
            when you need to catch up.
          </p>
        ) : null}

        {live.length > 0 ? (
          <ul className="divide-y divide-border rounded-lg border border-border">
            {live.map((worker) => (
              <WorkerRow
                key={worker.worker_id}
                worker={worker}
                stopping={stop.isPending}
                onStop={() => {
                  setNotice(null)
                  stop.mutate(worker.worker_id)
                }}
              />
            ))}
          </ul>
        ) : null}

        {departed.length > 0 ? (
          <div className="space-y-2">
            <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
              Not running
            </p>
            <ul className="divide-y divide-border rounded-lg border border-dashed border-border">
              {departed.map((worker) => (
                <WorkerRow
                  key={worker.worker_id}
                  worker={worker}
                  stopping={stop.isPending}
                  onStop={() => {
                    setNotice(null)
                    stop.mutate(worker.worker_id)
                  }}
                />
              ))}
            </ul>
          </div>
        ) : null}

        {notice ? (
          <Banner tone="success" title="Done">
            <p>{notice}</p>
          </Banner>
        ) : null}
        {start.isError ? <ErrorNotice error={start.error} verbose /> : null}
        {stop.isError ? <ErrorNotice error={stop.error} verbose /> : null}
      </CardContent>
    </Card>
  )
}

/**
 * One worker's row.
 *
 * The status is rendered through `describeWorkerStatus`, never as the raw
 * value: the raw value is the database's word ("running"), and the whole
 * point of this row is to say something a person can act on. A worker that
 * has stopped responding still shows its last heartbeat age, so "stopped
 * responding 40m ago" and "stopped responding 3s ago" are distinguishable.
 */
function WorkerRow({
  worker,
  stopping,
  onStop,
}: {
  worker: WorkerHealthEntry
  stopping: boolean
  onStop: () => void
}) {
  const status = describeWorkerStatus(worker)
  const ageSeconds = Math.round(worker.heartbeat_age_seconds)
  const lastSeen =
    ageSeconds < 60
      ? `${ageSeconds}s ago`
      : ageSeconds < 3600
        ? `${Math.round(ageSeconds / 60)}m ago`
        : `${Math.round(ageSeconds / 3600)}h ago`

  return (
    <li className="flex flex-wrap items-center justify-between gap-3 px-3 py-2 text-sm">
      <div className="min-w-0 space-y-0.5">
        <div className="flex items-center gap-2">
          <span
            className={`inline-block size-2 shrink-0 rounded-full ${
              worker.healthy ? "bg-forest" : "bg-muted-foreground/40"
            }`}
            aria-hidden="true"
          />
          <p className="truncate font-mono text-xs text-foreground">
            {worker.worker_id}
          </p>
        </div>
        <p className="text-xs text-muted-foreground">
          <span className={workerStatusToneClass(status.tone)}>
            {status.label}
          </span>
          {worker.pid ? ` · pid ${worker.pid}` : ""} · heartbeat {lastSeen} ·{" "}
          {worker.processed_items} done
          {worker.failed_items > 0 ? `, ${worker.failed_items} failed` : ""}
        </p>
        <p className="text-xs text-muted-foreground/80">{status.note}</p>
      </div>
      <Button
        variant="outline"
        size="sm"
        disabled={!worker.stoppable || stopping}
        onClick={onStop}
      >
        Stop
      </Button>
    </li>
  )
}
