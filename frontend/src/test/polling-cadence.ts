import { isRunTerminal } from "@/components/observability/run-progress"

/**
 * Test double for `@/lib/polling` with the **production cadences compressed to
 * milliseconds**, so a screen test can observe the wiring — which query
 * polls, which stops, what stays silent — without waiting minutes for it.
 *
 * The rules are the same as the real module's; those rules are pinned in
 * `src/lib/polling.test.ts` against the real cadences. What is duplicated
 * here is only the wiring under test.
 */
export const HEALTH_POLL_MS = 80
export const ACTIVITY_POLL_MS = 80
export const OVERVIEW_POLL_MS = 80
export const RUN_ACTIVE_POLL_MS = 60
export const RUN_ACTIVE_WITH_CHILD_POLL_MS = 150
export const RUNS_LIST_ACTIVE_POLL_MS = 120
export const RUNS_LIST_IDLE_POLL_MS = 600
export const ADMIN_RUNS_ACTIVE_POLL_MS = 60
export const ADMIN_RUNS_IDLE_POLL_MS = 600
export const WORKER_HEALTH_POLL_MS = 150

interface PollableRun {
  status: string
  metadata?: Record<string, unknown>
}

export function runPollInterval(run: PollableRun | undefined): number | false {
  if (!run) return RUN_ACTIVE_POLL_MS
  if (isRunTerminal(run.status)) return false
  const refresh = run.metadata?.refresh as
    { embedding_run_id?: string | null } | undefined
  return refresh?.embedding_run_id
    ? RUN_ACTIVE_WITH_CHILD_POLL_MS
    : RUN_ACTIVE_POLL_MS
}

export function runsListPollInterval(
  runs: ReadonlyArray<{ status: string }> | undefined
): number {
  if (!runs) return RUNS_LIST_ACTIVE_POLL_MS
  return runs.some((run) => !isRunTerminal(run.status))
    ? RUNS_LIST_ACTIVE_POLL_MS
    : RUNS_LIST_IDLE_POLL_MS
}

export function adminRunsPollInterval(
  runs: ReadonlyArray<{ status: string }> | undefined
): number {
  if (!runs) return ADMIN_RUNS_ACTIVE_POLL_MS
  return runs.some((run) => !isRunTerminal(run.status))
    ? ADMIN_RUNS_ACTIVE_POLL_MS
    : ADMIN_RUNS_IDLE_POLL_MS
}
