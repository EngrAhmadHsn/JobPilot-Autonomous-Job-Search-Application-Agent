import { useMutation, useQuery } from "@tanstack/react-query"
import { useState } from "react"

import { Banner } from "@/components/common/banner"
import { EmptyState, ProgressState } from "@/components/common/progress-state"
import { ErrorNotice } from "@/components/common/error-notice"
import { PageHeader, Section } from "@/components/common/page-header"
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
import type { AdminOverview, RunSummary } from "@/lib/api/types"
import { formatDateTime } from "@/lib/format"
import { describeStatus } from "@/lib/status"

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
          />
        )
      ) : overview.isPending || !overview.data ? (
        <ProgressState
          title="Counting the platform"
          description="Reading accounts, applications, the audit trail and the corpus."
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
            <span className="w-10 shrink-0 text-right text-sm tabular-nums text-muted-foreground">
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
function BackgroundRuns() {
  const [confirming, setConfirming] = useState<RunSummary | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  const runs = useQuery({
    queryKey: ["admin", "embedding-runs"],
    queryFn: ({ signal }) => api.adminEmbeddingRuns(signal),
    refetchInterval: 5_000,
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
      runs.refetch()
    },
  })

  return (
    <Section
      title="Background runs"
      description="Durable executions of the embedding worker. A run's state survives the browser, the API process and a worker restart."
    >
      <div className="space-y-4">
        <div className="flex flex-wrap gap-2">
          <Button
            variant="outline"
            disabled={reconcile.isPending}
            onClick={() => reconcile.mutate()}
          >
            {reconcile.isPending
              ? "Queueing reconciliation..."
              : "Reconcile the vector index"}
          </Button>
        </div>

        {notice ? (
          <Banner tone="success" title="Accepted">
            <p>{notice}</p>
          </Banner>
        ) : null}
        {resume.isError ? <ErrorNotice error={resume.error} /> : null}
        {reconcile.isError ? <ErrorNotice error={reconcile.error} /> : null}

        {runs.isError ? (
          <ErrorNotice error={runs.error} onRetry={() => runs.refetch()} />
        ) : runs.isPending ? (
          <ProgressState
            title="Reading the background runs"
            description="Loading the platform's embedding executions."
          />
        ) : (runs.data?.runs.length ?? 0) === 0 ? (
          <EmptyState
            title="No embedding runs yet"
            description="A refresh that finds new or changed listings creates one. Interrupted runs appear here with a Resume action."
          />
        ) : (
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
                <TableHead>Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {runs.data!.runs.map((run) => (
                <TableRow key={run.id}>
                  <TableCell className="font-mono text-xs">
                    {run.id.slice(0, 12)}
                  </TableCell>
                  <TableCell>{run.job_type}</TableCell>
                  <TableCell>{run.status}</TableCell>
                  <TableCell className="tabular-nums">
                    {run.progress_percent}% ({run.completed_items}/
                    {run.total_items})
                  </TableCell>
                  <TableCell>{formatDateTime(run.created_at)}</TableCell>
                  <TableCell>{formatDateTime(run.heartbeat_at)}</TableCell>
                  <TableCell className="max-w-56 truncate text-xs text-muted-foreground">
                    {run.last_error ?? "—"}
                  </TableCell>
                  <TableCell>
                    {run.resumable ? (
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => setConfirming(run)}
                      >
                        Resume
                      </Button>
                    ) : (
                      <span className="text-xs text-muted-foreground">—</span>
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
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
                Only the outstanding work is queued; completed vectors are
                kept, the daily embedding budget still applies, and the
                action is audited against your account.
              </DialogDescription>
            </DialogHeader>
            {confirming ? (
              <dl className="grid grid-cols-2 gap-2 text-sm">
                <dt className="text-muted-foreground">Run</dt>
                <dd className="font-mono text-xs">{confirming.id}</dd>
                <dt className="text-muted-foreground">Status</dt>
                <dd>{confirming.status}</dd>
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
                {resume.isPending ? "Resuming..." : "Resume outstanding work"}
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </div>
    </Section>
  )
}
