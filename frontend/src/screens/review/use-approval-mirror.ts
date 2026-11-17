/**
 * The console's memory of the approval it last worked on.
 *
 * The screen keeps its working state (the prepared payload, the decision
 * response) in React Query, which a reload empties. The server, though,
 * persists the approval itself: `GET /api/applications/approvals/{id}`
 * returns the stored decision for any id this account owns. What the reload
 * loses is only **which id** to ask about — the route has no `:approvalId`
 * parameter — so this mirror records it in `localStorage`, the same
 * client-side convenience the current-profile id uses (`lib/profile.ts`).
 *
 * The mirror is a pointer, never a source of truth. On load the screen
 * reads the pointer and asks the **server** for the state; the banner it
 * renders is built from the GET response, not from what was cached here.
 * The one field the GET does not carry is the run id (the 202 response's),
 * so the run id travels in the mirror and is labelled as what was recorded
 * at approval time — the run's own truth lives in `/api/runs/{id}` and the
 * Operations screen that reads it.
 *
 * Like the profile id, a private-mode browser or a disabled storage simply
 * loses the pointer: the screen works, it just cannot re-open the last
 * approval after a reload.
 */
const STORAGE_KEY = "aja.lastApproval"

export interface ApprovalMirror {
  /** The approval request the screen last prepared or decided. */
  approval_id: string
  /** The tracked application the prepare created, when it did. */
  application_id: string | null
  /** The run the 202 accepted, recorded from the decision response. */
  run_id: string | null
}

function isString(value: unknown): value is string {
  return typeof value === "string"
}

export function readApprovalMirror(): ApprovalMirror | null {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY)
    if (!raw) return null
    const parsed: unknown = JSON.parse(raw)
    if (typeof parsed !== "object" || parsed === null) return null
    const record = parsed as Record<string, unknown>
    if (!isString(record.approval_id) || !record.approval_id) return null
    return {
      approval_id: record.approval_id,
      application_id: isString(record.application_id)
        ? record.application_id
        : null,
      run_id: isString(record.run_id) ? record.run_id : null,
    }
  } catch {
    // Unreadable storage or a malformed value: the pointer is lost, and the
    // screen falls back to the prepare form. The server's records are intact.
    return null
  }
}

export function writeApprovalMirror(mirror: ApprovalMirror): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(mirror))
  } catch {
    // Storage refused the write; the mirror is a convenience, not a record.
  }
}

export function clearApprovalMirror(): void {
  try {
    window.localStorage.removeItem(STORAGE_KEY)
  } catch {
    // Nothing to recover here either.
  }
}
