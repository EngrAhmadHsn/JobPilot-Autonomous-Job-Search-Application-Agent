import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useState } from "react"

import { CardSkeleton } from "@/components/common/card-skeleton"
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
import { WorkPreferencesCard } from "@/components/profile/work-preferences-card"
import { api } from "@/lib/api/endpoints"
import type { ApplicationProfileInput, EeoProfile } from "@/lib/api/types"

/**
 * The answers you confirm (WS-20; work preferences unified in WS-21).
 *
 * A résumé is not an application form. It rarely says whether you can work
 * without sponsorship, what salary you want, or how much notice you owe — yet
 * every application asks. This is where you answer once, so the agent can
 * answer for you.
 *
 * Three cards, in the order they matter:
 *
 * 1. **Work preferences** — the shared editor (the Résumé page shows the
 *    same one), so both pages always agree.
 * 2. **Application answers** — the facts a form asks for. Work authorization,
 *    sponsorship and citizenship are three separate questions, because they
 *    are three separate answers.
 * 3. **Voluntary self-identification** — never inferred, never used for
 *    matching, and deletable.
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
      queryClient.invalidateQueries({
        queryKey: ["application-profile", profileId],
      }),
  })

  if (query.isPending) {
    // The shape of the answer, not the word "Loading": this panel is a card of
    // labelled fields, so the bones copy that layout and the page does not jump.
    return <CardSkeleton rows={4} />
  }
  if (query.isError) {
    return <ErrorNotice error={query.error} onRetry={() => query.refetch()} />
  }

  const loaded = query.data.application_profile as ApplicationProfileInput
  return (
    <div className="space-y-5">
      <WorkPreferencesCard key={`prefs-${profileId}`} profileId={profileId} />
      <MeasuredQuestionsCard key={`gaps-${profileId}`} profileId={profileId} />
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

/**
 * The questions the boards actually ask (WS-25b).
 *
 * The server measures these from the boards' own published form schemas and
 * ranks them by how many listings ask them. It has **already** excluded the
 * questions the profile answers, the questions that are consent or EEO (never
 * the agent's to answer), and — with `limit=20` — the long tail. So this card
 * renders the response rather than second-guessing it: a re-filter here would
 * be a second opinion about coverage, and the measured one is the honest one.
 *
 * It sits above the guessed answer fields on purpose. A question three boards
 * ask is worth answering before a field nobody has ever asked for.
 */
function MeasuredQuestionsCard({ profileId }: { profileId: string }) {
  const query = useQuery({
    queryKey: ["question-gaps", profileId],
    queryFn: ({ signal }) => api.getQuestionGaps(profileId, signal),
  })

  const questions = query.data?.questions ?? []
  // No measurement is not an error state to announce: a corpus with no
  // published schema (or a board that timed out — the endpoint fails soft)
  // simply has nothing measured to show, and the panel keeps the layout it
  // had. A failed query *is* silent too — the gaps are a prompt, not a
  // source of truth, and an error notice here would offer a retry for a
  // panel the user can already read.
  if (query.isError || questions.length === 0) {
    return null
  }

  return (
    <Card data-testid="measured-questions">
      <CardHeader>
        <CardTitle>Questions the boards actually ask</CardTitle>
        <CardDescription>
          Measured from the application forms the boards publish. Most-asked
          first — answering one that every board asks removes a question from
          every future application.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <ul className="space-y-2">
          {questions.map((question) => (
            <li
              key={question.label}
              className="flex flex-wrap items-baseline gap-x-2 gap-y-1"
            >
              <span className="text-sm font-medium">{question.label}</span>
              {question.required ? (
                <span className="rounded-full bg-terracotta-soft px-2 py-0.5 text-[11px] font-medium text-terracotta">
                  required
                </span>
              ) : null}
              <span className="text-xs text-muted-foreground">
                asked by {question.boards}{" "}
                {question.boards === 1 ? "board" : "boards"}
                {" · "}
                {question.times_seen}{" "}
                {question.times_seen === 1 ? "listing" : "listings"}
              </span>
            </li>
          ))}
        </ul>
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
              onChange={(e) =>
                setForm((f) => ({ ...f, years: e.target.value }))
              }
            />
          </label>
          <label className={fieldClass}>
            <span className={labelClass}>Seniority</span>
            <Input
              placeholder="senior, lead, mid…"
              value={form.seniority}
              onChange={(e) =>
                setForm((f) => ({ ...f, seniority: e.target.value }))
              }
            />
          </label>
          <label className={fieldClass}>
            <span className={labelClass}>Current title</span>
            <Input
              value={form.title}
              onChange={(e) =>
                setForm((f) => ({ ...f, title: e.target.value }))
              }
            />
          </label>
          <label className={fieldClass}>
            <span className={labelClass}>Portfolio URL</span>
            <Input
              value={form.portfolio}
              onChange={(e) =>
                setForm((f) => ({ ...f, portfolio: e.target.value }))
              }
            />
          </label>
          <label className={fieldClass}>
            <span className={labelClass}>LinkedIn URL</span>
            <Input
              value={form.linkedin}
              onChange={(e) =>
                setForm((f) => ({ ...f, linkedin: e.target.value }))
              }
            />
          </label>
        </div>

        <div className="grid gap-4 sm:grid-cols-2">
          <label className={fieldClass}>
            <span className={labelClass}>Authorized to work here?</span>
            <select
              className="h-9 w-full rounded-md border border-input bg-transparent px-3 text-sm"
              value={form.authorized}
              onChange={(e) =>
                setForm((f) => ({ ...f, authorized: e.target.value as Tri }))
              }
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
              onChange={(e) =>
                setForm((f) => ({ ...f, sponsorship: e.target.value as Tri }))
              }
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
              onChange={(e) =>
                setForm((f) => ({ ...f, citizenship: e.target.value }))
              }
            />
          </label>
          <label className={fieldClass}>
            <span className={labelClass}>Current salary (optional)</span>
            <Input
              inputMode="numeric"
              value={form.currentSalary}
              onChange={(e) =>
                setForm((f) => ({ ...f, currentSalary: e.target.value }))
              }
            />
          </label>
          <label className={fieldClass}>
            <span className={labelClass}>
              Notice period (days; 0 = immediate)
            </span>
            <Input
              inputMode="numeric"
              value={form.noticeDays}
              onChange={(e) =>
                setForm((f) => ({ ...f, noticeDays: e.target.value }))
              }
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
    Object.fromEntries(
      EEO_FIELDS.map(({ key }) => [key, (eeo?.[key] as string) ?? ""])
    )

  const save = useMutation({
    mutationFn: () =>
      api.putEeo(profileId, {
        opt_in: effectiveOptIn,
        ...currentValues,
      } as EeoProfile),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ["eeo", profileId] }),
  })
  const remove = useMutation({
    mutationFn: () => api.deleteEeo(profileId),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ["eeo", profileId] }),
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
          <Button
            variant="outline"
            onClick={() => save.mutate()}
            disabled={save.isPending}
          >
            Save
          </Button>
          <Button
            variant="ghost"
            onClick={() => remove.mutate()}
            disabled={remove.isPending}
          >
            Delete this data
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}
