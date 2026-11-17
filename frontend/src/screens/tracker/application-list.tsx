import { useQuery } from "@tanstack/react-query"
import { InboxIcon } from "lucide-react"
import { useState } from "react"
import { Link } from "react-router-dom"

import { ErrorNotice } from "@/components/common/error-notice"
import { ProgressState } from "@/components/common/progress-state"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { EmptyState } from "@/components/ui/empty-state"
import { StatusBadge } from "@/components/ui/status-badge"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"

import { api } from "@/lib/api/endpoints"
import { stagger } from "@/lib/stagger"
import { formatDateTime, pluralize } from "@/lib/format"
import { APPLICATION_STATUS_NAMES, describeStatus } from "@/lib/status"
import type { ApplicationList } from "@/lib/api/types"

const PAGE_SIZE = 10

/*
  The Tracker's List view (WS-39).

  The list is the backend's, filtered and paged by the backend's own
  parameters — the console does not filter a page of results on its own,
  because a page that says "3 of 400" has to be the server's count.

  The status chips are **single-select**. The backend honours one `status`
  parameter and silently ignores the rest (`src/api/routes/tracking.py:
  220-221` returns the *unfiltered* list for a multi-status call), so a row
  of multi-toggle chips would look filtered while showing everything. One
  chip or none: what the filter claims is what the server does.
*/
export function ApplicationList({
  statusFilter,
  onStatusFilterChange,
}: {
  /** The one status the server filters by, or null for every application. */
  statusFilter: string | null
  onStatusFilterChange: (status: string | null) => void
}) {
  const [offset, setOffset] = useState(0)

  const applications = useQuery({
    queryKey: ["applications", "list", statusFilter, offset],
    queryFn: ({ signal }) =>
      api.listApplications(
        {
          status: statusFilter ? [statusFilter] : undefined,
          limit: PAGE_SIZE,
          offset,
        },
        signal
      ),
  })

  const total = applications.data?.total ?? 0
  const items: ApplicationList["items"] = applications.data?.items ?? []

  return (
    <Card>
      <CardHeader>
        <CardTitle>Tracked applications</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div
          role="group"
          aria-label="Filter by status"
          className="flex flex-wrap gap-2"
        >
          <button
            type="button"
            aria-pressed={statusFilter === null}
            onClick={() => onStatusFilterChange(null)}
            className={
              statusFilter === null
                ? "rounded-full border border-primary bg-primary px-3 py-1 text-xs font-medium text-primary-foreground"
                : "rounded-full border border-border px-3 py-1 text-xs font-medium text-muted-foreground hover:bg-muted"
            }
          >
            All statuses
          </button>
          {APPLICATION_STATUS_NAMES.map((status) => {
            const presentation = describeStatus(status)
            const active = statusFilter === status
            return (
              <button
                key={status}
                type="button"
                aria-pressed={active}
                onClick={() => onStatusFilterChange(active ? null : status)}
                title={presentation.nextStep}
                className={
                  active
                    ? "rounded-full border border-primary bg-primary px-3 py-1 text-xs font-medium text-primary-foreground"
                    : "rounded-full border border-border px-3 py-1 text-xs font-medium text-muted-foreground hover:bg-muted"
                }
              >
                {presentation.label}
              </button>
            )
          })}
        </div>

        {applications.isPending ? (
          <ProgressState key="applications" title="Loading the applications" />
        ) : null}

        {applications.isError ? (
          <ErrorNotice
            error={applications.error}
            onRetry={() => applications.refetch()}
          />
        ) : null}

        {applications.data ? (
          <>
            <p className="text-sm text-muted-foreground">
              {pluralize(total, "application")} · showing {offset + 1}–
              {Math.min(offset + PAGE_SIZE, total)}
              {statusFilter ? (
                <>
                  {" "}
                  with the status{" "}
                  <span className="font-medium text-foreground">
                    {describeStatus(statusFilter).label}
                  </span>
                </>
              ) : null}
            </p>

            {items.length === 0 ? (
              <EmptyState
                icon={InboxIcon}
                title="Nothing tracked yet"
                message="An application appears here once it has been prepared through the Review screen — prepare-only, until a person decides."
              />
            ) : (
              <Table>
                {/*
                  Five columns, all `whitespace-nowrap`, in a ~295 px card is
                  a horizontal-scroll island where the identifying column
                  scrolls out of view — and the only way into a record is
                  the Job link in that column.

                  So the table gets shorter rather than wider below `md`.
                  The two timestamps are already shown in full on the record
                  screen this table links to (`tracker/:id`), which is the
                  "short view that links deeper" the layout rules ask for;
                  nothing is lost, and the Job and Company columns carry the
                  identity. The `hidden md:table-cell` pairs on head and
                  body keep the header and the cells in step at both widths.
                */}
                <TableHeader>
                  <TableRow>
                    <TableHead>Job</TableHead>
                    <TableHead>Company</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead className="hidden md:table-cell">
                      Created
                    </TableHead>
                    <TableHead className="hidden md:table-cell">
                      Submitted
                    </TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {items.map((application, index) => (
                    <TableRow key={application.id} {...stagger(index)}>
                      <TableCell className="whitespace-normal">
                        <Link
                          to={`/app/tracker/${encodeURIComponent(application.id)}`}
                          className="font-medium wrap-anywhere underline-offset-4 hover:underline"
                        >
                          {application.job_title}
                        </Link>
                      </TableCell>
                      <TableCell className="whitespace-normal">
                        {application.company_name}
                      </TableCell>
                      <TableCell>
                        <StatusBadge status={application.status} />
                      </TableCell>
                      <TableCell className="hidden md:table-cell">
                        {formatDateTime(application.created_at)}
                      </TableCell>
                      <TableCell className="hidden md:table-cell">
                        {formatDateTime(application.submitted_at)}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}

            <div className="flex items-center justify-between gap-2">
              <Button
                type="button"
                variant="outline"
                size="sm"
                disabled={offset === 0}
                onClick={() =>
                  setOffset((value) => Math.max(0, value - PAGE_SIZE))
                }
              >
                Previous
              </Button>
              <span className="text-xs text-muted-foreground">
                {total === 0
                  ? "nothing"
                  : `${offset + 1}–${Math.min(offset + PAGE_SIZE, total)}`}{" "}
                of {total}
              </span>
              <Button
                type="button"
                variant="outline"
                size="sm"
                disabled={offset + PAGE_SIZE >= total}
                onClick={() => setOffset((value) => value + PAGE_SIZE)}
              >
                Next
              </Button>
            </div>
          </>
        ) : null}
      </CardContent>
    </Card>
  )
}
