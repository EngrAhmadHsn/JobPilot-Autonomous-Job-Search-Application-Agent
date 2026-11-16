import { Link } from "react-router-dom"

import { PlainText } from "@/components/common/plain-text"
import { StatusBadge } from "@/components/ui/status-badge"
import { EmptyState } from "@/components/ui/empty-state"
import { LinkButton } from "@/components/ui/link-button"

/*
  "Your attention" (WS-35) — the screen's answer to "what is my next useful
  action", before anything else on the page competes for it.

  Every row is a real, resolvable thing: an approval waiting for a decision,
  a trail entry a human should read, a question the boards ask that the
  profile does not answer, a missing résumé. Each row links to the screen
  that resolves it — no row is a dead end, and when there is nothing, the
  section says so plainly instead of padding.
*/

/** A summary row: a count of things, and the screen that resolves them. */
export interface AttentionItem {
  key: string
  title: string
  body: string
  to: string
  /** The action's words, on the button at the row's end. */
  label: string
}

/**
 * One awaiting-approval application, shown as its own row.
 *
 * The status renders through the one presentation (`describeStatus`, via
 * `StatusBadge`) — never a screen-local label — and the row links to the
 * application's own tracker page, where its history and evidence live.
 */
export interface AttentionApplication {
  id: string
  jobTitle: string
  company: string
  status: string
}

function ApplicationRow({
  application,
}: {
  application: AttentionApplication
}) {
  return (
    <li>
      <Link
        to={`/app/tracker/${encodeURIComponent(application.id)}`}
        viewTransition
        className="group grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-3 gap-y-1.5 rounded-xl border border-border bg-card px-4 py-3 transition-colors duration-150 hover:bg-muted/60"
      >
        <span className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1.5">
          <StatusBadge status={application.status} />
          <PlainText as="span" className="text-sm font-medium wrap-anywhere">
            {application.jobTitle}
          </PlainText>
          <PlainText
            as="span"
            className="text-sm wrap-anywhere text-muted-foreground"
          >
            {application.company}
          </PlainText>
        </span>
        <span
          aria-hidden="true"
          className="text-muted-foreground transition-colors duration-150 group-hover:text-foreground"
        >
          →
        </span>
      </Link>
    </li>
  )
}

function SummaryRow({ item }: { item: AttentionItem }) {
  return (
    <li className="enter-up flex flex-wrap items-center justify-between gap-3 rounded-xl border border-terracotta/50 bg-terracotta-soft/60 px-4 py-3">
      <div className="max-w-[52ch] min-w-0">
        <p className="text-sm font-medium text-foreground">{item.title}</p>
        <p className="mt-0.5 text-sm text-muted-foreground">{item.body}</p>
      </div>
      <LinkButton to={item.to} variant="outline" size="sm">
        {item.label}
      </LinkButton>
    </li>
  )
}

export function AttentionSection({
  items,
  applications,
}: {
  items: AttentionItem[]
  /** The newest awaiting-approval applications, already cut to a few. */
  applications: AttentionApplication[]
}) {
  if (items.length === 0 && applications.length === 0) {
    return (
      <EmptyState
        title="Nothing needs you right now"
        message="No approvals are waiting and the recent trail is clean. The agent holds anything that would need a decision."
      />
    )
  }

  return (
    <div className="space-y-3">
      {items.length > 0 ? (
        <ul className="space-y-3">
          {items.map((item) => (
            <SummaryRow key={item.key} item={item} />
          ))}
        </ul>
      ) : null}
      {applications.length > 0 ? (
        <ul className="space-y-2">
          {applications.map((application) => (
            <ApplicationRow key={application.id} application={application} />
          ))}
        </ul>
      ) : null}
    </div>
  )
}
