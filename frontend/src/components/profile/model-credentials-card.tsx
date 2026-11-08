import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useState } from "react"

import { Banner } from "@/components/common/banner"
import { ErrorNotice } from "@/components/common/error-notice"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { api } from "@/lib/api/endpoints"
import type { LlmCredentialInput } from "@/lib/api/types"

/**
 * Model credentials — bring your own key (WS-22).
 *
 * The user may register their own provider key. When one is stored, every
 * model call their requests make runs on **their** key, their quota and their
 * bill; the deployment's own key is only a fallback (and the deployment may
 * instead *require* a personal key).
 *
 * Two rules this card is built around:
 *
 * 1. **The key is write-only.** The read returns a mask (the last four
 *    characters). The field is cleared after a successful save and is never
 *    re-rendered from server data, because the server never has it to send.
 * 2. **Saving does not spend.** Registering a key is free; proving it works
 *    is a button, because the test call is billed to the user's own quota.
 */

const labelClass = "text-xs font-medium text-muted-foreground"
const fieldClass = "space-y-1"

const PROVIDERS = [
  { value: "google", label: "Google Gemini" },
  { value: "openai-compatible", label: "OpenAI-compatible endpoint" },
  { value: "openai", label: "OpenAI (default endpoint)" },
  { value: "zai", label: "Z.ai GLM (default endpoint)" },
] as const

/** Providers whose base URL the user must or may supply. */
const NEEDS_BASE_URL = new Set(["openai-compatible"])
const MAY_HAVE_BASE_URL = new Set(["openai-compatible", "openai", "zai", "google"])

const maskingKey = (hint: string): string => `••••••••${hint}`

export function ModelCredentialsCard() {
  const queryClient = useQueryClient()
  const state = useQuery({
    queryKey: ["llm-credentials"],
    queryFn: ({ signal }) => api.getLlmCredentials(signal),
    staleTime: 15_000,
  })

  const [provider, setProvider] = useState("google")
  const [model, setModel] = useState("")
  const [apiKey, setApiKey] = useState("")
  const [baseUrl, setBaseUrl] = useState("")

  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: ["llm-credentials"] })

  const save = useMutation({
    mutationFn: (body: LlmCredentialInput) => api.putLlmCredentials(body),
    onSuccess: () => {
      setApiKey("")
      invalidate()
    },
  })

  const remove = useMutation({
    mutationFn: () => api.deleteLlmCredentials(),
    onSuccess: invalidate,
  })

  const test = useMutation({
    mutationFn: () => api.testLlmCredentials(),
    onSuccess: invalidate,
  })

  const stored = state.data?.credential ?? null
  const mode = state.data?.mode ?? "optional"
  const available = state.data?.available ?? false

  const submit = () => {
    const body: LlmCredentialInput = {
      provider,
      model: model.trim(),
      api_key: apiKey.trim(),
      base_url: MAY_HAVE_BASE_URL.has(provider) ? baseUrl.trim() || null : null,
    }
    save.mutate(body)
  }

  const canSubmit =
    model.trim().length > 0 &&
    apiKey.trim().length >= 8 &&
    (!NEEDS_BASE_URL.has(provider) || baseUrl.trim().length > 0) &&
    !save.isPending

  return (
    <Card>
      <CardHeader>
        <CardTitle>Model credentials</CardTitle>
        <CardDescription>
          Use your own AI provider key for tailoring and research. Your calls
          then run on your key, your quota and your bill — the key is stored
          encrypted and never shown again.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-5">
        {state.isPending ? (
          <p className="text-sm text-muted-foreground">
            Checking your credentials…
          </p>
        ) : null}

        {state.isError ? <ErrorNotice error={state.error} /> : null}

        {state.data ? (
          <Banner
            tone={stored ? "success" : "neutral"}
            title={
              stored
                ? "Your key is in use"
                : mode === "required"
                  ? "This deployment requires your own key"
                  : "Using the deployment's key"
            }
          >
            {stored ? (
              <p>
                {stored.provider} · {stored.model} · key ending{" "}
                <span className="font-mono">{stored.hint}</span>
                {stored.base_url ? ` · ${stored.base_url}` : ""}
              </p>
            ) : (
              <p>
                {mode === "required"
                  ? "Add your own provider key below — tailoring and research cannot run without one."
                  : "Add your own key below to spend your own quota instead. Until then, calls use the key this deployment configured."}
              </p>
            )}
            {mode === "disabled" ? (
              <p className="mt-2">
                Personal keys are disabled on this deployment.
              </p>
            ) : null}
          </Banner>
        ) : null}

        {!available && mode !== "disabled" ? (
          <p className="text-sm text-muted-foreground">
            This deployment cannot store credentials: it has no encryption key
            material configured.
          </p>
        ) : null}

        <div className="grid gap-4 sm:grid-cols-2">
          <label className={fieldClass}>
            <span className={labelClass}>Provider</span>
            <select
              className="h-9 w-full rounded-md border border-input bg-transparent px-3 text-sm"
              value={provider}
              onChange={(e) => setProvider(e.target.value)}
            >
              {PROVIDERS.map((entry) => (
                <option key={entry.value} value={entry.value}>
                  {entry.label}
                </option>
              ))}
            </select>
          </label>
          <label className={fieldClass}>
            <span className={labelClass}>Model</span>
            <Input
              placeholder="gemini-3.8-flash"
              value={model}
              onChange={(e) => setModel(e.target.value)}
            />
          </label>
          <label className={fieldClass}>
            <span className={labelClass}>API key</span>
            <Input
              type="password"
              autoComplete="off"
              placeholder={stored ? maskingKey(stored.hint) : "Paste your key"}
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
            />
            <span className="block text-xs text-muted-foreground">
              Stored encrypted. It is never shown again and never written to a
              log or the audit trail.
            </span>
          </label>
          {MAY_HAVE_BASE_URL.has(provider) ? (
            <label className={fieldClass}>
              <span className={labelClass}>
                Base URL {NEEDS_BASE_URL.has(provider) ? "" : "(optional)"}
              </span>
              <Input
                placeholder="https://api.z.ai/api/paas/v4"
                value={baseUrl}
                onChange={(e) => setBaseUrl(e.target.value)}
              />
              {provider === "google" ? (
                <span className="block text-xs text-muted-foreground">
                  Leave empty for Google's default endpoint.
                </span>
              ) : null}
            </label>
          ) : null}
        </div>

        {save.isError ? <ErrorNotice error={save.error} /> : null}
        {remove.isError ? <ErrorNotice error={remove.error} /> : null}
        {test.isError ? <ErrorNotice error={test.error} /> : null}

        {test.data ? (
          <Banner tone={test.data.ok ? "success" : "danger"} title={test.data.ok ? "The key works" : "The key did not work"}>
            {test.data.ok ? (
              <p>
                {test.data.provider} · {test.data.model} answered in{" "}
                {test.data.latency_ms} ms.
              </p>
            ) : (
              <p>
                {test.data.error_type === "LLMCredentialError"
                  ? "The provider rejected the key or the endpoint. Check the provider, the model and the URL."
                  : `The call failed (${test.data.error_type ?? "unknown"}). Try again shortly.`}
              </p>
            )}
          </Banner>
        ) : null}

        <div className="flex flex-wrap gap-2">
          <Button onClick={submit} disabled={!canSubmit}>
            {save.isPending ? "Saving…" : stored ? "Replace key" : "Save key"}
          </Button>
          {stored ? (
            <>
              <Button
                variant="outline"
                onClick={() => test.mutate()}
                disabled={test.isPending}
              >
                {test.isPending ? "Testing…" : "Test the key"}
              </Button>
              <Button
                variant="ghost"
                onClick={() => remove.mutate()}
                disabled={remove.isPending}
              >
                {remove.isPending ? "Removing…" : "Remove"}
              </Button>
            </>
          ) : null}
        </div>
      </CardContent>
    </Card>
  )
}