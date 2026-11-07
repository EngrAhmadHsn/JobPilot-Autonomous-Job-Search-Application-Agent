import { isRunTerminal } from "@/components/observability/run-progress"

/**
 * The console's polling budget.
 *
 * The rule these numbers implement: **every polled resource stays at or below
 * 10 requests/minute**, terminal work is polled zero times, and an idle screen
 * costs almost nothing. The API's own abuse limit is 60 requests/minute per
 * client, shared with user actions and any second visible window, so the
 * console must budget rather than hope.
 *
 * | query                     | cadence | requests/min |
 * |---------------------------|---------|--------------|
 * | health                    | 30 s    | 2            |
 * | audit (activity)          | 30 s    | 2            |
 * | applications + audit (overview) | 30 s | 4           |
 * | one active run            | 6 s     | 10           |
 * | active parent while its child runs | 15 s | 4        |
 * | runs list, something running | 20 s | 3            |
 * | runs list, everything settled | 60 s | 1           |
 * | admin runs, something running | 10 s | 6            |
 * | admin runs, everything settled | 60 s | 1          |
 * | worker health             | 20 s    | 3            |
 *
 * Hidden tabs stop all of it: TanStack pauses interval fetches while the
 * document is hidden (`refetchIntervalInBackground` is false, deliberately).
 * The elapsed-time clocks tick locally at no request cost (see
 * `use-now.ts` / `relative-time.tsx`).
 */
export const HEALTH_POLL_MS = 30_000
export const ACTIVITY_POLL_MS = 30_000
export const OVERVIEW_POLL_MS = 30_000

/** One run the operator is watching, while it is still doing work. */
export const RUN_ACTIVE_POLL_MS = 6_000

/**
 * A run whose child is doing the work can only change when the child does, so
 * while both are active the parent slows down instead of doubling the load.
 */
export const RUN_ACTIVE_WITH_CHILD_POLL_MS = 15_000

/** The runs list: discover promptly while something is running… */
export const RUNS_LIST_ACTIVE_POLL_MS = 20_000
/** …and keep a one-per-minute heartbeat when everything has settled. */
export const RUNS_LIST_IDLE_POLL_MS = 60_000

export const ADMIN_RUNS_ACTIVE_POLL_MS = 10_000
export const ADMIN_RUNS_IDLE_POLL_MS = 60_000
export const WORKER_HEALTH_POLL_MS = 20_000

/** The fields the poll decision needs — a `RunSummary` or `RunDetail` fits. */
interface PollableRun {
  status: string
  metadata?: Record<string, unknown>
}

/**
 * The refetch interval for one run's detail.
 *
 * A terminal run is polled **never** (the state cannot change without an
 * actor). An active run polls while it works; if it has spawned an embedding
 * child, the parent slows down because the child's progress — not the
 * parent's — is what is moving.
 */
export function runPollInterval(run: PollableRun | undefined): number | false {
  if (!run) return RUN_ACTIVE_POLL_MS
  if (isRunTerminal(run.status)) return false
  const refresh = run.metadata?.refresh as
    { embedding_run_id?: string | null } | undefined
  return refresh?.embedding_run_id
    ? RUN_ACTIVE_WITH_CHILD_POLL_MS
    : RUN_ACTIVE_POLL_MS
}

/** The refetch interval for a list of runs. */
export function runsListPollInterval(
  runs: ReadonlyArray<{ status: string }> | undefined
): number {
  if (!runs) return RUNS_LIST_ACTIVE_POLL_MS
  return runs.some((run) => !isRunTerminal(run.status))
    ? RUNS_LIST_ACTIVE_POLL_MS
    : RUNS_LIST_IDLE_POLL_MS
}

/** The refetch interval for the administration runs table. */
export function adminRunsPollInterval(
  runs: ReadonlyArray<{ status: string }> | undefined
): number {
  if (!runs) return ADMIN_RUNS_ACTIVE_POLL_MS
  return runs.some((run) => !isRunTerminal(run.status))
    ? ADMIN_RUNS_ACTIVE_POLL_MS
    : ADMIN_RUNS_IDLE_POLL_MS
}
