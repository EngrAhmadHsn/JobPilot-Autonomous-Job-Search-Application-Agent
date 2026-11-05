import { useQuery } from "@tanstack/react-query"
import { useEffect, useState } from "react"

import { EmptyState } from "@/components/common/progress-state"
import { ErrorNotice } from "@/components/common/error-notice"
import { PageHeader, Section } from "@/components/common/page-header"
import { StatTile } from "@/components/common/stat-tile"
import { EventList } from "@/components/observability/event-timeline"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { LinkButton } from "@/components/ui/link-button"

import { api } from "@/lib/api/endpoints"
import { formatRelativeTime, summarizeEvents } from "@/lib/observability"
import { useCurrentProfileId } from "@/lib/profile"

/**
 * The overview.
 *
 * The first screen a signed-in operator sees, and the honest answer to
 * "what is going on?". Every number here is counted from data the server
 * actually returned — the tracked applications and the account's own audit
 * trail — and the screen says when that data was read rather than
 * implying it is live. There is no streaming endpoint (see the activity
 * screen's note), so this refetches on an interval and is explicit about
 * it.
 */
export function OverviewScreen() {
  const profileId = useCurrentProfileId()

  const applications = useQuery({
    queryKey: ["applications", "overview"],
    queryFn: ({ signal }) => api.listApplications({ limit: 200 }, signal),
    refetchInterval: 30_000,
  })

  const audit = useQuery({
    queryKey: ["audit", "overview"],
    queryFn: ({ signal }) => api.audit(signal),
    refetchInterval: 30_000,
  })

  const documents = useQuery({
    queryKey: ["documents"],
    queryFn: ({ signal }) => api.documents(signal),
  })

  // A ticking clock so "data read N ago" actually ages between refetches.
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 15_000)
    return () => window.clearInterval(timer)
  }, [])

  const items = applications.data?.items ?? []
  const events = audit.data?.events ?? []
  const summary = summarizeEvents(events)

  const awaiting = items.filter((item) =>
    ["prepared", "awaiting_approval"].includes(item.status)
  ).length
  const verified = items.filter((item) => item.status === "verified").length
  const failed = items.filter(
    (item) => item.status === "rejected" || item.status === "withdrawn"
  ).length

  const lastRead = Math.max(
    applications.dataUpdatedAt,
    audit.dataUpdatedAt,
    documents.dataUpdatedAt,
    0
  )

  // The things a human has to deal with, in the order they cost the most
  // to ignore. Each one links to the screen that resolves it.
  const nextActions: { title: string; body: string; to: string; label: string }[] = []
  if (!profileId) {
    // The console works against a chosen profile. If the account already
    // has documents, the honest ask is "choose one", not "upload one".
    const hasDocuments = (documents.data?.count ?? 0) > 0
    nextActions.push({
      title: hasDocuments ? "Choose a résumé to work from" : "Upload a résumé",
      body: hasDocuments
        ? "This account already has documents. Pick the one the agent should work from, so matches and tailoring have a profile."
        : "There is no candidate profile yet, so the agent has nothing to match against.",
      to: "/app/resume",
      label: hasDocuments ? "Choose a document" : "Go to Resume",
    })
  }
  if (awaiting > 0) {
    nextActions.push({
      title: `${awaiting} application${awaiting === 1 ? "" : "s"} awaiting your approval`,
      body: "Prepared applications are held until a person approves or rejects them.",
      to: "/app/approvals",
      label: "Review approvals",
    })
  }
  if (summary.attention > 0) {
    nextActions.push({
      title: `${summary.attention} event${summary.attention === 1 ? "" : "s"} need attention`,
      body: "The audit trail recorded a refusal, a block or a failure that a human should read.",
      to: "/app/activity",
      label: "Open activity",
    })
  }
  if (failed > 0) {
    nextActions.push({
      title: `${failed} application${failed === 1 ? "" : "s"} closed without a result`,
      body: "Rejected or withdrawn applications are final; the history explains each one.",
      to: "/app/tracker",
      label: "Open the tracker",
    })
  }

  return (
    <div className="space-y-8">
      <PageHeader
        title="Overview"
        description="What the agent has done, what is waiting on you, and what needs a look. Every figure is counted from this account's own records."
        actions={
          <span className="text-xs text-muted-foreground">
            Data read{" "}
            {formatRelativeTime(lastRead ? new Date(lastRead).toISOString() : null, now)} ·
            refreshes every 30s
          </span>
        }
      />

      {applications.isError ? <ErrorNotice error={applications.error} /> : null}
      {audit.isError ? <ErrorNotice error={audit.error} /> : null}

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <StatTile
          label="Tracked applications"
          value={items.length}
          hint="Every application this account is following"
        />
        <StatTile
          label="Awaiting your approval"
          value={awaiting}
          tone="human"
          hint="Prepared, held for a human decision"
        />
        <StatTile
          label="Verified submissions"
          value={verified}
          tone="agent"
          hint="Confirmed by evidence"
        />
        <StatTile
          label="Recorded actions"
          value={summary.total}
          hint="Agent and human steps in the audit trail"
        />
      </div>

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)]">
        <Section
          title="Next actions"
          description="What is waiting on you, before anything else."
        >
          {nextActions.length === 0 ? (
            <EmptyState
              title="Nothing needs you"
              description="No approvals are pending and the recent trail is clean. The agent will hold anything that needs a decision."
            />
          ) : (
            <ul className="space-y-3">
              {nextActions.map((action) => (
                <li
                  key={action.title}
                  className="enter-up flex flex-wrap items-center justify-between gap-3 rounded-xl border border-terracotta/50 bg-terracotta-soft/60 px-4 py-3"
                >
                  <div className="min-w-0">
                    <p className="text-sm font-medium text-foreground">
                      {action.title}
                    </p>
                    <p className="mt-0.5 text-sm text-muted-foreground">
                      {action.body}
                    </p>
                  </div>
                  <LinkButton to={action.to} variant="outline" size="sm">
                    {action.label}
                  </LinkButton>
                </li>
              ))}
            </ul>
          )}
        </Section>

        <Section
          title="At a glance"
          description="The two questions an operator asks first."
        >
          <div className="space-y-3">
            <Card>
              <CardHeader>
                <CardTitle>Activity by actor</CardTitle>
              </CardHeader>
              <CardContent className="grid grid-cols-3 gap-3 text-center">
                <ActorCount label="Agent" value={summary.agent} tone="agent" />
                <ActorCount label="People" value={summary.human} tone="human" />
                <ActorCount
                  label="Needs attention"
                  value={summary.attention}
                  tone="attention"
                />
              </CardContent>
            </Card>
            <Card>
              <CardHeader>
                <CardTitle>Library</CardTitle>
              </CardHeader>
              <CardContent className="space-y-1 text-sm text-muted-foreground">
                <p>
                  {documents.data?.count ?? "—"} document
                  {(documents.data?.count ?? 0) === 1 ? "" : "s"} — uploaded and
                  tailored résumés.
                </p>
                {profileId ? (
                  <p>
                    Working with profile{" "}
                    <code className="font-mono text-xs text-foreground">
                      {profileId}
                    </code>
                  </p>
                ) : (
                  <p>No profile selected yet.</p>
                )}
              </CardContent>
            </Card>
          </div>
        </Section>
      </div>

      <Section
        title="Recent agent activity"
        description="The newest entries in this account's audit trail."
        action={
          <LinkButton to="/app/activity" variant="ghost" size="sm">
            See the full trail
          </LinkButton>
        }
      >
        {audit.isPending ? (
          <p className="text-sm text-muted-foreground">Reading the trail...</p>
        ) : events.length === 0 ? (
          <EmptyState
            title="No recorded activity yet"
            description="Upload a résumé or run a search, and the agent's steps will appear here."
          />
        ) : (
          <Card>
            <CardContent>
              <EventList events={events.slice(0, 6)} />
            </CardContent>
          </Card>
        )}
      </Section>
    </div>
  )
}

function ActorCount({
  label,
  value,
  tone,
}: {
  label: string
  value: number
  tone: "agent" | "human" | "attention"
}) {
  const toneClass =
    tone === "agent"
      ? "text-lime-foreground"
      : tone === "human"
        ? "text-terracotta-foreground"
        : "text-destructive"
  return (
    <div>
      <p className={`font-heading text-xl font-semibold ${toneClass}`}>{value}</p>
      <p className="text-xs text-muted-foreground">{label}</p>
    </div>
  )
}
