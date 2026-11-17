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

/**
 * The confirmation the decision gets before it is recorded.
 *
 * The approve dialog states the **queued consequence** in the operator's
 * own terms: approving records the decision and queues durable work — the
 * submission happens on a worker, later, and the stored payload the operator
 * just reviewed is what the run executes. That sentence is the audit fix's
 * second half: the button no longer says "Approve and submit" (the route
 * answers 202, not a submission), and the confirmation carries the truth the
 * old copy hid.
 *
 * The dialog is controlled, and it stays open while the decision request is
 * in flight: the confirming button is disabled and labelled "Queuing…"/
 * "Recording…", so a double-click cannot send two decisions, and Escape
 * cannot dismiss the dialog while a decision is being written (the server's
 * 409 on an already-decided approval remains the authority).
 */
export function DecideDialog({
  action,
  jobLabel,
  jobUrl,
  pending,
  onAction,
  onDismiss,
}: {
  /** Which decision is being confirmed; null closes the dialog. */
  action: "approve" | "reject" | null
  /** "Title at Company" — the application the decision is about. */
  jobLabel: string
  /** The stored payload's target URL, so the confirm names where it goes. */
  jobUrl: string
  /** True while the decision request is in flight. */
  pending: boolean
  /** Runs the decision (the caller validates its own form first). */
  onAction: () => void
  /** Dismisses the dialog; ignored by the caller while pending. */
  onDismiss: () => void
}) {
  return (
    <AlertDialog
      open={action !== null}
      onOpenChange={(open) => {
        if (!open && !pending) onDismiss()
      }}
    >
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>
            {action === "approve"
              ? "Approve this application?"
              : "Reject this application?"}
          </AlertDialogTitle>
          <AlertDialogDescription>
            {action === "approve" ? (
              <>
                Approving records your decision on {jobLabel} and queues the
                submission as durable work against{" "}
                <span className="font-mono text-[11px] wrap-anywhere">
                  {jobUrl}
                </span>
                . A background worker performs the run — nothing is submitted by
                this click, and nothing claims it was. The stored payload you
                reviewed is exactly what the run executes, and the decision
                cannot be taken back once recorded. The run's id appears when
                the queue accepts the work.
              </>
            ) : (
              <>
                Rejecting records your decision on {jobLabel}. Nothing is
                submitted and nothing is queued. The decision, its reason and
                the time are kept with the approval record.
              </>
            )}
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel disabled={pending}>Cancel</AlertDialogCancel>
          <Button
            onClick={onAction}
            disabled={pending}
            variant={action === "reject" ? "outline" : "default"}
          >
            {pending
              ? action === "approve"
                ? "Queuing…"
                : "Recording…"
              : action === "approve"
                ? "Approve & continue"
                : "Reject"}
          </Button>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}
