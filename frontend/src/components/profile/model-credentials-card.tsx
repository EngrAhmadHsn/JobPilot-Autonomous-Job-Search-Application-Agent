import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useState } from "react"

import { Banner } from "@/components/common/banner"
import { ErrorNotice } from "@/components/common/error-notice"
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader } from "@/components/ui/card"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { ApiError } from "@/lib/api/client"
import { api } from "@/lib/api/endpoints"
import type {
  LlmCredentialInput,
  LlmCredentialStatus,
  LlmCredentialTestResult,
  LlmCredentialUpdate,
} from "@/lib/api/types"

/**
 * Model connections — bring your own keys (WS-22; several at once).
 *
 * An account may store **more than one** provider key and choose which one
 * its tailoring and research calls spend. The rules this card is built
 * around:
 *
 * 1. **The key is write-only.** The read returns a mask (the last four
 *    characters). A key field is never re-rendered from server data — the
 *    server does not have the key to send — so it starts empty, and an
 *    omitted key on an edit *keeps* the stored one.
 * 2. **Saving is not switching.** Adding or editing a connection never
 *    changes which key a job spends; "Make active" is its own button, and
 *    removing the active one hands over to the next in the server's order.
 * 3. **Saving does not spend.** Proving a key works is a separate, billable
 *    provider call, so it is never run implicitly.
 * 4. **Server error text is never displayed.** A failure on this form may
 *    quote the key back, so the card shows its own words for every refusal
 *    and keeps the server's out of the DOM, the cache and the console.
 */

const labelClass = "text-xs font-medium text-muted-foreground"
const fieldClass = "space-y-1"

const PROVIDERS = [
  { value: "google", label: "Google Gemini" },
  { value: "openai-compatible", label: "OpenAI-compatible endpoint" },
  { value: "openai", label: "OpenAI (default endpoint)" },
  { value: "zai", label: "Z.ai GLM (default endpoint)" },
  // WS-30: the same three providers the platform's fallback chain uses. Each
  // carries its vendor endpoint, so a key and a model are all that is needed.
  { value: "groq", label: "Groq (default endpoint)" },
  { value: "tokenharbor", label: "TokenHarbor (default endpoint)" },
  { value: "pollinations", label: "Pollinations (default endpoint)" },
] as const

const PROVIDER_LABELS = new Map(
  PROVIDERS.map((entry) => [entry.value, entry.label])
)

/** Providers whose base URL the user must supply. */
const NEEDS_BASE_URL: Set<string> = new Set(["openai-compatible"])
/** Providers that may carry a base URL (a regional endpoint, a proxy). */
const MAY_HAVE_BASE_URL: Set<string> = new Set(
  PROVIDERS.map((entry) => entry.value)
)

const maskingKey = (hint: string): string => `${"•".repeat(8)}${hint}`

const providerLabel = (provider: string): string =>
  PROVIDER_LABELS.get(provider as (typeof PROVIDERS)[number]["value"]) ??
  provider

/**
 * A save failure, in our words.
 *
 * The server's own detail is deliberately dropped: this form sends an API
 * key, and a server that echoes the request back would put that key in the
 * DOM and in the query cache. The copy is chosen from the *request* instead —
 * whether it carried a key — so the message is still specific enough to act
 * on.
 */
class CredentialError extends Error {
  readonly status: number | null

  constructor(message: string, status: number | null = null) {
    super(message)
    this.name = "CredentialError"
    this.status = status
  }
}

function credentialError(error: unknown, sentKey: boolean): Error {
  if (error instanceof ApiError) {
    if (error.status === 422) {
      return new CredentialError(
        sentKey
          ? "The provider or the endpoint refused that key. Check the provider, the model and the URL, then try again."
          : "Changing the provider or the endpoint requires a new API key. Paste the key to save this change.",
        422
      )
    }
    if (error.status === 403) {
      return new CredentialError(
        "This deployment has disabled personal model keys.",
        403
      )
    }
    if (error.status === 503) {
      return new CredentialError(
        "This deployment cannot store keys: it has no encryption key material configured.",
        503
      )
    }
    if (error.status === 404) {
      return new CredentialError(
        "That saved connection no longer exists. The list has been refreshed.",
        404
      )
    }
    return new CredentialError(
      `The change could not be saved (HTTP ${error.status}). Try again.`,
      error.status
    )
  }
  return error instanceof Error
    ? error
    : new CredentialError("The change could not be saved.")
}

interface Draft {
  provider: string
  model: string
  apiKey: string
  baseUrl: string
}

const emptyDraft = (provider = "google"): Draft => ({
  provider,
  model: "",
  apiKey: "",
  baseUrl: "",
})

/** The add-form body: every field, with the vendor's endpoint left implicit. */
function addBody(draft: Draft): LlmCredentialInput {
  return {
    provider: draft.provider,
    model: draft.model.trim(),
    base_url: MAY_HAVE_BASE_URL.has(draft.provider)
      ? draft.baseUrl.trim() || null
      : null,
    api_key: draft.apiKey.trim(),
  }
}

/**
 * The edit-form body: **only what changed**.
 *
 * Sending the whole row would re-write fields the user did not touch, and an
 * unchanged `api_key` can only be sent as itself — which the user does not
 * have. So the body is a diff, and an untouched key is simply absent.
 */
function editChanges(row: LlmCredentialStatus, draft: Draft): LlmCredentialUpdate {
  const changes: LlmCredentialUpdate = {}
  if (draft.provider !== row.provider) changes.provider = draft.provider
  const model = draft.model.trim()
  if (model !== row.model) changes.model = model
  const baseUrl = draft.baseUrl.trim() || null
  if (baseUrl !== (row.base_url ?? null)) changes.base_url = baseUrl
  const key = draft.apiKey.trim()
  if (key) changes.api_key = key
  return changes
}

function ConnectionEditor({
  title,
  description,
  submitLabel,
  draft,
  onDraft,
  onSubmit,
  onCancel,
  pending,
  error,
  disabledHint,
}: {
  title: string
  description: string
  submitLabel: string
  draft: Draft
  onDraft: (next: Draft) => void
  onSubmit: () => void
  onCancel: () => void
  pending: boolean
  error: Error | null
  disabledHint: string | null
}) {
  return (
    <>
      <DialogHeader>
        <DialogTitle>{title}</DialogTitle>
        <DialogDescription>{description}</DialogDescription>
      </DialogHeader>

      <div className="grid gap-4 sm:grid-cols-2">
        <div className={fieldClass}>
          <label className={labelClass} htmlFor="credential-provider">
            Provider
          </label>
          <select
            id="credential-provider"
            className="h-9 w-full rounded-md border border-input bg-transparent px-3 text-sm"
            value={draft.provider}
            onChange={(event) => onDraft({ ...draft, provider: event.target.value })}
          >
            {PROVIDERS.map((entry) => (
              <option key={entry.value} value={entry.value}>
                {entry.label}
              </option>
            ))}
          </select>
        </div>

        <div className={fieldClass}>
          <label className={labelClass} htmlFor="credential-model">
            Model
          </label>
          <Input
            id="credential-model"
            value={draft.model}
            onChange={(event) => onDraft({ ...draft, model: event.target.value })}
          />
        </div>

        <div className={fieldClass}>
          <label className={labelClass} htmlFor="credential-api-key">
            Provider API key
          </label>
          <Input
            id="credential-api-key"
            type="password"
            autoComplete="off"
            placeholder="Paste the key securely"
            value={draft.apiKey}
            onChange={(event) => onDraft({ ...draft, apiKey: event.target.value })}
          />
          <span className="block text-xs text-muted-foreground">
            Leave blank to keep the stored key. It is encrypted at rest and
            never shown again — not in a response, a log or the audit trail.
          </span>
        </div>

        {MAY_HAVE_BASE_URL.has(draft.provider) ? (
          <div className={fieldClass}>
            <label className={labelClass} htmlFor="credential-base-url">
              Base URL {NEEDS_BASE_URL.has(draft.provider) ? "" : "(optional)"}
            </label>
            <Input
              id="credential-base-url"
              placeholder="https://api.z.ai/api/paas/v4"
              value={draft.baseUrl}
              onChange={(event) => onDraft({ ...draft, baseUrl: event.target.value })}
            />
            {!NEEDS_BASE_URL.has(draft.provider) ? (
              <span className="block text-xs text-muted-foreground">
                Leave empty to use this provider's default endpoint.
              </span>
            ) : null}
          </div>
        ) : null}
      </div>

      {disabledHint ? (
        <p className="text-xs leading-relaxed text-muted-foreground">
          {disabledHint}
        </p>
      ) : null}

      {/* Our own words, never the server's — see `credentialError`. */}
      {error ? (
        <Banner tone="danger" title="The key was not saved">
          <p>{error.message}</p>
        </Banner>
      ) : null}

      <DialogFooter>
        <Button variant="outline" onClick={onCancel} disabled={pending}>
          Cancel
        </Button>
        <Button onClick={onSubmit} disabled={pending || disabledHint !== null}>
          {pending ? "Saving..." : submitLabel}
        </Button>
      </DialogFooter>
    </>
  )
}

export function ModelCredentialsCard() {
  const queryClient = useQueryClient()
  const state = useQuery({
    queryKey: ["llm-credentials"],
    queryFn: ({ signal }) => api.getLlmCredentials(signal),
    staleTime: 15_000,
  })

  const [addOpen, setAddOpen] = useState(false)
  const [addDraft, setAddDraft] = useState<Draft>(() => emptyDraft())
  const [editing, setEditing] = useState<LlmCredentialStatus | null>(null)
  const [editDraft, setEditDraft] = useState<Draft>(() => emptyDraft())
  const [removing, setRemoving] = useState<LlmCredentialStatus | null>(null)
  const [testingId, setTestingId] = useState<string | null>(null)
  const [testResults, setTestResults] = useState<
    Record<string, LlmCredentialTestResult>
  >({})

  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: ["llm-credentials"] })

  /*
    The mutation functions take **no variables**. React Query stores a
    mutation's variables in its cache, and the variables here would be the
    form body — which contains the key. Reading the draft from state instead
    keeps the secret out of the cache entirely.
  */
  const add = useMutation({
    mutationFn: async () => {
      const body = addBody(addDraft)
      try {
        return await api.createLlmCredential(body)
      } catch (error) {
        throw credentialError(error, Boolean(body.api_key))
      }
    },
    onSuccess: () => {
      setAddDraft(emptyDraft())
      setAddOpen(false)
      void invalidate()
    },
    onError: () => {
      // A refused key must not stay in the field: the response may have
      // echoed it, and either way the operator should paste it again after
      // fixing whatever was refused.
      setAddDraft((previous) => ({ ...previous, apiKey: "" }))
    },
  })

  const edit = useMutation({
    mutationFn: async () => {
      if (!editing) throw new CredentialError("No connection is being edited.")
      const changes = editChanges(editing, editDraft)
      try {
        return await api.patchLlmCredential(editing.id, changes)
      } catch (error) {
        throw credentialError(error, "api_key" in changes)
      }
    },
    onSuccess: () => {
      setEditing(null)
      setEditDraft(emptyDraft())
      void invalidate()
    },
    onError: () => {
      setEditDraft((previous) => ({ ...previous, apiKey: "" }))
    },
  })

  const remove = useMutation({
    mutationFn: (id: string) => api.deleteLlmCredential(id),
    onSuccess: () => {
      setRemoving(null)
      void invalidate()
    },
  })

  const activate = useMutation({
    mutationFn: (id: string) => api.activateLlmCredential(id),
    onSuccess: () => {
      void invalidate()
    },
  })

  const test = useMutation({
    mutationFn: (id: string) => api.testLlmCredential(id),
    onMutate: (id: string) => {
      setTestingId(id)
      setTestResults((previous) => {
        const next = { ...previous }
        delete next[id]
        return next
      })
    },
    onSuccess: (result, id) => {
      setTestResults((previous) => ({ ...previous, [id]: result }))
    },
    onSettled: () => {
      setTestingId(null)
    },
  })

  const loading = state.isPending
  const connections: LlmCredentialStatus[] | null = Array.isArray(
    state.data?.credentials
  )
    ? state.data.credentials
    : null

  const using = state.data?.using ?? "none"
  const mode = state.data?.mode ?? "optional"
  const canWrite = Boolean(state.data?.available) && mode !== "disabled"
  const activeId = state.data?.credential?.id ?? null
  const isActive = (id: string) => using === "user" && id === activeId

  const summaryTitle =
    using === "user"
      ? "Your key is in use"
      : mode === "required"
        ? "This deployment requires your own key"
        : using === "platform"
          ? "Using the deployment's key"
          : "No model key is in use"

  const policyNotice =
    mode === "disabled"
      ? "Personal keys are disabled on this deployment. Existing connections can be removed, but nothing will spend them."
      : "This deployment cannot store keys: it has no encryption key material configured. Existing connections can be removed."

  return (
    <Card>
      <CardHeader className="space-y-2">
        <h2 className="text-[20px] leading-[29px] font-semibold text-primary">
          Your model connections
        </h2>
        <p className="text-sm leading-relaxed text-muted-foreground">
          Store one or more provider keys. Tailoring and research run on the
          connection marked as current; adding another never switches to it.
        </p>
      </CardHeader>

      <CardContent className="space-y-5">
        {loading ? (
          <p className="text-sm text-muted-foreground" aria-busy="true">
            Checking your model connections...
          </p>
        ) : null}

        {state.isError ? <ErrorNotice error={state.error} /> : null}

        {/* A server that predates multiple connections answers without the
            list. Saying so is better than rendering "none stored" over rows
            that exist. */}
        {state.data && connections === null ? (
          <Banner tone="warning" title="This API does not support multiple model connections">
            <p>
              The console cannot manage saved connections against this server.
              Update the backend, or manage the single key with the older
              endpoint.
            </p>
          </Banner>
        ) : null}

        {state.data && connections !== null ? (
          <>
            <Banner tone={using === "user" ? "success" : "neutral"} title={summaryTitle}>
              <p>
                {using === "user"
                  ? "Tailoring and research run on your saved connection, spending your own quota."
                  : mode === "required"
                    ? "Add a provider key — model calls cannot run without one."
                    : using === "platform"
                      ? "Calls use the key this deployment configured. Add your own to spend your own quota instead."
                      : "No personal key and no deployment key: model calls cannot run yet."}
              </p>
            </Banner>

            {!canWrite ? (
              <Banner tone="warning" title="Changes are refused on this deployment">
                <p>{policyNotice}</p>
              </Banner>
            ) : null}

            {connections.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                No saved connections yet.
              </p>
            ) : (
              <ul className="space-y-2">
                {connections.map((row) => {
                  const rowActive = isActive(row.id)
                  const isDefault = row.id === activeId
                  const result = testResults[row.id]
                  const rowTesting = testingId === row.id
                  return (
                    <li
                      key={row.id}
                      aria-label={`${providerLabel(row.provider)} · ${row.model}`}
                      className="flex flex-wrap items-start justify-between gap-3 rounded-surface bg-muted/40 p-3"
                    >
                      <div className="min-w-0 flex-1 space-y-1">
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="font-medium break-anywhere">
                            {row.model}
                          </span>
                          {rowActive ? (
                            <span className="rounded-[6px] bg-lime-soft px-2 py-0.5 text-[11px] font-semibold text-lime-foreground">
                              Active
                            </span>
                          ) : isDefault ? (
                            <span className="rounded-[6px] bg-muted px-2 py-0.5 text-[11px] font-semibold text-muted-foreground">
                              Default (not in use)
                            </span>
                          ) : null}
                        </div>
                        <p className="text-xs text-muted-foreground">
                          <span>{providerLabel(row.provider)}</span>
                          <span aria-hidden="true"> · </span>
                          <span className="font-mono">
                            {maskingKey(row.hint)}
                          </span>
                          {row.base_url ? (
                            <>
                              <span aria-hidden="true"> · </span>
                              <span className="break-all">{row.base_url}</span>
                            </>
                          ) : null}
                        </p>
                        {result ? (
                          result.ok ? (
                            <Banner tone="success" title="The key works">
                              <p>
                                {result.provider} · {result.model} answered in{" "}
                                {result.latency_ms} ms.
                              </p>
                            </Banner>
                          ) : (
                            <Banner tone="danger" title="The key did not work">
                              <p>
                                {result.error_type === "LLMCredentialError"
                                  ? "The provider rejected the key or the endpoint. Check the provider, the model and the URL."
                                  : `The call failed (${result.error_type ?? "unknown"}). Try again shortly.`}
                              </p>
                            </Banner>
                          )
                        ) : null}
                      </div>

                      <div className="flex flex-wrap gap-2">
                        {!rowActive ? (
                          <Button
                            variant="outline"
                            size="sm"
                            aria-label={`Make active: ${row.model}`}
                            disabled={!canWrite || testingId !== null}
                            onClick={() => activate.mutate(row.id)}
                          >
                            Make active
                          </Button>
                        ) : null}
                        {rowTesting ? (
                          <Button variant="outline" size="sm" disabled>
                            Testing...
                          </Button>
                        ) : (
                          <Button
                            variant="outline"
                            size="sm"
                            aria-label={`Test connection: ${row.model}`}
                            disabled={!canWrite}
                            onClick={() => test.mutate(row.id)}
                          >
                            Test connection
                          </Button>
                        )}
                        <Button
                          variant="outline"
                          size="sm"
                          aria-label={`Edit ${row.model}`}
                          disabled={!canWrite}
                          onClick={() => {
                            setEditing(row)
                            setEditDraft({
                              provider: row.provider,
                              model: row.model,
                              apiKey: "",
                              baseUrl: row.base_url ?? "",
                            })
                            edit.reset()
                          }}
                        >
                          Edit
                        </Button>
                        <Button
                          variant="ghost"
                          size="sm"
                          aria-label={`Remove ${row.model}`}
                          disabled={remove.isPending}
                          onClick={() => setRemoving(row)}
                        >
                          Remove
                        </Button>
                      </div>
                    </li>
                  )
                })}
              </ul>
            )}

            <div className="flex flex-wrap items-center gap-3">
              <Button
                disabled={!canWrite}
                onClick={() => {
                  add.reset()
                  setAddDraft(emptyDraft())
                  setAddOpen(true)
                }}
              >
                Add connection
              </Button>
              <p className="text-xs leading-relaxed text-muted-foreground">
                Testing makes a separate, billable provider call. It never runs
                when saving.
              </p>
            </div>
          </>
        ) : null}
      </CardContent>

      <Dialog
        open={addOpen}
        onOpenChange={(open) => {
          setAddOpen(open)
          if (!open) add.reset()
        }}
      >
        <DialogContent>
          <ConnectionEditor
            title="Add connection"
            description="The new connection is saved but does not take over. Make it active when you want jobs to spend it."
            submitLabel="Save connection"
            draft={addDraft}
            onDraft={setAddDraft}
            pending={add.isPending}
            error={add.error as Error | null}
            disabledHint={
              addDraft.model.trim().length === 0
                ? "Enter the model id this key serves."
                : addDraft.apiKey.trim().length < 8
                  ? "Paste the provider key (at least 8 characters)."
                  : NEEDS_BASE_URL.has(addDraft.provider) &&
                      addDraft.baseUrl.trim().length === 0
                    ? "Enter the endpoint this key serves."
                    : null
            }
            onCancel={() => setAddOpen(false)}
            onSubmit={() => add.mutate()}
          />
        </DialogContent>
      </Dialog>

      <Dialog
        open={editing !== null}
        onOpenChange={(open) => {
          if (!open) {
            setEditing(null)
            edit.reset()
          }
        }}
      >
        <DialogContent>
          {editing ? (
            <ConnectionEditor
              title="Edit connection"
              description="Only the fields you change are saved. Leaving the key blank keeps the stored one."
              submitLabel="Save changes"
              draft={editDraft}
              onDraft={(next) => {
                /*
                  A different provider means a different key: the stored one
                  was issued by the old provider, so it is cleared rather
                  than carried across silently.
                */
                if (next.provider !== editDraft.provider) {
                  setEditDraft({ ...next, apiKey: "" })
                  return
                }
                setEditDraft(next)
              }}
              pending={edit.isPending}
              error={edit.error as Error | null}
              disabledHint={
                Object.keys(editChanges(editing, editDraft)).length === 0
                  ? "Change a field to save."
                  : editDraft.provider !== editing.provider &&
                      editDraft.apiKey.trim().length === 0
                    ? "Enter a new key for the new provider."
                    : null
              }
              onCancel={() => {
                setEditing(null)
                edit.reset()
              }}
              onSubmit={() => edit.mutate()}
            />
          ) : null}
        </DialogContent>
      </Dialog>

      <AlertDialog
        open={removing !== null}
        onOpenChange={(open) => {
          if (!open) setRemoving(null)
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Remove connection?</AlertDialogTitle>
            <AlertDialogDescription>
              {removalConsequence(removing, connections, mode, using)}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              variant="destructive"
              disabled={remove.isPending}
              onClick={() => {
                if (removing) remove.mutate(removing.id)
              }}
            >
              Remove connection
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </Card>
  )
}

/**
 * What removing a connection means, said before it happens.
 *
 * Removing the connection in use promotes the next one the server listed, so
 * the sentence names it. Removing a spare changes nothing about what jobs
 * spend, and says that too — a confirmation that always sounds alarming
 * trains people to click through it.
 */
function removalConsequence(
  row: LlmCredentialStatus | null,
  connections: LlmCredentialStatus[] | null,
  mode: string,
  using: string
): string {
  if (!row) return ""
  const list = connections ?? []
  const inUse = using === "user" && list[0]?.id === row.id
  if (!inUse) {
    return `${row.model} is not the connection in use: the default connection will not change.`
  }
  const next = list[1]
  if (next) {
    return `${next.model} will become the default connection and the key your jobs spend.`
  }
  return mode === "required"
    ? `This is the last connection and this deployment requires your own key: model calls cannot run until you add another.`
    : `This is the last connection. Model calls will fall back to the deployment's key.`
}
