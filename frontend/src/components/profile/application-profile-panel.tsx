import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Check, Pencil, X } from "lucide-react"
import { useState } from "react"

import { ErrorNotice } from "@/components/common/error-notice"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { api } from "@/lib/api/endpoints"
import type { ApplicationProfileInput, EeoProfile } from "@/lib/api/types"

/**
 * The answers you confirm (WS-20).
 *
 * A résumé is not an application form. It rarely says whether you can work
 * without sponsorship, what salary you want, or how much notice you owe — yet
 * every application asks. This is where you answer once, so the agent can
 * answer for you.
 *
 * Two cards, in the order they matter:
 *
 * 1. **Work preferences** — what you want from a job (where, how, how much).
 *    Each line is editable in place; a preference you set here is what the
 *    matching uses.
 * 2. **Application answers** — the facts a form asks for. Work authorization,
 *    sponsorship and citizenship are three separate questions, because they
 *    are three separate answers.
 *
 * Voluntary self-identification is a third, separate card: never inferred,
 * never used for matching, and deletable.
 */

type Tri = "" | "yes" | "no"

const tri = {
  from: (value: boolean | null | undefined): Tri =>
    value === true ? "yes" : value === false ? "no" : "",
  to: (value: Tri): boolean | null =>
    value === "yes" ? true : value === "no" ? false : null,
}
const num = (value: string): number | null => {
  const trimmed = value.trim()
  if (!trimmed) return null
  const parsed = Number(trimmed)
  return Number.isFinite(parsed) ? parsed : null
}
const list = (value: string): string[] =>
  value
    .split(",")
    .map((part) => part.trim())
    .filter(Boolean)

const labelClass = "text-xs font-medium text-muted-foreground"
const fieldClass = "space-y-1"

/** The whole profile, in the shape the API writes back. */
function emptyProfile(): ApplicationProfileInput {
  return {
    professional: {},
    preferences: { preferred_locations: [], employment_types: [] },
    answers: {
      work_authorization: {},
      compensation: {},
      notice: {},
    },
  }
}

export function ApplicationProfilePanel({ profileId }: { profileId: string }) {
  const queryClient = useQueryClient()
  const query = useQuery({
    queryKey: ["application-profile", profileId],
    queryFn: ({ signal }) => api.getApplicationProfile(profileId, signal),
  })
  const save = useMutation({
    mutationFn: (body: ApplicationProfileInput) =>
      api.putApplicationProfile(profileId, body),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ["application-profile", profileId] }),
  })

  if (query.isPending) {
    return <p className="text-sm text-muted-foreground">Loading…</p>
  }
  if (query.isError) {
    return <ErrorNotice error={query.error} onRetry={() => query.refetch()} />
  }

  const loaded = query.data.application_profile as ApplicationProfileInput
  return (
    <div className="space-y-5">
      <WorkPreferencesCard
        key={`prefs-${profileId}`}
        profile={loaded}
        onSave={(body) => save.mutate(body)}
        saving={save.isPending}
      />
      <ApplicationAnswersCard
        key={`answers-${profileId}`}
        profile={loaded}
        onSave={(body) => save.mutate(body)}
        saving={save.isPending}
      />
      <EeoCard profileId={profileId} />
    </div>
  )
}

/** One editable line: the value, and a pencil that turns it into an input. */
function EditableRow({
  label,
  display,
  children,
  editing,
  onEdit,
  onCancel,
  onSave,
}: {
  label: string
  display: string
  children: React.ReactNode
  editing: boolean
  onEdit: () => void
  onCancel: () => void
  onSave: () => void
}) {
  return (
    <div className="flex items-start justify-between gap-3 py-2">
      <div className="min-w-0 flex-1">
        <p className={labelClass}>{label}</p>
        {editing ? (
          <div className="mt-1">{children}</div>
        ) : (
          <p className="truncate text-sm text-foreground">{display}</p>
        )}
      </div>
      <div className="flex shrink-0 items-center gap-1 pt-4">
        {editing ? (
          <>
            <Button variant="ghost" size="sm" aria-label={`Save ${label}`} onClick={onSave}>
              <Check aria-hidden="true" className="size-4" />
            </Button>
            <Button variant="ghost" size="sm" aria-label={`Cancel ${label}`} onClick={onCancel}>
              <X aria-hidden="true" className="size-4" />
            </Button>
          </>
        ) : (
          <Button variant="ghost" size="sm" aria-label={`Edit ${label}`} onClick={onEdit}>
            <Pencil aria-hidden="true" className="size-4" />
          </Button>
        )}
      </div>
    </div>
  )
}

/**
 * The work preferences, editable in place.
 *
 * These are what you want, not what a résumé happened to say — so the matching
 * uses them (a preferred city or a salary floor changes the ranking).
 */
function WorkPreferencesCard({
  profile,
  onSave,
  saving,
}: {
  profile: ApplicationProfileInput
  onSave: (body: ApplicationProfileInput) => void
  saving: boolean
}) {
  const prefs = profile.preferences ?? {}
  const comp = profile.answers?.compensation ?? {}
  const [editing, setEditing] = useState<string | null>(null)

  // A working copy, so saving one field never drops the others.
  const [draft, setDraft] = useState({
    remote: prefs.remote_preference ?? "",
    locations: (prefs.preferred_locations ?? []).join(", "),
    employment: (prefs.employment_types ?? []).join(", "),
    salary: comp.expected_salary?.toString() ?? "",
    currency: comp.expected_currency ?? "",
    period: comp.expected_period ?? "",
  })

  function commit() {
    onSave({
      ...emptyProfile(),
      ...profile,
      preferences: {
        ...prefs,
        remote_preference: draft.remote || null,
        preferred_locations: list(draft.locations),
        employment_types: list(draft.employment),
      },
      answers: {
        ...profile.answers,
        compensation: {
          ...comp,
          expected_salary: num(draft.salary),
          expected_currency: draft.currency.trim() || null,
          expected_period: draft.period || null,
        },
      },
      confirmed_fields: ["preferences", "answers.compensation"],
    })
    setEditing(null)
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Work preferences</CardTitle>
        <CardDescription>
          What you want from a job. These guide the ranking, so they are yours
          to set — a résumé can only guess.
        </CardDescription>
      </CardHeader>
      <CardContent className="divide-y divide-border">
        <EditableRow
          label="Work mode"
          display={draft.remote || "Not set"}
          editing={editing === "remote"}
          onEdit={() => setEditing("remote")}
          onCancel={() => setEditing(null)}
          onSave={commit}
        >
          <select
            className="h-9 w-full rounded-md border border-input bg-transparent px-3 text-sm"
            value={draft.remote}
            onChange={(e) => setDraft((d) => ({ ...d, remote: e.target.value }))}
          >
            <option value="">Not set</option>
            <option value="remote">Remote</option>
            <option value="hybrid">Hybrid</option>
            <option value="onsite">Onsite</option>
            <option value="any">Any</option>
          </select>
        </EditableRow>

        <EditableRow
          label="Preferred locations"
          display={draft.locations || "Not set"}
          editing={editing === "locations"}
          onEdit={() => setEditing("locations")}
          onCancel={() => setEditing(null)}
          onSave={commit}
        >
          <Input
            placeholder="Berlin, Remote"
            value={draft.locations}
            onChange={(e) => setDraft((d) => ({ ...d, locations: e.target.value }))}
          />
        </EditableRow>

        <EditableRow
          label="Employment types"
          display={draft.employment || "Not set"}
          editing={editing === "employment"}
          onEdit={() => setEditing("employment")}
          onCancel={() => setEditing(null)}
          onSave={commit}
        >
          <Input
            placeholder="full-time, contract"
            value={draft.employment}
            onChange={(e) => setDraft((d) => ({ ...d, employment: e.target.value }))}
          />
        </EditableRow>

        <EditableRow
          label="Expected salary"
          display={
            draft.salary
              ? `${draft.currency || ""} ${draft.salary}${draft.period ? ` per ${draft.period}` : ""}`.trim()
              : "Not set"
          }
          editing={editing === "salary"}
          onEdit={() => setEditing("salary")}
          onCancel={() => setEditing(null)}
          onSave={commit}
        >
          <div className="grid gap-2 sm:grid-cols-3">
            <Input
              inputMode="numeric"
              placeholder="Amount"
              value={draft.salary}
              onChange={(e) => setDraft((d) => ({ ...d, salary: e.target.value }))}
            />
            <Input
              placeholder="USD"
              value={draft.currency}
              onChange={(e) => setDraft((d) => ({ ...d, currency: e.target.value }))}
            />
            <select
              className="h-9 w-full rounded-md border border-input bg-transparent px-3 text-sm"
              value={draft.period}
              onChange={(e) => setDraft((d) => ({ ...d, period: e.target.value }))}
            >
              <option value="">Period</option>
              <option value="annual">Annual</option>
              <option value="monthly">Monthly</option>
              <option value="weekly">Weekly</option>
              <option value="daily">Daily</option>
              <option value="hourly">Hourly</option>
            </select>
          </div>
        </EditableRow>

        {saving ? <p className="pt-2 text-xs text-muted-foreground">Saving…</p> : null}
      </CardContent>
    </Card>
  )
}

/** The facts a form asks for, that a résumé does not carry. */
function ApplicationAnswersCard({
  profile,
  onSave,
  saving,
}: {
  profile: ApplicationProfileInput
  onSave: (body: ApplicationProfileInput) => void
  saving: boolean
}) {
  const pro = profile.professional ?? {}
  const wa = profile.answers?.work_authorization ?? {}
  const comp = profile.answers?.compensation ?? {}
  const notice = profile.answers?.notice ?? {}

  const [form, setForm] = useState({
    years: pro.total_experience_years?.toString() ?? "",
    seniority: pro.seniority_level ?? "",
    title: pro.current_title ?? "",
    portfolio: pro.portfolio_url ?? "",
    linkedin: pro.linkedin_url ?? "",
    authorized: tri.from(wa.legally_authorized),
    sponsorship: tri.from(wa.requires_sponsorship),
    citizenship: wa.citizenship_status ?? "",
    currentSalary: comp.current_salary?.toString() ?? "",
    noticeDays: notice.notice_days?.toString() ?? "",
  })

  const missing = [
    !form.seniority.trim() && "seniority",
    !form.authorized && "work authorization",
    !form.sponsorship && "sponsorship",
    !form.noticeDays.trim() && "notice period",
  ].filter(Boolean) as string[]

  function submit() {
    onSave({
      ...emptyProfile(),
      ...profile,
      professional: {
        ...pro,
        total_experience_years: num(form.years),
        seniority_level: form.seniority.trim() || null,
        current_title: form.title.trim() || null,
        portfolio_url: form.portfolio.trim() || null,
        linkedin_url: form.linkedin.trim() || null,
      },
      answers: {
        ...profile.answers,
        work_authorization: {
          ...wa,
          legally_authorized: tri.to(form.authorized),
          requires_sponsorship: tri.to(form.sponsorship),
          citizenship_status: form.citizenship.trim() || null,
        },
        compensation: { ...comp, current_salary: num(form.currentSalary) },
        notice: { ...notice, notice_days: num(form.noticeDays) },
      },
      confirmed_fields: ["professional", "answers"],
    })
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Application answers</CardTitle>
        <CardDescription>
          What a form asks and a résumé does not answer. Authorization,
          sponsorship and citizenship are separate questions, because they have
          separate answers.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-5">
        <div className="grid gap-4 sm:grid-cols-2">
          <label className={fieldClass}>
            <span className={labelClass}>Total years of experience</span>
            <Input
              inputMode="numeric"
              value={form.years}
              onChange={(e) => setForm((f) => ({ ...f, years: e.target.value }))}
            />
          </label>
          <label className={fieldClass}>
            <span className={labelClass}>Seniority</span>
            <Input
              placeholder="senior, lead, mid…"
              value={form.seniority}
              onChange={(e) => setForm((f) => ({ ...f, seniority: e.target.value }))}
            />
          </label>
          <label className={fieldClass}>
            <span className={labelClass}>Current title</span>
            <Input
              value={form.title}
              onChange={(e) => setForm((f) => ({ ...f, title: e.target.value }))}
            />
          </label>
          <label className={fieldClass}>
            <span className={labelClass}>Portfolio URL</span>
            <Input
              value={form.portfolio}
              onChange={(e) => setForm((f) => ({ ...f, portfolio: e.target.value }))}
            />
          </label>
          <label className={fieldClass}>
            <span className={labelClass}>LinkedIn URL</span>
            <Input
              value={form.linkedin}
              onChange={(e) => setForm((f) => ({ ...f, linkedin: e.target.value }))}
            />
          </label>
        </div>

        <div className="grid gap-4 sm:grid-cols-2">
          <label className={fieldClass}>
            <span className={labelClass}>Authorized to work here?</span>
            <select
              className="h-9 w-full rounded-md border border-input bg-transparent px-3 text-sm"
              value={form.authorized}
              onChange={(e) => setForm((f) => ({ ...f, authorized: e.target.value as Tri }))}
            >
              <option value="">Not answered</option>
              <option value="yes">Yes</option>
              <option value="no">No</option>
            </select>
          </label>
          <label className={fieldClass}>
            <span className={labelClass}>Need visa sponsorship?</span>
            <select
              className="h-9 w-full rounded-md border border-input bg-transparent px-3 text-sm"
              value={form.sponsorship}
              onChange={(e) => setForm((f) => ({ ...f, sponsorship: e.target.value as Tri }))}
            >
              <option value="">Not answered</option>
              <option value="yes">Yes, now or later</option>
              <option value="no">No</option>
            </select>
          </label>
          <label className={fieldClass}>
            <span className={labelClass}>Citizenship / status (optional)</span>
            <Input
              value={form.citizenship}
              onChange={(e) => setForm((f) => ({ ...f, citizenship: e.target.value }))}
            />
          </label>
          <label className={fieldClass}>
            <span className={labelClass}>Current salary (optional)</span>
            <Input
              inputMode="numeric"
              value={form.currentSalary}
              onChange={(e) => setForm((f) => ({ ...f, currentSalary: e.target.value }))}
            />
          </label>
          <label className={fieldClass}>
            <span className={labelClass}>Notice period (days; 0 = immediate)</span>
            <Input
              inputMode="numeric"
              value={form.noticeDays}
              onChange={(e) => setForm((f) => ({ ...f, noticeDays: e.target.value }))}
            />
          </label>
        </div>

        {missing.length > 0 ? (
          <p className="text-xs text-muted-foreground">
            Still missing: {missing.join(", ")}. Filling these lets the agent
            answer more questions for you.
          </p>
        ) : null}

        <Button onClick={submit} disabled={saving}>
          {saving ? "Saving…" : "Save answers"}
        </Button>
      </CardContent>
    </Card>
  )
}

const EEO_FIELDS: { key: keyof EeoProfile; label: string }[] = [
  { key: "race_ethnicity", label: "Race / ethnicity" },
  { key: "gender", label: "Gender" },
  { key: "disability", label: "Disability status" },
  { key: "veteran_status", label: "Veteran status" },
]

function EeoCard({ profileId }: { profileId: string }) {
  const queryClient = useQueryClient()
  const query = useQuery({
    queryKey: ["eeo", profileId],
    queryFn: ({ signal }) => api.getEeo(profileId, signal),
  })
  const eeo = query.data?.eeo
  const [optIn, setOptIn] = useState<boolean | null>(null)
  const [values, setValues] = useState<Record<string, string> | null>(null)

  const effectiveOptIn = optIn ?? Boolean(eeo?.opt_in)
  const currentValues =
    values ??
    Object.fromEntries(EEO_FIELDS.map(({ key }) => [key, (eeo?.[key] as string) ?? ""]))

  const save = useMutation({
    mutationFn: () =>
      api.putEeo(profileId, { opt_in: effectiveOptIn, ...currentValues } as EeoProfile),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["eeo", profileId] }),
  })
  const remove = useMutation({
    mutationFn: () => api.deleteEeo(profileId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["eeo", profileId] }),
  })

  return (
    <Card>
      <CardHeader>
        <CardTitle>Voluntary self-identification</CardTitle>
        <CardDescription>
          Optional. Never guessed from your résumé, never used to rank jobs, and
          you can delete it at any time.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={effectiveOptIn}
            onChange={(e) => setOptIn(e.target.checked)}
          />
          I want to provide these details
        </label>
        <div className="grid gap-4 sm:grid-cols-2">
          {EEO_FIELDS.map(({ key, label }) => (
            <label key={key} className={fieldClass}>
              <span className={labelClass}>{label}</span>
              <Input
                disabled={!effectiveOptIn}
                value={currentValues[key] ?? ""}
                onChange={(e) =>
                  setValues((prev) => ({
                    ...(prev ?? currentValues),
                    [key]: e.target.value,
                  }))
                }
              />
            </label>
          ))}
        </div>
        <div className="flex items-center gap-3">
          <Button variant="outline" onClick={() => save.mutate()} disabled={save.isPending}>
            Save
          </Button>
          <Button variant="ghost" onClick={() => remove.mutate()} disabled={remove.isPending}>
            Delete this data
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}