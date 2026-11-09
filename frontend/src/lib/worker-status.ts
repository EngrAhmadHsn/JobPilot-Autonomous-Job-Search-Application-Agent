import type { WorkerHealthEntry } from "@/lib/api/types"

/**
 * What a worker's status means to the operator.
 *
 * The console **never prints the raw status string**. The stored vocabulary
 * (`running`/`stopping`/`stopped`/`crashed`) is the database's word, not a
 * sentence, and printing it verbatim produced the reported defect: a worker
 * that had been dead for hours still read "running", because the row it came
 * from said so. The `status` here is the server's **effective** status (it
 * derives `crashed` from a stale heartbeat), and this module gives each value
 * a label, a tone, and a next step.
 */
export interface WorkerStatusPresentation {
  label: string
  tone: "ok" | "stopping" | "idle" | "dead"
  /** What the operator should do, or why nothing is needed. */
  note: string
}

export function describeWorkerStatus(
  worker: Pick<WorkerHealthEntry, "status" | "heartbeat_age_seconds">
): WorkerStatusPresentation {
  switch (worker.status) {
    case "running":
      return {
        label: "Running",
        tone: "ok",
        note: "Heartbeating normally and draining the queue.",
      }
    case "stopping":
      return {
        label: "Stopping",
        tone: "stopping",
        note: "Asked to finish the current batch and exit.",
      }
    case "stopped":
      return {
        label: "Stopped",
        tone: "idle",
        note: "Exited cleanly. Its queued work waits for another worker.",
      }
    case "crashed":
      return {
        label: "Stopped responding",
        tone: "dead",
        note: "It stopped heartbeating without exiting — the process is gone. Its work is queued for the next worker.",
      }
    default:
      // An unfamiliar status is shown verbatim rather than hidden: the
      // console does not invent a meaning for a value it does not know.
      return {
        label: worker.status,
        tone: "idle",
        note: "The server reported a status this console does not know. The raw value is shown unchanged.",
      }
  }
}

/** The tailwind text colour for a worker status tone. */
export function workerStatusToneClass(tone: WorkerStatusPresentation["tone"]): string {
  switch (tone) {
    case "ok":
      return "text-forest"
    case "stopping":
      return "text-terracotta"
    case "dead":
      return "text-destructive"
    case "idle":
    default:
      return "text-muted-foreground"
  }
}