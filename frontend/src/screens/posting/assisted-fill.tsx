import { useEffect, useState } from "react"

import { ErrorNotice } from "@/components/common/error-notice"
import {
  AlertDialog,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog"
import { Button } from "@/components/ui/button"
import { request } from "@/lib/api/client"

/** A grant is short-lived. Keep it out of URLs, browser storage, and the query cache. */
export function AssistedFill({
  applicationId,
  host,
}: {
  applicationId: string
  host: string
}) {
  const [open, setOpen] = useState(false)
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const [grant, setGrant] = useState<{
    code: string
    expires_at: string
  } | null>(null)
  useEffect(() => {
    if (!grant) return
    const timer = window.setTimeout(
      () => setGrant(null),
      Math.min(600_000, Math.max(0, Date.parse(grant.expires_at) - Date.now()))
    )
    return () => window.clearTimeout(timer)
  }, [grant])

  async function authorize() {
    if (pending) return
    setPending(true)
    setError(null)
    try {
      const result = await request<{ code: string; expires_at: string }>(
        `/api/applications/${encodeURIComponent(applicationId)}/authorize-fill`,
        {
          method: "POST",
          json: { purpose: "fill_only" },
        }
      )
      setGrant(result)
      setOpen(false)
    } catch (err) {
      setError(err)
    } finally {
      setPending(false)
    }
  }

  return (
    <div className="min-w-0 space-y-2">
      <Button
        type="button"
        onClick={() => {
          setGrant(null)
          setError(null)
          setOpen(true)
        }}
      >
        Assisted autofill
      </Button>
      <p className="text-sm text-muted-foreground">
        Fill supported fields on this Greenhouse posting with the local JobPilot
        helper. You review and submit.
      </p>
      <AlertDialog
        open={open}
        onOpenChange={(next) => {
          if (!pending) setOpen(next)
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              Allow autofill for this posting?
            </AlertDialogTitle>
            <AlertDialogDescription>
              Authorize the local helper to enter the contact details, résumé
              and answers in this review on {host}. The employer may receive
              information as fields are filled, before you submit. JobPilot will
              not click Submit.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <ErrorNotice error={error} />
          <AlertDialogFooter>
            <AlertDialogCancel disabled={pending}>Cancel</AlertDialogCancel>
            <Button
              type="button"
              disabled={pending}
              onClick={() => void authorize()}
            >
              {pending ? "Authorizing…" : "Authorize fill only"}
            </Button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
      {grant ? (
        <section
          aria-label="Start local autofill"
          className="min-w-0 space-y-2 rounded-lg border border-border-surface bg-card p-4 text-sm"
        >
          <h3 className="font-semibold">Start local autofill</h3>
          <p>
            On the computer running JobPilot, open a terminal in the project
            folder and run:
          </p>
          <code className="block wrap-anywhere">
            .\env\Scripts\python.exe -m scripts.fill_review
          </code>
          <p>
            Paste this private, single-use code at the helper’s hidden prompt.
            It expires in 10 minutes. Keep it out of commands and messages.
          </p>
          <code
            className="block wrap-anywhere select-all"
            aria-label="Single-use code"
          >
            {grant.code}
          </code>
          <p>
            If you cannot use the local helper, open the employer site and
            finish manually.
          </p>
        </section>
      ) : null}
    </div>
  )
}
