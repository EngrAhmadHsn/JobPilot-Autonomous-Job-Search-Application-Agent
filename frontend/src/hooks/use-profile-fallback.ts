import { useQuery } from "@tanstack/react-query"
import { useEffect, useMemo } from "react"

import { useDocuments } from "@/components/documents/document-picker"
import { ApiError } from "@/lib/api/client"
import { api } from "@/lib/api/endpoints"
import { chooseProfile, useCurrentProfileId } from "@/lib/profile"

/**
 * The current profile, with a way out of a stale handle.
 *
 * The console keeps the profile id in `localStorage`, and a handle can go
 * stale: it was written by another account, or the profile has been removed.
 * The server answers 404, and the honest response is **not** an error
 * banner — the account's own documents are right there, newest first. So the
 * rule lives in one place: when the remembered profile cannot be read, the
 * console works with the most recent document the account does have, and
 * says which one it chose.
 *
 * The resolution is **derived**, not stored: the effective id is a pure
 * function of what the server said and what the account has, so a stale
 * handle cannot leave the screen on a broken profile for even one render.
 * The only write is the external-store sync below, which corrects the handle
 * for the other screens — which also means the substitution is not announced
 * by a transient banner: the resume screen marks the document it is reading
 * ("In use"), and that mark stays.
 */
export function useProfileWithFallback() {
  const storedId = useCurrentProfileId()
  const documents = useDocuments()

  const stored = useQuery({
    queryKey: ["profile", storedId],
    queryFn: ({ signal }) => api.getResume(storedId as string, signal),
    enabled: Boolean(storedId),
    retry: false,
  })

  const missing =
    stored.error instanceof ApiError && stored.error.status === 404

  const documents_ = documents.data?.documents
  const fallback = useMemo(() => {
    if (!missing || !documents_) return null
    return (
      documents_.find((item) => item.kind === "resume" && item.profile_id) ??
      documents_.find((item) => item.profile_id) ??
      null
    )
  }, [missing, documents_])

  const effectiveId = missing ? (fallback?.profile_id ?? null) : storedId

  /*
    The substitute profile has its own query: the stale id already failed, so
    it cannot be the one that supplies the facts. When the handle is fine the
    two ids are the same and React Query serves one request.
  */
  const resolved = useQuery({
    queryKey: ["profile", effectiveId],
    queryFn: ({ signal }) => api.getResume(effectiveId as string, signal),
    enabled: Boolean(effectiveId),
    retry: false,
  })

  /*
    Correct the remembered handle so the screens that resolve it themselves
    (the shell's profile chip, the approvals form) agree with this one. It is
    idempotent — the guard compares before writing — and it writes to the
    store, not to React state.
  */
  useEffect(() => {
    if (!missing) return
    /*
      Do not decide before the library is known. The profile check can fail
      before the documents arrive, and clearing the handle then would throw
      away the very fallback this hook exists to find: the account would be
      left on the upload prompt with résumés sitting in the library.
    */
    if (!documents.isSuccess) return
    const next = fallback?.profile_id ?? null
    if (next !== storedId) chooseProfile(next)
  }, [missing, fallback, storedId, documents.isSuccess])

  return {
    /** The profile the console is working with (already corrected). */
    profileId: effectiveId,
    /** The profile query, for the screens that render the facts. */
    profile: resolved,
    /** True when the remembered handle could not be read. */
    missing,
    /**
     * The document the console adopted, while the remembered handle was
     * stale. A screen may use it to explain the substitution; it clears as
     * soon as the handle is corrected.
     */
    switchedTo: fallback,
    /** The account's documents (the same query the library uses). */
    documents,
  }
}
