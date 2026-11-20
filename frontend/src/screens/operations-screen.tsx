import { useMutation, useQuery } from "@tanstack/react-query"
import { useMemo, useState } from "react"
import { Link } from "react-router-dom"

import { Banner } from "@/components/common/banner"
import { ErrorNotice } from "@/components/common/error-notice"
import { EmptyState, ProgressState } from "@/components/common/progress-state"
import { TablePager } from "@/components/common/pagination"
import { PageHeader, Section } from "@/components/common/page-header"
import {
  RunProgress,
  isRunTerminal,
  runStatusCopy,
} from "@/components/observability/run-progress"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
  TableSortHead,
} from "@/components/ui/table"

import { api } from "@/lib/api/endpoints"
import type {
  RunAccepted,
  RunDetail,
  RunSummary,
  SourceStatusResponse,
} from "@/lib/api/types"
import { formatDateTime } from "@/lib/format"
import { runPollInterval, runsListPollInterval } from "@/lib/polling"
import { describeStatus } from "@/lib/status"
import { NoWorkerExplanation } from "@/screens/facts/system/no-worker-explanation"

/**
 * The Operations screen (WS-42, design node `16:282`).
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
 *
 * The design's composition: the explain panel, then a 2:1 row — the
 * "Job corpus refresh" card (the queue affordance, the tracked run and its
 * recovery path) beside the "Corpus freshness" card — then the source
 * registry's table, then the run history.
 */
export function OperationsScreen() {
  /** A run the operator pinned by hand (or queued just now). */
  const [pickedId, setPickedId] = useState<string | null>(null)

  const history = useQuery({
    queryKey: ["runs", "history"],
    queryFn: ({ signal }) => api.listRuns(signal),
    // Patient while everything has settled, prompt while something is moving.
    refetchInterval: (query) => runsListPollInterval(query.state.data?.runs),
  })

  /*
    The corpus's source registry and freshness (design nodes 49:1449 and
    49:3253). The registry is shared across the instance's operators — the
    same rule as the corpus — so this read is account-wide.
  */
  const sources = useQuery({
    queryKey: ["jobs", "sources"],
    queryFn: ({ signal }) => api.sourceStatus(signal),
    refetchInterval: 60_000,
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
    pickedId ??
    runs.find((run) => !isRunTerminal(run.status))?.id ??
    runs[0]?.id ??
    null

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
    // A terminal run is polled never; an active one at the budgeted cadence.
    refetchInterval: (query) => runPollInterval(query.state.data?.run),
  })

  const detail: RunDetail | undefined = tracked.data?.run

  /*
    A refresh run finishes quickly (it fetches and persists); the embedding
    it started is the long part. Its id is on the parent's metadata, so the
    screen can show both without a second endpoint.
  */
  const childId =
    (
      detail?.metadata?.refresh as
        { embedding_run_id?: string | null } | undefined
    )?.embedding_run_id ?? null
  const child = useQuery({
    queryKey: ["run", childId],
    queryFn: ({ signal }) => api.getRun(childId as string, signal),
    enabled: Boolean(childId),
    refetchInterval: (query) => runPollInterval(query.state.data?.run),
  })

  return (
    <div className="space-y-6">
      <PageHeader
        title="Keep your workspace moving."
        documentTitle="Operations"
        description="Sources, freshness, and background work — away from your daily flow."
      />

      {/*
        The design's explain panel (node `49:1431`), because the search/refresh
        distinction is the one thing operators misread: Discovery searches the
        listings already stored; the refresh here fetches new ones, and the
        run keeps going after this page is closed.
      */}
      <section className="rounded-surface bg-forest-soft p-[18px]">
        <h2 className="text-base leading-[23px] font-semibold text-primary">
          Search finds matches. Refresh brings in new listings.
        </h2>
        <p className="mt-1.5 text-[13px] leading-[19px] text-muted-foreground">
          Discovery searches the stored corpus. Background refreshes continue
          even when you leave this page.
        </p>
      </section>

      {/*
        The design's 2:1 row (node `49:1434`): the refresh card — the one
        durable thing this screen operates — beside the corpus's freshness.
      */}
      <div className="grid gap-6 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)] lg:items-start">
        <Card>
          <CardHeader>
            <CardTitle>Job corpus refresh</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <p className="text-sm text-muted-foreground">
              Fetches the boards, drops duplicates, stores the new listings and
              indexes them for matching. Only new or changed listings are
              embedded, and a second click joins the run already going.
            </p>

            <div className="flex flex-wrap items-center gap-3">
              <Button
                disabled={refresh.isPending}
                onClick={() => refresh.mutate()}
              >
                {refresh.isPending ? "Queueing…" : "Queue the refresh"}
              </Button>

              {/*
                The design's recovery path (nodes 49:1435–49:1447): a run the
                lease reaper marked RECOVERABLE carries its chip, the one
                sentence that says who may resume it, and the way there.
              */}
              {detail?.status === "RECOVERABLE" ? (
                <>
                  <span className="type-eyebrow rounded-md bg-terracotta-soft px-2 py-1 text-terracotta-foreground">
                    Recoverable
                  </span>
                  <span className="text-[13px] leading-[19px] text-muted-foreground">
                    An administrator can resume only the unfinished work.
                  </span>
                  <Link
                    to="/app/admin"
                    viewTransition
                    className="inline-flex h-[37px] items-center rounded-lg bg-primary px-3.5 text-[13px] leading-[19px] font-semibold text-primary-foreground outline-none transition-colors hover:bg-primary/90 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
                  >
                    Open administration →
                  </Link>
                </>
              ) : null}
            </div>

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
                  {/* The run's own status, in the centralized vocabulary —
                      never the raw machine string (WS-40: the overlap between
                      the run vocabulary and `describeStatus` is exactly the
                      `QUEUED`/`RUNNING` a 202 answer carries). The label reads
                      "Accepted and queued", so the sentence does not repeat
                      "accepted". */}
                  Run <code>{refresh.data.run_id}</code>:{" "}
                  <strong>{describeStatus(refresh.data.status).label}</strong>.
                  It runs in the background — you can close this page.
                </p>
              </Banner>
            ) : null}

            {/*
              WS-40 / master prompt §6.9: a queued run with no worker is the
              state an operator misreads as breakage. Named only when the run is
              actually QUEUED — never as a general disclaimer.
            */}
            {detail?.status === "QUEUED" ? (
              <div className="mt-4">
                <NoWorkerExplanation queuedCount={1} />
              </div>
            ) : null}

            {/*
              The tracked run's own state, under the queue affordance — the
              design draws the run and its progress inside this card (the
              app's "Latest run" heading keeps the section's name for the
              tests and the screen reader).
            */}
            {detail ? (
              <div className="space-y-4 border-t border-border-surface pt-4">
                <h3 className="type-card-title">Latest run</h3>
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
                        <ProgressState title="Making your jobs searchable" />
                      )}
                    </div>
                  </div>
                ) : null}
              </div>
            ) : null}
          </CardContent>
        </Card>

        <CorpusFreshnessCard
          sources={sources.data}
          pending={sources.isPending}
          error={sources.error}
          onRetry={() => void sources.refetch()}
        />
      </div>

      <SourceStatusTable
        sources={sources.data}
        pending={sources.isPending}
        error={sources.error}
        onRetry={() => void sources.refetch()}
      />

      <Section
        title="Recent runs"
        description="Everything this account has run, newest first. Reopen the page and the state is still here."
      >
        {history.isError ? (
          <ErrorNotice
            error={history.error}
            onRetry={() => history.refetch()}
          />
        ) : history.isPending ? (
          <ProgressState
            title="Reading the run history"
            description="Loading your runs."
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

/** "Today, 08:40" — the freshness card's own date voice. */
function freshnessDate(iso: string | null): string {
  if (!iso) return "Never"
  const date = new Date(iso)
  const now = new Date()
  const time = date.toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
  })
  if (date.toDateString() === now.toDateString()) return `Today, ${time}`
  const yesterday = new Date(now)
  yesterday.setDate(now.getDate() - 1)
  if (date.toDateString() === yesterday.toDateString()) {
    return `Yesterday, ${time}`
  }
  return date.toLocaleDateString([], { month: "short", day: "numeric" })
}

/** One label/value row of the freshness card (nodes 49:1451–49:1457). */
function FreshnessRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline justify-between gap-4">
      <dt className="text-xs leading-[17px] text-muted-foreground">{label}</dt>
      <dd className="text-[13px] leading-[19px] font-semibold text-forest">
        {value}
      </dd>
    </div>
  )
}

/**
 * The corpus's freshness (design node 49:1449): when the refresh last ran
 * to completion, how many providers the registry watches, and whether the
 * stored corpus can answer a search at all.
 */
function CorpusFreshnessCard({
  sources,
  pending,
  error,
  onRetry,
}: {
  sources: SourceStatusResponse | undefined
  pending: boolean
  error: unknown
  onRetry: () => void
}) {
  return (
    <div className="surface p-5">
      <h2 className="type-section">Corpus freshness</h2>
      {pending ? (
        <p className="type-caption mt-3" role="status">
          Reading the registry…
        </p>
      ) : error ? (
        <ErrorNotice error={error} onRetry={onRetry} />
      ) : sources ? (
        <dl className="mt-4 space-y-[14px]">
          <FreshnessRow
            label="Last completed refresh"
            value={freshnessDate(sources.last_refresh_completed_at)}
          />
          <FreshnessRow
            label="Source adapters"
            value={`${sources.adapters.length} configured`}
          />
          <FreshnessRow
            label="Search availability"
            value={
              sources.jobs_stored > 0
                ? "Stored jobs available"
                : "No stored jobs"
            }
          />
        </dl>
      ) : null}
    </div>
  )
}

type SourceSortKey = "source" | "last_check" | "state"

/**
 * The source registry's table (design node 49:3253, component 49:2428):
 * sortable Source / Last check / Current state columns over the watched
 * boards, with the design's pager. A failing board reads as failing — the
 * one place the table's plain text earns a tone colour, because a source
 * that cannot answer is the fact this table exists to tell.
 */
function SourceStatusTable({
  sources,
  pending,
  error,
  onRetry,
}: {
  sources: SourceStatusResponse | undefined
  pending: boolean
  error: unknown
  onRetry: () => void
}) {
  const [sort, setSort] = useState<{ key: SourceSortKey; dir: "asc" | "desc" | null }>({
    key: "source",
    dir: null,
  })
  const [page, setPage] = useState(0)
  const [pageSize, setPageSize] = useState(10)

  // A stable fallback: `?? []` creates a new array each render, which would
  // make the sort memo recompute every time for no reason.
  const boards = useMemo(() => sources?.boards ?? [], [sources])
  const sorted = useMemo(() => {
    if (sort.dir === null) return boards
    const direction = sort.dir === "asc" ? 1 : -1
    return [...boards].sort((a, b) => {
      switch (sort.key) {
        case "source":
          return a.id.localeCompare(b.id) * direction
        case "last_check":
          return (
            ((Date.parse(a.last_ok_at ?? "") || 0) -
              (Date.parse(b.last_ok_at ?? "") || 0)) *
            direction
          )
        case "state": {
          const byHealth = Number(a.failing) - Number(b.failing)
          return (byHealth || a.id.localeCompare(b.id)) * direction
        }
      }
    })
  }, [boards, sort])

  const paged = sorted.slice(page * pageSize, (page + 1) * pageSize)
  const cycle = (key: SourceSortKey) => (next: "asc" | "desc" | null) => {
    setSort({ key, dir: next })
    setPage(0)
  }

  return (
    <Section
      title="Source status"
      description="The boards the refresh watches, with their last successful check."
    >
      {pending ? (
        <ProgressState
          title="Reading the source registry"
          description="Loading the watched boards."
        />
      ) : error ? (
        <ErrorNotice error={error} onRetry={onRetry} />
      ) : boards.length === 0 ? (
        <EmptyState
          title="No boards registered"
          description="A refresh seeds the registry from the environment's board lists."
        />
      ) : (
        <div className="surface p-5">
          <Table>
            <TableHeader>
              <TableRow>
                <TableSortHead
                  label="Source"
                  sort={sort.key === "source" ? sort.dir : null}
                  onSortChange={cycle("source")}
                />
                <TableSortHead
                  label="Last check"
                  sort={sort.key === "last_check" ? sort.dir : null}
                  onSortChange={cycle("last_check")}
                />
                <TableSortHead
                  label="Current state"
                  sort={sort.key === "state" ? sort.dir : null}
                  onSortChange={cycle("state")}
                />
                <TableHead className="text-right">Listings</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {paged.map((board) => (
                <TableRow key={board.id}>
                  <TableCell className="py-[13px] text-xs font-semibold">
                    {board.company_name ?? board.id}
                    <span className="ml-2 font-mono text-[11px] font-normal text-muted-foreground">
                      {board.ats}
                    </span>
                  </TableCell>
                  <TableCell
                    className="py-[13px] text-xs text-muted-foreground"
                    title={board.last_error ?? undefined}
                  >
                    {board.last_ok_at ? freshnessDate(board.last_ok_at) : "Never"}
                  </TableCell>
                  <TableCell
                    className={
                      board.failing
                        ? "py-[13px] text-xs text-destructive"
                        : "py-[13px] text-xs text-muted-foreground"
                    }
                  >
                    {board.failing
                      ? "Failing"
                      : board.enabled
                        ? "Enabled"
                        : "Off"}
                  </TableCell>
                  <TableCell className="py-[13px] text-right text-xs text-muted-foreground tabular-nums">
                    {board.listings_seen}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          <TablePager
            page={page}
            pageSize={pageSize}
            total={boards.length}
            onPageChange={setPage}
            onPageSizeChange={(next) => {
              setPageSize(next)
              setPage(0)
            }}
            className="mt-3"
          />
        </div>
      )}
    </Section>
  )
}

type RunSortKey = "run" | "type" | "state" | "progress" | "created"

/**
 * The run history, with the interactive-table set's affordances (node
 * `49:3745`): sortable Run/Type/State/Progress columns and the pager.
 */
function RunsTable({
  runs,
  trackedId,
  onTrack,
}: {
  runs: RunSummary[]
  trackedId: string | null
  onTrack: (runId: string) => void
}) {
  const [sort, setSort] = useState<{ key: RunSortKey; dir: "asc" | "desc" | null }>({
    key: "created",
    dir: null,
  })
  const [page, setPage] = useState(0)
  const [pageSize, setPageSize] = useState(10)

  const sorted = useMemo(() => {
    if (sort.dir === null) return runs
    const direction = sort.dir === "asc" ? 1 : -1
    return [...runs].sort((a, b) => {
      switch (sort.key) {
        case "run":
          return a.id.localeCompare(b.id) * direction
        case "type":
          return a.job_type.localeCompare(b.job_type) * direction
        case "state":
          return a.status.localeCompare(b.status) * direction
        case "progress":
          return (a.progress_percent - b.progress_percent) * direction
        case "created":
          return (
            ((Date.parse(a.created_at ?? "") || 0) -
              (Date.parse(b.created_at ?? "") || 0)) *
            direction
          )
      }
    })
  }, [runs, sort])

  const paged = sorted.slice(page * pageSize, (page + 1) * pageSize)
  const cycle = (key: RunSortKey) => (next: "asc" | "desc" | null) => {
    setSort({ key, dir: next })
    setPage(0)
  }

  return (
    <div className="surface p-5">
      <Table>
        <TableHeader>
          <TableRow>
            <TableSortHead
              label="Run"
              sort={sort.key === "run" ? sort.dir : null}
              onSortChange={cycle("run")}
            />
            <TableSortHead
              label="Type"
              sort={sort.key === "type" ? sort.dir : null}
              onSortChange={cycle("type")}
            />
            <TableSortHead
              label="State"
              sort={sort.key === "state" ? sort.dir : null}
              onSortChange={cycle("state")}
            />
            <TableSortHead
              label="Progress"
              sort={sort.key === "progress" ? sort.dir : null}
              onSortChange={cycle("progress")}
            />
            <TableSortHead
              label="Created"
              sort={sort.key === "created" ? sort.dir : null}
              onSortChange={cycle("created")}
            />
            <TableHead className="text-right">Actions</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {paged.map((run) => (
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
      <TablePager
        page={page}
        pageSize={pageSize}
        total={runs.length}
        onPageChange={setPage}
        onPageSizeChange={(next) => {
          setPageSize(next)
          setPage(0)
        }}
        className="mt-3"
      />
    </div>
  )
}
