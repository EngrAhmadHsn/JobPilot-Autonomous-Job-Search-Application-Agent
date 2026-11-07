import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useState } from "react"

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
import type { ApplicationProfileInput, EeoProfile } from "@/lib/api/types"

/**
 * The application profile editor (WS-20).
 *
 * A résumé is not an application form: visa status, notice period, expected
 * salary and EEO selections are not on it, yet a form asks for them. This
 * panel is where the candidate confirms those values, kept separate from the
 * parsed résumé above.
 *
 * Work authorization, sponsorship and citizenship are three *separate*
 * questions here, because they are three separate answers — a candidate may
 * be authorized today and still need sponsorship later.
 *
 * EEO data is a separate, clearly optional card. It is never inferred, never
 * used for matching, and can be deleted outright.
 */

type Tri = "" | "yes" | "no"

function triToBool(value: Tri): boolean | null {
  if (value === "yes") return true
  if (value === "no") return false
  return null
}
function boolToTri(value: boolean | null | undefined): Tri {
  if (value === true) return "yes"
  if (value === false) return "no"
  return ""
}
function intOrNull(value: string): number | null {
  const trimmed = value.trim()
  if (!trimmed) return null
  const n = Number(trimmed)
  return Number.isFinite(n) ? n : null
}
function listFrom(value: string): string[] {
  return value
    .split(",")
    .map((part) => part.trim())
    .filter(Boolean)
}

const labelClass = "text-xs font-medium text-muted-foreground"
const fieldClass = "space-y-1"

export function ApplicationProfilePanel({ profileId }: { profileId: string }) {
  const queryClient = useQueryClient()
  const query = useQuery({
    queryKey: ["application-profile", profileId],
    queryFn: ({ signal }) => api.getApplicationProfile(profileId, signal),
  })
  const eeoQuery = useQuery({
    queryKey: ["eeo", profileId],
    queryFn: ({ signal }) => api.getEeo(profileId, signal),
  })

  const save = useMutation({
    mutationFn: (body: ApplicationProfileInput) =>
      api.putApplicationProfile(profileId, body),
    onSuccess: () =>
      queryClient.invalidateQueries({
        queryKey: ["application-profile", profileId],
      }),
  })

  if (query.isPending) {
    return <p className="text-sm text-muted-foreground">Loading profile…</p>
  }
  if (query.isError) {
    return (
      <ErrorNotice error={query.error} onRetry={() => query.refetch()} />
    )
  }
  // Remount the form (keyed on the loaded data) so state initialises once.
  return (
    <ProfileForm
      key={JSON.stringify(query.data.application_profile)}
      profileId={profileId}
      current={query.data.application_profile}
      onSave={(body) => save.mutate(body)}
      saving={save.isPending}
      saved={save.isSuccess}
      eeo={eeoQuery.data?.eeo ?? null}
    />
  )
}

function ProfileForm({
  profileId,
  current,
  onSave,
  saving,
  saved,
  eeo,
}: {
  profileId: string
  current: ApplicationProfileInput & {
    professional: {
      total_experience_years: number | null
      seniority_level: string | null
      current_title: string | null
      portfolio_url: string | null
      linkedin_url: string | null
    }
    preferences: {
      preferred_locations: string[]
      remote_preference: string | null
      employment_types: string[]
      willing_to_relocate: boolean | null
    }
    answers: {
      work_authorization: {
        legally_authorized: boolean | null
        requires_sponsorship: boolean | null
        citizenship_status: string | null
      }
      compensation: {
        expected_salary: number | null
        expected_currency: string | null
        expected_period: string | null
        current_salary: number | null
        current_currency: string | null
        current_period: string | null
      }
      notice: {
        notice_days: number | null
        available_from: string | null
      }
    }
  }
  onSave: (body: ApplicationProfileInput) => void
  saving: boolean
  saved: boolean
  eeo: EeoProfile | null
}) {
  const [years, setYears] = useState(
    current.professional.total_experience_years?.toString() ?? ""
  )
  const [seniority, setSeniority] = useState(
    current.professional.seniority_level ?? ""
  )
  const [title, setTitle] = useState(current.professional.current_title ?? "")
  const [portfolio, setPortfolio] = useState(
    current.professional.portfolio_url ?? ""
  )
  const [linkedin, setLinkedin] = useState(
    current.professional.linkedin_url ?? ""
  )
  const [locations, setLocations] = useState(
    current.preferences.preferred_locations.join(", ")
  )
  const [remote, setRemote] = useState(
    current.preferences.remote_preference ?? ""
  )
  const [employment, setEmployment] = useState(
    current.preferences.employment_types.join(", ")
  )
  const [authorized, setAuthorized] = useState<Tri>(
    boolToTri(current.answers.work_authorization.legally_authorized)
  )
  const [sponsorship, setSponsorship] = useState<Tri>(
    boolToTri(current.answers.work_authorization.requires_sponsorship)
  )
  const [citizenship, setCitizenship] = useState(
    current.answers.work_authorization.citizenship_status ?? ""
  )
  const [expSalary, setExpSalary] = useState(
    current.answers.compensation.expected_salary?.toString() ?? ""
  )
  const [expCurrency, setExpCurrency] = useState(
    current.answers.compensation.expected_currency ?? ""
  )
  const [expPeriod, setExpPeriod] = useState(
    current.answers.compensation.expected_period ?? ""
  )
  const [curSalary, setCurSalary] = useState(
    current.answers.compensation.current_salary?.toString() ?? ""
  )
  const [noticeDays, setNoticeDays] = useState(
    current.answers.notice.notice_days?.toString() ?? ""
  )

  const missing: string[] = []
  if (!seniority.trim()) missing.push("seniority level")
  if (!authorized) missing.push("work authorization")
  if (!sponsorship) missing.push("sponsorship")
  if (!expSalary.trim()) missing.push("expected salary")
  if (!noticeDays.trim()) missing.push("notice period")

  function submit() {
    onSave({
      professional: {
        total_experience_years: intOrNull(years),
        seniority_level: seniority.trim() || null,
        current_title: title.trim() || null,
        portfolio_url: portfolio.trim() || null,
        linkedin_url: linkedin.trim() || null,
      },
      preferences: {
        preferred_locations: listFrom(locations),
        remote_preference: remote || null,
        employment_types: listFrom(employment),
      },
      answers: {
        work_authorization: {
          legally_authorized: triToBool(authorized),
          requires_sponsorship: triToBool(sponsorship),
          citizenship_status: citizenship.trim() || null,
        },
        compensation: {
          expected_salary: intOrNull(expSalary),
          expected_currency: expCurrency.trim() || null,
          expected_period: expPeriod || null,
          current_salary: intOrNull(curSalary),
        },
        notice: { notice_days: intOrNull(noticeDays) },
      },
      confirmed_fields: ["answers", "preferences"],
    })
  }

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>Application answers</CardTitle>
          <CardDescription>
            What a job form will ask and your résumé does not answer. Your
            résumé facts stay separate from these confirmed values.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-5">
          <div className="grid gap-4 sm:grid-cols-2">
            <label className={fieldClass}>
              <span className={labelClass}>Total years of experience</span>
              <Input
                inputMode="numeric"
                value={years}
                onChange={(e) => setYears(e.target.value)}
              />
            </label>
            <label className={fieldClass}>
              <span className={labelClass}>Seniority level</span>
              <Input
                placeholder="senior, lead, mid…"
                value={seniority}
                onChange={(e) => setSeniority(e.target.value)}
              />
            </label>
            <label className={fieldClass}>
              <span className={labelClass}>Current title</span>
              <Input value={title} onChange={(e) => setTitle(e.target.value)} />
            </label>
            <label className={fieldClass}>
              <span className={labelClass}>Portfolio URL</span>
              <Input
                value={portfolio}
                onChange={(e) => setPortfolio(e.target.value)}
              />
            </label>
            <label className={fieldClass}>
              <span className={labelClass}>LinkedIn URL</span>
              <Input
                value={linkedin}
                onChange={(e) => setLinkedin(e.target.value)}
              />
            </label>
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <label className={fieldClass}>
              <span className={labelClass}>
                Are you legally authorized to work?
              </span>
              <select
                className="h-9 w-full rounded-md border border-input bg-transparent px-3 text-sm"
                value={authorized}
                onChange={(e) => setAuthorized(e.target.value as Tri)}
              >
                <option value="">Not answered</option>
                <option value="yes">Yes</option>
                <option value="no">No</option>
              </select>
            </label>
            <label className={fieldClass}>
              <span className={labelClass}>
                Do you require visa sponsorship?
              </span>
              <select
                className="h-9 w-full rounded-md border border-input bg-transparent px-3 text-sm"
                value={sponsorship}
                onChange={(e) => setSponsorship(e.target.value as Tri)}
              >
                <option value="">Not answered</option>
                <option value="yes">Yes, now or in the future</option>
                <option value="no">No</option>
              </select>
            </label>
            <label className={fieldClass}>
              <span className={labelClass}>
                Citizenship / immigration status (optional)
              </span>
              <Input
                value={citizenship}
                onChange={(e) => setCitizenship(e.target.value)}
              />
            </label>
          </div>

          <div className="grid gap-4 sm:grid-cols-3">
            <label className={fieldClass}>
              <span className={labelClass}>Expected salary</span>
              <Input
                inputMode="numeric"
                value={expSalary}
                onChange={(e) => setExpSalary(e.target.value)}
              />
            </label>
            <label className={fieldClass}>
              <span className={labelClass}>Currency</span>
              <Input
                placeholder="USD"
                value={expCurrency}
                onChange={(e) => setExpCurrency(e.target.value)}
              />
            </label>
            <label className={fieldClass}>
              <span className={labelClass}>Period</span>
              <select
                className="h-9 w-full rounded-md border border-input bg-transparent px-3 text-sm"
                value={expPeriod}
                onChange={(e) => setExpPeriod(e.target.value)}
              >
                <option value="">Not set</option>
                <option value="annual">Annual</option>
                <option value="monthly">Monthly</option>
                <option value="weekly">Weekly</option>
                <option value="daily">Daily</option>
                <option value="hourly">Hourly</option>
              </select>
            </label>
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <label className={fieldClass}>
              <span className={labelClass}>Current salary (optional)</span>
              <Input
                inputMode="numeric"
                value={curSalary}
                onChange={(e) => setCurSalary(e.target.value)}
              />
            </label>
            <label className={fieldClass}>
              <span className={labelClass}>
                Notice period (days; 0 = immediate)
              </span>
              <Input
                inputMode="numeric"
                value={noticeDays}
                onChange={(e) => setNoticeDays(e.target.value)}
              />
            </label>
          </div>

          <div className="grid gap-4 sm:grid-cols-3">
            <label className={fieldClass}>
              <span className={labelClass}>Preferred locations</span>
              <Input
                placeholder="Berlin, Remote"
                value={locations}
                onChange={(e) => setLocations(e.target.value)}
              />
            </label>
            <label className={fieldClass}>
              <span className={labelClass}>Work mode</span>
              <select
                className="h-9 w-full rounded-md border border-input bg-transparent px-3 text-sm"
                value={remote}
                onChange={(e) => setRemote(e.target.value)}
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
                value={employment}
                onChange={(e) => setEmployment(e.target.value)}
              />
            </label>
          </div>

          {missing.length > 0 ? (
            <p className="text-xs text-muted-foreground">
              Still missing: {missing.join(", ")}. Filling these lets the agent
              answer more form questions.
            </p>
          ) : null}

          <div className="flex items-center gap-3">
            <Button onClick={submit} disabled={saving}>
              {saving ? "Saving…" : "Save application answers"}
            </Button>
            {saved ? (
              <span className="text-xs text-muted-foreground">Saved.</span>
            ) : null}
          </div>
        </CardContent>
      </Card>

      <EeoCard profileId={profileId} eeo={eeo} />
    </div>
  )
}

const EEO_FIELDS: { key: keyof EeoProfile; label: string }[] = [
  { key: "race_ethnicity", label: "Race / ethnicity" },
  { key: "gender", label: "Gender" },
  { key: "disability", label: "Disability status" },
  { key: "veteran_status", label: "Veteran status" },
]

function EeoCard({
  profileId,
  eeo,
}: {
  profileId: string
  eeo: EeoProfile | null
}) {
  const queryClient = useQueryClient()
  const [optIn, setOptIn] = useState(Boolean(eeo?.opt_in))
  const [values, setValues] = useState<Record<string, string>>(() => {
    const initial: Record<string, string> = {}
    for (const { key } of EEO_FIELDS) initial[key] = (eeo?.[key] as string) ?? ""
    return initial
  })

  const save = useMutation({
    mutationFn: () =>
      api.putEeo(profileId, {
        opt_in: optIn,
        ...values,
      } as EeoProfile),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["eeo", profileId] }),
  })
  const remove = useMutation({
    mutationFn: () => api.deleteEeo(profileId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["eeo", profileId] }),
  })

  return (
    <Card>
      <CardHeader>
        <CardTitle>Voluntary self-identification (optional)</CardTitle>
        <CardDescription>
          Never inferred, never used for matching, and only ever filled in by
          you. Leave anything blank or choose "prefer not to answer". You can
          delete this at any time.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={optIn}
            onChange={(e) => setOptIn(e.target.checked)}
          />
          I opt in to providing these details
        </label>
        <div className="grid gap-4 sm:grid-cols-2">
          {EEO_FIELDS.map(({ key, label }) => (
            <label key={key} className={fieldClass}>
              <span className={labelClass}>{label}</span>
              <Input
                disabled={!optIn}
                value={values[key] ?? ""}
                onChange={(e) =>
                  setValues((prev) => ({ ...prev, [key]: e.target.value }))
                }
              />
            </label>
          ))}
        </div>
        <div className="flex items-center gap-3">
          <Button
            variant="outline"
            onClick={() => save.mutate()}
            disabled={save.isPending}
          >
            Save EEO data
          </Button>
          <Button
            variant="ghost"
            onClick={() => remove.mutate()}
            disabled={remove.isPending}
          >
            Delete EEO data
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}