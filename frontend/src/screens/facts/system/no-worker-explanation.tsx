import { Banner } from "@/components/common/banner"

/*
  "Queued, but nothing is picking it up" (WS-40, master prompt §6.9).

  The durable queue outlives the API process: a `202` is recorded and will run
  whenever a worker is next available, and **starting the API does not start a
  worker** (`docs/RUNBOOK.md` §4.4). That is deliberate, and it is exactly the
  state an operator misreads as "the agent is broken" — a run sitting at 0%
  with nothing failing.

  So when a run has been queued and has not started moving, the screen says
  what is actually true and gives the documented command, copied verbatim from
  the runbook rather than paraphrased. This is a **hint, never an alarm**: the
  queue is working as designed, and the run has not failed.
*/

/** The command the runbook documents (§4.4), verbatim. */
export const WORKER_START_COMMAND = "python scripts/run_worker.py"

export function NoWorkerExplanation({ queuedCount }: { queuedCount: number }) {
  return (
    <Banner tone="neutral" title="Queued — waiting for a worker">
      <p>
        {queuedCount === 1
          ? "One run is accepted and waiting."
          : `${queuedCount} runs are accepted and waiting.`}{" "}
        Work is recorded durably and runs when a worker picks it up — starting
        the API does <strong>not</strong> start a worker, so a queued run can
        sit here indefinitely without anything being wrong. Nothing has failed.
      </p>
      <p className="mt-2">
        To process the queue, run the worker in a second terminal:
      </p>
      <pre className="mt-2 overflow-x-auto rounded-lg bg-muted px-3 py-2 font-mono text-xs text-foreground">
        <code>{WORKER_START_COMMAND}</code>
      </pre>
      <p className="mt-2 text-xs text-muted-foreground">
        Run one worker unless the vector store supports concurrent writers — the
        queue is safe with several, but the local embedder is not (RUNBOOK
        §4.4).
      </p>
    </Banner>
  )
}
