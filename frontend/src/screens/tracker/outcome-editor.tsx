import { useMutation, useQueryClient } from "@tanstack/react-query"
import { useState } from "react"

import { Banner } from "@/components/common/banner"
import { ErrorNotice } from "@/components/common/error-notice"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"

import { api } from "@/lib/api/endpoints"
import { describeStatus, HUMAN_OUTCOME_STATUS_NAMES } from "@/lib/status"
import type { ApplicationDetail } from "@/lib/api/types"

/*
  The statuses that close an application. The backend's transition matrix
  gives `rejected` and `withdrawn` **no outgoing transitions**
  (`src/applications/tracking.py:118-120`), so once an application rests in
  one of them every PATCH is a guaranteed 409 — the console does not offer a
  form that can only fail, and says why the form is not here instead.
*/
const CLOSED_STATUSES = ["rejected", "withdrawn"]

/*
  The human outcome editor (WS-39).

  The form sends `status` and an optional `note` — and **nothing else**. The
  backend accepts an `actor` field but ignores it (WS-14): the actor is the
  authenticated principal, recorded server-side as `human:<user id>`. The
  console does not collect an actor name, because a name typed into a form
  would be a value the server throws away while the operator believes it was
  recorded. The agent may not decide that an employer made an offer, and the
  console offers no way to pretend otherwise.

  Only the four human outcomes are offered (`HUMAN_OUTCOME_STATUS_NAMES`) —
  the same four the backend's actor rule reserves for a human. Agent-side
  states (submitted, verified, …) are the agent's to set, and no human form
  sets them. On a closed application (rejected, withdrawn) the editor is
  absent outright: the state is final, the server would refuse every move,
  and the timeline is the record.
*/
export function OutcomeEditor({
  application,
}: {
  application: ApplicationDetail
}) {
  const queryClient = useQueryClient()
  const [outcome, setOutcome] = useState<string>(HUMAN_OUTCOME_STATUS_NAMES[0])
  const [notes, setNotes] = useState("")

  const update = useMutation({
    mutationFn: (values: { status: string; notes?: string }) =>
      api.updateApplicationStatus(application.id, values),
    onSuccess: () => {
      // The PATCH answers with the full updated detail; the invalidation
      // re-reads it through the same query key the detail screen holds, so
      // the status, the fields and the timeline all move together.
      void queryClient.invalidateQueries({
        queryKey: ["application", application.id],
      })
    },
  })

  const closed = CLOSED_STATUSES.includes(application.status)

  return (
    <Card>
      <CardHeader>
        <CardTitle>
          {closed ? "The outcome is final" : "Record a human outcome"}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {closed ? (
          <Banner tone="neutral" title="This application is closed">
            <p>
              The application is{" "}
              <span className="font-medium">
                {describeStatus(application.status).label}
              </span>
              , and no status can follow a closed one. The timeline above is the
              record, and it is the server&apos;s.
            </p>
          </Banner>
        ) : (
          <>
            <Banner
              tone="neutral"
              title="A human outcome is recorded by a human"
            >
              <p>
                The agent prepares, submits and verifies. It never decides that
                an employer made an offer. The outcome is recorded against your
                account, so it is attributable to a person and to nobody else.
              </p>
            </Banner>

            <form
              className="grid gap-3 sm:grid-cols-[1fr_2fr_auto] sm:items-end"
              onSubmit={(event) => {
                event.preventDefault()
                update.mutate({
                  status: outcome,
                  notes: notes.trim() ? notes.trim() : undefined,
                })
              }}
            >
              <label className="space-y-1">
                <span className="text-sm font-medium">Outcome</span>
                <select
                  className="h-8 w-full rounded-lg border border-input bg-transparent px-2 text-sm"
                  value={outcome}
                  onChange={(event) => setOutcome(event.target.value)}
                >
                  {HUMAN_OUTCOME_STATUS_NAMES.map((status) => (
                    <option key={status} value={status}>
                      {describeStatus(status).label}
                    </option>
                  ))}
                </select>
              </label>
              <label className="space-y-1">
                <span className="text-sm font-medium">Note (optional)</span>
                <Input
                  value={notes}
                  onChange={(event) => setNotes(event.target.value)}
                />
              </label>
              <Button type="submit" disabled={update.isPending}>
                {update.isPending ? "Recording…" : "Record the outcome"}
              </Button>
            </form>

            {update.isError ? <ErrorNotice error={update.error} /> : null}

            {update.isSuccess ? (
              <Banner tone="success" title="The outcome was recorded">
                <p>
                  The application is now{" "}
                  <span className="font-medium">
                    {describeStatus(update.data.status).label}
                  </span>
                  . The history above is the server&apos;s.
                </p>
              </Banner>
            ) : null}
          </>
        )}
      </CardContent>
    </Card>
  )
}
