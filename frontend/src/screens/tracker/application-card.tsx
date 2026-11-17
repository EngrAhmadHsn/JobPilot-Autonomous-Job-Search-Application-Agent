import { Link } from "react-router-dom"

import { StatusBadge } from "@/components/ui/status-badge"

import { describeStatus } from "@/lib/status"
import { stagger } from "@/lib/stagger"
import type { ApplicationSummary } from "@/lib/api/types"

/*
  One application on the board (WS-39).

  The card keeps what the brief pins: the job, the company, the status, and
  the next action — which is the status vocabulary's own `nextStep` line, so
  the card and the detail screen can never disagree about what has to happen
  next. The line is clamped to two rows because a column is ~200 px wide and
  some next-step lines are sentences; the full line rides in `title`, and
  the detail screen renders it unclamped through `StatusExplainer`.

  The whole card is the link into the application's detail, the same
  whole-row-is-the-target pattern the Discover results use.
*/
export function ApplicationCard({
  application,
  index,
}: {
  application: ApplicationSummary
  index: number
}) {
  const presentation = describeStatus(application.status)

  return (
    <li {...stagger(index)}>
      <Link
        to={`/app/tracker/${encodeURIComponent(application.id)}`}
        className="block rounded-xl border border-border bg-card px-3 py-2.5 shadow-paper transition-colors duration-150 hover:bg-accent/60"
      >
        <span className="block font-heading text-sm font-semibold wrap-anywhere text-foreground underline-offset-4 hover:underline">
          {application.job_title}
        </span>
        <span className="mt-0.5 block text-xs wrap-anywhere text-muted-foreground">
          {application.company_name}
        </span>
        <span className="mt-2 block">
          <StatusBadge status={application.status} />
        </span>
        <span
          title={presentation.nextStep}
          className="mt-2 line-clamp-2 block text-xs leading-relaxed text-muted-foreground"
        >
          {presentation.nextStep}
        </span>
      </Link>
    </li>
  )
}
