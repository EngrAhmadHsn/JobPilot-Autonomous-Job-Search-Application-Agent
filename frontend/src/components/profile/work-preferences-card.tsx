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
import type {
  ApplicationProfileInput,
  ApplicationProfileResponse,
} from "@/lib/api/types"

/**
 * Work preferences — **one** editor, on both pages (WS-21).
 *
 * The Resume page used to show a read-only card of résumé-derived
 * preferences while the Profile page edited a different document, and
 * neither page showed what the matcher actually used. This component is the
 * single source of truth: the same fields, options, validation, save and
 * source on both screens, writing the user-confirmed application profile.
 *
 * Résumé-detected values are shown as **provenance, not truth**: a labelled
 * strip offers them ("Use detected values") and only the user's Save writes
 * anything. A saved field — including a cleared one — is the answer; the
 * engine's merge is explicit about that, so clearing a preference cannot
 * resurrect the résumé's value.
 */

const labelClass = "text-xs font-medium text-muted-foreground"
const fieldClass = "space-y-1"

const list = (value: string): string[] =>
  value
    .split(",")
    .map((part) => part.trim())
    .filter(Boolean)

const num = (value: string): number | null => {
  const trimmed = value.trim()
  if (!trimmed) return null
  const parsed = Number(trimmed)
  return Number.isFinite(parsed) ? parsed : null
}

/** The confirmed groups this card owns (the engine merges by these markers). */
export const PREFERENCE_CONFIRMED_FIELDS = [
  "preferences",
  "preferences.target_roles",
  "answers.compensation",
]

/** The amount and currency inside a verbatim résumé salary line, if any. */
function detectedSalary(
  text: string | null | undefined
): { amount: string; currency: string } | null {
  if (!text) return null
  const match = /(\d[\d,]*)/.exec(text)
  if (!match) return null
  const currency = text.includes("$")
    ? "USD"
    : text.includes("€")
      ? "EUR"
      : text.includes("£")
        ? "GBP"
        : ""
  return { amount: (match[1] ?? "").replace(/,/g, ""), currency }
}

export function WorkPreferencesCard({ profileId }: { profileId: string }) {
  const query = useQuery({
    queryKey: ["application-profile", profileId],
    queryFn: ({ signal }) => api.getApplicationProfile(profileId, signal),
  })

  if (query.isPending) {
    return <p className="text-sm text-muted-foreground">Loading…</p>
  }
  if (query.isError) {
    return <ErrorNotice error={query.error} onRetry={() => query.refetch()} />
  }

  return (
    <WorkPreferencesForm
      key={profileId}
      profileId={profileId}
      profile={query.data.application_profile as ApplicationProfileInput}
    />
  )
}

function WorkPreferencesForm({
  profileId,
  profile,
}: {
  profileId: string
  profile: ApplicationProfileInput
}) {
  const queryClient = useQueryClient()
  // The résumé's own work_preferences, for the detected strip only. The
  // query is shared with the screens that already load the profile.
  const resume = useQuery({
    queryKey: ["profile", profileId],
    queryFn: ({ signal }) => api.getResume(profileId, signal),
    retry: false,
  })

  const prefs = profile.preferences ?? {}
  const comp = profile.answers?.compensation ?? {}

  const [draft, setDraft] = useState({
    remote: prefs.remote_preference ?? "",
    locations: (prefs.preferred_locations ?? []).join(", "),
    employment: (prefs.employment_types ?? []).join(", "),
    salary: comp.expected_salary?.toString() ?? "",
    currency: comp.expected_currency ?? "",
    period: comp.expected_period ?? "",
    targets: (prefs.target_roles ?? []).join(", "),
  })

  const save = useMutation({
    mutationFn: (body: ApplicationProfileInput) =>
      api.putApplicationProfile(profileId, body),
    onSuccess: () =>
      queryClient.invalidateQueries({
        queryKey: ["application-profile", profileId],
      }),
  })

  /*
    The PUT body is built from the **latest cached document**, not the
    render-time snapshot: another card (the application answers) may have
    saved in between, and saving this card must not clobber its fields.
  */
  function buildBody(): ApplicationProfileInput {
    const cached = queryClient.getQueryData<ApplicationProfileResponse>([
      "application-profile",
      profileId,
    ])
    const base =
      (cached?.application_profile as ApplicationProfileInput) ?? profile
    return {
      ...base,
      preferences: {
        ...(base.preferences ?? {}),
        remote_preference: draft.remote || null,
        preferred_locations: list(draft.locations),
        employment_types: list(draft.employment),
        target_roles: list(draft.targets),
      },
      answers: {
        ...base.answers,
        compensation: {
          ...(base.answers?.compensation ?? {}),
          expected_salary: num(draft.salary),
          expected_currency: draft.currency.trim() || null,
          expected_period: draft.period || null,
        },
      },
      confirmed_fields: Array.from(
        new Set([
          ...(base.confirmed_fields ?? []),
          ...PREFERENCE_CONFIRMED_FIELDS,
        ])
      ),
    }
  }

  const detected = resume.data?.profile.work_preferences
  const detectedRows: string[] = detected
    ? [
        detected.remote_preference
          ? `Work mode: ${detected.remote_preference}`
          : "",
        detected.preferred_locations.length > 0
          ? `Locations: ${detected.preferred_locations.join(", ")}`
          : "",
        detected.employment_types.length > 0
          ? `Employment types: ${detected.employment_types.join(", ")}`
          : "",
        detected.min_salary ? `Minimum salary: ${detected.min_salary}` : "",
        detected.work_authorization
          ? `Work authorization: ${detected.work_authorization} — an application answer; set it on the Profile screen`
          : "",
      ].filter(Boolean)
    : []

  function useDetectedValues() {
    const salary = detectedSalary(detected?.min_salary)
    setDraft((current) => ({
      ...current,
      remote: detected?.remote_preference ?? current.remote,
      locations: detected?.preferred_locations.join(", ") || current.locations,
      employment: detected?.employment_types.join(", ") || current.employment,
      salary: salary?.amount ?? current.salary,
      currency: salary?.currency || current.currency,
    }))
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Work preferences</CardTitle>
        <CardDescription>
          What you want from a job. These guide the ranking and the
          occupational-role match — and this is the same editor on your Résumé
          and Profile pages, so they always agree.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-5">
        {detectedRows.length > 0 ? (
          <Banner
            tone="neutral"
            title="Detected from your résumé (not saved yet)"
          >
            <ul className="list-disc space-y-0.5 pl-5">
              {detectedRows.map((row) => (
                <li key={row}>{row}</li>
              ))}
            </ul>
            <div className="mt-3">
              <Button variant="outline" size="sm" onClick={useDetectedValues}>
                Use detected values
              </Button>
            </div>
          </Banner>
        ) : null}

        <div className="grid gap-4 sm:grid-cols-2">
          <label className={fieldClass}>
            <span className={labelClass}>Work mode</span>
            <select
              className="h-9 w-full rounded-md border border-input bg-transparent px-3 text-sm"
              value={draft.remote}
              onChange={(e) =>
                setDraft((d) => ({ ...d, remote: e.target.value }))
              }
            >
              <option value="">Not set</option>
              <option value="remote">Remote</option>
              <option value="hybrid">Hybrid</option>
              <option value="onsite">Onsite</option>
              <option value="any">Any</option>
            </select>
          </label>
          <label className={fieldClass}>
            <span className={labelClass}>Employment types</span>
            <Input
              placeholder="full-time, contract"
              value={draft.employment}
              onChange={(e) =>
                setDraft((d) => ({ ...d, employment: e.target.value }))
              }
            />
          </label>
          <label className={`${fieldClass} sm:col-span-2`}>
            <span className={labelClass}>Preferred locations</span>
            <Input
              placeholder="Berlin, Remote"
              value={draft.locations}
              onChange={(e) =>
                setDraft((d) => ({ ...d, locations: e.target.value }))
              }
            />
          </label>
          <div className={`${fieldClass} sm:col-span-2`}>
            <label className={fieldClass}>
              <span className={labelClass}>Target roles</span>
              <Input
                placeholder="Web Developer, Frontend Developer"
                value={draft.targets}
                onChange={(e) =>
                  setDraft((d) => ({ ...d, targets: e.target.value }))
                }
              />
            </label>
            <span className="block text-xs text-muted-foreground">
              The occupations you want matched. These decide the
              occupational-role score, and they take priority over anything
              inferred from your résumé. Leave empty to match on everything.
            </span>
          </div>
          <div className={`${fieldClass} sm:col-span-2`}>
            <span className={labelClass}>Expected salary</span>
            <div className="grid gap-2 sm:grid-cols-3">
              <Input
                inputMode="numeric"
                placeholder="Amount"
                value={draft.salary}
                onChange={(e) =>
                  setDraft((d) => ({ ...d, salary: e.target.value }))
                }
              />
              <Input
                placeholder="USD"
                value={draft.currency}
                onChange={(e) =>
                  setDraft((d) => ({ ...d, currency: e.target.value }))
                }
              />
              <select
                className="h-9 w-full rounded-md border border-input bg-transparent px-3 text-sm"
                value={draft.period}
                onChange={(e) =>
                  setDraft((d) => ({ ...d, period: e.target.value }))
                }
              >
                <option value="">Period</option>
                <option value="annual">Annual</option>
                <option value="monthly">Monthly</option>
                <option value="weekly">Weekly</option>
                <option value="daily">Daily</option>
                <option value="hourly">Hourly</option>
              </select>
            </div>
          </div>
        </div>

        {save.isError ? <ErrorNotice error={save.error} /> : null}

        <Button
          onClick={() => save.mutate(buildBody())}
          disabled={save.isPending}
        >
          {save.isPending ? "Saving…" : "Save preferences"}
        </Button>
      </CardContent>
    </Card>
  )
}
