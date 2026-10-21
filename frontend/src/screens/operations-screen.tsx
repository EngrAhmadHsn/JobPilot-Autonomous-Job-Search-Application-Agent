import { useMutation } from "@tanstack/react-query"
import { useRef, useState } from "react"

import { Banner } from "@/components/common/banner"
import { ErrorNotice } from "@/components/common/error-notice"
import { FieldList, SectionTitle } from "@/components/common/field-list"
import { EmptyState, ProgressState } from "@/components/common/progress-state"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"

import { api } from "@/lib/api/endpoints"
import type { JobRefreshResponse } from "@/lib/api/types"

/**
 * The Operations screen.
 *
 * The refresh is the one call that reaches the outside world: it fetches the
 * job boards, normalizes, deduplicates, persists and embeds. It takes
 * minutes, it is idempotent and resumable, and it is bounded by the
 * backend's own limits (the corpus cap, the daily embedding budget, the
 * spam screen).
 *
 * The console does not run it in the background or on a timer: the operator
 * starts it, watches it, and reads the report.
 */
export function OperationsScreen() {
  const [run, setRun] = useState(0)
  const abortRef = useRef<AbortController | null>(null)

  const refresh = useMutation({
    mutationFn: () => {
      const controller = new AbortController()
      abortRef.current = controller
      return api.refreshJobs(controller.signal)
    },
  })

  const report: JobRefreshResponse | undefined = refresh.data

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>Refresh the job corpus</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <p className="text-sm text-muted-foreground">
            One run: fetch the boards → normalize → deduplicate → persist →
            embed. Only new or changed listings cost an embedding, and a run
            stopped by the daily budget leaves everything persisted for the next
            one.
          </p>

          <Button
            disabled={refresh.isPending}
            onClick={() => {
              setRun((value) => value + 1)
              refresh.mutate()
            }}
          >
            {refresh.isPending ? "Refreshing…" : "Run the refresh"}
          </Button>

          {refresh.isPending ? (
            <ProgressState
              key={`refresh-${run}`}
              title="Refreshing the corpus"
              description="Fetching the boards, normalizing and embedding. This can take minutes."
              onCancel={() => abortRef.current?.abort()}
            >
              <p className="text-xs text-muted-foreground">
                Cancelling stops the console waiting. The server&apos;s run is
                resumable and keeps what it already persisted.
              </p>
            </ProgressState>
          ) : null}

          {refresh.isError ? <ErrorNotice error={refresh.error} /> : null}
        </CardContent>
      </Card>

      {report ? (
        <Card>
          <CardHeader>
            <CardTitle>The report</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            {report.quota_exhausted ? (
              <Banner
                tone="warning"
                title="The run stopped on the daily embedding budget"
              >
                <p>
                  The listings were fetched and persisted; only the embedding
                  ran out. The next run resumes at no extra cost.
                </p>
              </Banner>
            ) : null}

            {report.degraded_embedding ? (
              <Banner tone="warning" title="The embedding was degraded">
                <p>
                  Some listings were persisted without a vector, so a later
                  search will score them weakly. The search screen says so when
                  it happens.
                </p>
              </Banner>
            ) : null}

            <FieldList
              items={[
                { label: "Found", value: report.stats.found },
                { label: "Dropped", value: report.stats.dropped },
                { label: "Deduped", value: report.stats.deduped },
                { label: "Persisted", value: report.stats.persisted },
                { label: "Embedded", value: report.stats.embedded },
                { label: "Screened out", value: report.stats.screened_out },
                {
                  label: "Admission capped",
                  value: report.stats.admission_capped,
                },
                {
                  label: "Embedding requests",
                  value: `${report.embedding_requests_used} of ${report.embedding_requests_planned}`,
                },
                {
                  label: "Quota exhausted",
                  value: report.quota_exhausted ? "Yes" : "No",
                },
                {
                  label: "Degraded embedding",
                  value: report.degraded_embedding ? "Yes" : "No",
                },
              ]}
            />

            {Object.keys(report.source_errors).length > 0 ? (
              <div className="space-y-1">
                <SectionTitle>Sources that failed</SectionTitle>
                <ul className="list-disc space-y-1 pl-5 text-sm">
                  {Object.entries(report.source_errors).map(
                    ([source, message]) => (
                      <li key={source}>
                        <span className="font-medium">{source}</span>: {message}
                      </li>
                    )
                  )}
                </ul>
              </div>
            ) : (
              <p className="text-sm text-muted-foreground">
                Every source answered.
              </p>
            )}
          </CardContent>
        </Card>
      ) : (
        <EmptyState
          title="No refresh yet"
          description="Run a refresh to fetch new listings into the corpus. The report below says exactly what happened."
        />
      )}
    </div>
  )
}
