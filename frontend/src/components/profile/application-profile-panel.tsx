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
import { Skeleton } from "@/components/ui/skeleton"
import { WorkPreferencesCard } from "@/components/profile/work-preferences-card"
import { api } from "@/lib/api/endpoints"
import type { ApplicationProfileInput, EeoProfile } from "@/lib/api/types"

/**
 * The answers you confirm (WS-20 · work preferences unified in WS-21 ·
 * context-dependent questions and the gaps UI in WS-45).
 *
 * A résumé is not an application form. It rarely says whether you can work
 * without sponsorship, what salary you want, or how much notice you owe — yet
 * every application asks. This is where you answer once, so the agent can
 * answer for you.
 *
 * The layout follows the design's two screens:
 *
 * - **Questions & privacy** (`20 · Questions & privacy`): the measured gaps
 *   ("Questions that still need you") beside the voluntary EEO card, whose
 *   heading is "Your choice. Never a ranking signal.".
 * - **Application profile** (`11 · Application profile`): the answers form
 *   beside the "Your answers have a clear source." rail.
 *
 * Work authorization is asked **per country** (WS-25c): the boards ask
 * "are you authorized to work in the country you are applying to?", and a
 * single yes/no cannot answer it — authorized in the UK is not authorized in
 * the US. The country list is the primary question; the bare "legally
 * authorized" tri-state is the anywhere-fallback the list narrows. A missing
 * answer stops form filling for a human's review instead of guessing.
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

/** The one read/save pair for the application profile (one query, one key). */
function useApplicationProfile(profileId: string) {
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
  return { query, save }
}

/**
 * Where a measured question gets answered on this screen, by the taxonomy
 * category the gaps endpoint reports.
 *
 * The mapping is the honest one: a category with a corresponding field here
 * gets an "Add answer →"/"Edit answer →" link that focuses that field; a
 * category with **no** field (a candidate's first name, a latitude, a
 * board-specific question) gets no link, because a link that goes nowhere is
 * worse than no link. Those questions are answered on the employer's own
 * form, on the Review screen — never fabricated here.
 */
const FIELD_FOR_CATEGORY: Record<string, string> = {
  total_experience: "field-experience",
  seniority_level: "field-seniority",
  work_authorization: "field-authorization",
  country: "field-work-eligibility-countries",
  visa_sponsorship: "field-sponsorship",
  citizenship_status: "field-citizenship",
  current_salary: "field-current-salary",
  desired_salary: "field-current-salary",
  notice_period: "field-notice",
  portfolio_url: "field-portfolio",
  linkedin_url: "field-linkedin",
}

/** Bring an answers-card field into view and focus it (same screen). */
function focusAnswerField(fieldId: string) {
  const field = document.getElementById(fieldId)
  if (!field) return
  field.scrollIntoView({ behavior: "smooth", block: "center" })
  field.focus({ preventScroll: true })
}

/** Bring the measured-gaps card into view (the rail's review anchor). */
function focusQuestionGaps() {
  const card = document.getElementById("question-gaps")
  if (!card) return
  card.scrollIntoView({ behavior: "smooth", block: "center" })
  card.focus({ preventScroll: true })
}

/**
 * The confirmed answers, without the preferences editor (WS-42).
 *
 * The design file splits the profile's editable half across two tabs —
 * "Work preferences" (the shared editor) and "Application answers" (the
 * facts a form asks for) — and the split is honest here because each half
 * owns its own cards: the preferences editor is `WorkPreferencesCard`, and
 * this panel is the measured question gaps, the application answers and
 * the voluntary self-identification. Both read the same query key, so the
 * two tabs can never disagree about what is stored.
 */
export function ApplicationAnswersPanel({ profileId }: { profileId: string }) {
  const { query, save } = useApplicationProfile(profileId)

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
    <div className="space-y-6">
      {/*
        The questions-and-privacy row (design `20 · Questions & privacy`):
        the measured gaps on the left, the voluntary EEO card in the rail.
      */}
      <div className="grid gap-6 xl:grid-cols-[minmax(0,2fr)_minmax(0,1fr)] xl:items-start">
        {/*
          The programmatic focus target the rail's "Review board questions →"
          lands on. `tabIndex={-1}` keeps it out of the tab order; it is
          focused by script only.
        */}
        <div
          id="question-gaps"
          tabIndex={-1}
          className="min-w-0 focus:outline-none"
        >
          <MeasuredQuestionsCard
            key={`gaps-${profileId}`}
            profileId={profileId}
            onAnswer={focusAnswerField}
          />
        </div>
        <EeoCard key={`eeo-${profileId}`} profileId={profileId} />
      </div>

      {/*
        The application-profile row (design `11 · Application profile`): the
        answers form on the left, the provenance rail on the right.
      */}
      <div className="grid gap-6 xl:grid-cols-[minmax(0,2fr)_minmax(0,1fr)] xl:items-start">
        <div className="min-w-0">
          <ApplicationAnswersCard
            key={`answers-${profileId}`}
            profile={loaded}
            onSave={(body) => save.mutate(body)}
            saving={save.isPending}
          />
        </div>
        <aside className="min-w-0 space-y-3">
          <AnswersSourceCard />
        </aside>
      </div>
    </div>
  )
}

export function ApplicationProfilePanel({ profileId }: { profileId: string }) {
  return (
    <div className="space-y-5">
      <WorkPreferencesCard key={`prefs-${profileId}`} profileId={profileId} />
      <ApplicationAnswersPanel profileId={profileId} />
    </div>
  )
}

/** How a measured gap reads as a chip, in the coverage words the backend uses. */
function GapChip({ coverage }: { coverage: string }) {
  switch (coverage) {
    case "answered":
      return (
        <span className="inline-flex items-center rounded-[6px] bg-lime-soft px-2.5 py-1 text-[11px] leading-4 font-semibold text-lime-foreground">
          Confirmed
        </span>
      )
    case "not_in_profile":
      return (
        <span className="inline-flex items-center rounded-[6px] bg-terracotta-soft px-2.5 py-1 text-[11px] leading-4 font-semibold text-terracotta-foreground">
          Needs answer
        </span>
      )
    case "never_autofill":
      return (
        <span className="inline-flex items-center rounded-[6px] border border-border-surface px-2.5 py-1 text-[11px] leading-4 font-semibold text-muted-foreground">
          Never autofilled
        </span>
      )
    default:
      return (
        <span className="inline-flex items-center rounded-[6px] border border-border-surface px-2.5 py-1 text-[11px] leading-4 font-semibold text-muted-foreground">
          Unclassified
        </span>
      )
  }
}

/**
 * The questions the boards actually ask (WS-25b · gap rows from WS-45).
 *
 * The server measures these from the boards' own published form schemas and
 * ranks them by how many listings ask them. It has **already** excluded the
 * questions the profile answers, the questions that are consent or EEO (never
 * the agent's to answer), and — with `limit=20` — the long tail. So this card
 * renders the response rather than second-guessing it: a re-filter here would
 * be a second opinion about coverage, and the measured one is the honest one.
 *
 * It sits above the answer fields on purpose. A question three boards ask is
 * worth answering before a field nobody has ever asked for. Each gap row
 * carries its own chip (Needs answer / Confirmed / Never autofilled) and —
 * when the category maps onto a field on this screen — a link that focuses
 * that field. Categories with no field here offer no link: those questions
 * are answered on the employer's form at review time, never here.
 */
function MeasuredQuestionsCard({
  profileId,
  onAnswer,
}: {
  profileId: string
  onAnswer?: (fieldId: string) => void
}) {
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
        <CardTitle>Questions that still need you</CardTitle>
        <CardDescription>
          Board-question gaps are prioritized by how often they occur. Answers
          come from you, never a guess.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <ul className="space-y-4">
          {questions.map((question) => {
            const fieldId = FIELD_FOR_CATEGORY[question.category]
            return (
              <li
                key={question.label}
                className="border-b border-border-surface pb-4 last:border-b-0 last:pb-0"
              >
                <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1.5">
                  <span className="text-sm font-semibold text-foreground">
                    {question.label}
                  </span>
                  <span className="flex shrink-0 items-center gap-2">
                    {question.required ? (
                      <span className="inline-flex items-center rounded-[6px] border border-terracotta px-2.5 py-1 text-[11px] leading-4 font-semibold text-terracotta-foreground">
                        Required
                      </span>
                    ) : null}
                    <GapChip coverage={question.coverage} />
                  </span>
                </div>
                <p className="mt-1 text-xs leading-[17px] text-muted-foreground">
                  asked by {question.boards}{" "}
                  {question.boards === 1 ? "board" : "boards"}
                  {" · "}
                  {question.times_seen}{" "}
                  {question.times_seen === 1 ? "listing" : "listings"}
                </p>
                {fieldId && onAnswer ? (
                  <div className="mt-2">
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => onAnswer(fieldId)}
                    >
                      {question.coverage === "answered"
                        ? "Edit answer →"
                        : "Add answer →"}
                    </Button>
                  </div>
                ) : null}
              </li>
            )
          })}
        </ul>
      </CardContent>
    </Card>
  )
}

/**
 * The countries the candidate may work in (WS-25c · the primary
 * authorization question from WS-45).
 *
 * A native multi-select on purpose. The list is long, the values are opaque
 * codes, and the native control gives keyboard selection, type-ahead and the
 * `selectedOptions` semantics that a hand-rolled listbox has to re-earn. The
 * options come from the **API**, which serves them from the same table the
 * write path validates against, so the picker cannot offer a country the model
 * would refuse — a picker with its own copy of the list drifts, and the failure
 * is a validation error on a value the UI just suggested.
 *
 * Empty is a real state: it means "not stated", which is different from "no
 * countries". Nothing here forces a selection, because forcing one would turn
 * an unanswered question into a wrong answer — a missing answer stops form
 * filling for a human's review instead.
 */
function AuthorizedCountries({
  value,
  onChange,
}: {
  value: string[]
  onChange: (countries: string[]) => void
}) {
  const query = useQuery({
    queryKey: ["countries"],
    queryFn: ({ signal }) => api.getCountries(signal),
    // The list is a static reference table, so it does not need refetching on
    // every focus. It is still served by the API rather than inlined, so the
    // console and the model cannot disagree about what a country is.
    staleTime: Infinity,
  })

  // The list is a dependency, not a decoration: rendering an empty picker
  // would look like "your countries are gone" and, worse, a save from that
  // state would clear the stored list. So the control is withheld until the
  // options exist.
  if (query.isPending) {
    return <Skeleton className="h-24 w-full rounded-md" />
  }
  if (query.isError) {
    return (
      <div className={fieldClass}>
        <span className={labelClass}>Work eligibility country</span>
        <ErrorNotice error={query.error} onRetry={() => query.refetch()} />
      </div>
    )
  }

  return (
    <label className={fieldClass}>
      <span className={labelClass}>Work eligibility country</span>
      <select
        data-testid="authorized-countries"
        id="field-work-eligibility-countries"
        multiple
        size={4}
        className="w-full rounded-md border border-input bg-transparent px-2 py-1 text-sm"
        value={value}
        onChange={(e) =>
          onChange(
            Array.from(e.target.selectedOptions).map((option) => option.value)
          )
        }
      >
        {query.data.countries.map((country) => (
          <option key={country.code} value={country.code}>
            {country.name}
          </option>
        ))}
      </select>
      <span className="block text-xs leading-relaxed text-muted-foreground">
        {/*
          The reason the question exists, in the design's words: work
          authorization is asked per country, and a missing answer is a
          stop, not a guess.
        */}
        Choose every country you may work in. A missing answer stops form
        filling instead of guessing.
      </span>
    </label>
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
    authorizationCountries: wa.authorized_countries ?? [],
    sponsorship: tri.from(wa.requires_sponsorship),
    citizenship: wa.citizenship_status ?? "",
    currentSalary: comp.current_salary?.toString() ?? "",
    noticeDays: notice.notice_days?.toString() ?? "",
  })

  const missing = [
    !form.seniority.trim() && "seniority",
    !form.authorized && "legal authorization",
    !form.sponsorship && "visa sponsorship",
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
          // WS-25c: canonical codes, in the order the picker lists them —
          // which is the order the API serves. The list is what makes the
          // authorization answer country-qualified, so it must travel.
          authorized_countries: form.authorizationCountries,
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
              id="field-experience"
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
              id="field-seniority"
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
              id="field-title"
              value={form.title}
              onChange={(e) =>
                setForm((f) => ({ ...f, title: e.target.value }))
              }
            />
          </label>
          <label className={fieldClass}>
            <span className={labelClass}>Portfolio URL</span>
            <Input
              id="field-portfolio"
              value={form.portfolio}
              onChange={(e) =>
                setForm((f) => ({ ...f, portfolio: e.target.value }))
              }
            />
          </label>
          <label className={fieldClass}>
            <span className={labelClass}>LinkedIn URL</span>
            <Input
              id="field-linkedin"
              value={form.linkedin}
              onChange={(e) =>
                setForm((f) => ({ ...f, linkedin: e.target.value }))
              }
            />
          </label>
        </div>

        {/*
          Work authorization, asked the way the boards ask it (WS-25c): per
          country first, the anywhere statement second.
        */}
        <div className="grid gap-4 sm:grid-cols-2">
          <div className="sm:col-span-2">
            <AuthorizedCountries
              value={form.authorizationCountries}
              onChange={(countries) =>
                setForm((f) => ({ ...f, authorizationCountries: countries }))
              }
            />
          </div>
          <label className={fieldClass}>
            <span className={labelClass}>Legally authorized to work?</span>
            <select
              id="field-authorization"
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
            <span className="block text-xs leading-relaxed text-muted-foreground">
              {/*
                WS-25c's exact semantics: the list narrows; the bare boolean
                is the statement about anywhere; neither goes to a human.
              */}
              The anywhere fallback: with no countries listed above, this
              answers for any country. When countries are listed, the list
              decides.
            </span>
          </label>
          <label className={fieldClass}>
            <span className={labelClass}>Citizenship / status (optional)</span>
            <Input
              id="field-citizenship"
              value={form.citizenship}
              onChange={(e) =>
                setForm((f) => ({ ...f, citizenship: e.target.value }))
              }
            />
          </label>
          {/*
            Sponsorship is its own question and is **never inferred** — not
            from the country list, and not from eligibility. Unanswered, the
            field wears the terracotta the design gives a required question.
          */}
          <div className="sm:col-span-2">
            <label className={fieldClass}>
              <span className={labelClass}>Need visa sponsorship?</span>
              <select
                id="field-sponsorship"
                className={
                  "h-9 w-full rounded-md border bg-transparent px-3 text-sm " +
                  (form.sponsorship
                    ? "border-input"
                    : "border-terracotta text-terracotta-foreground")
                }
                value={form.sponsorship}
                onChange={(e) =>
                  setForm((f) => ({ ...f, sponsorship: e.target.value as Tri }))
                }
              >
                <option value="">Select an answer</option>
                <option value="yes">Yes, now or later</option>
                <option value="no">No</option>
              </select>
              <span
                className={
                  "block text-xs leading-relaxed " +
                  (form.sponsorship
                    ? "text-muted-foreground"
                    : "text-terracotta-foreground")
                }
              >
                This answer is required. It is never inferred from your résumé.
              </span>
            </label>
          </div>
          <label className={fieldClass}>
            <span className={labelClass}>Current salary (optional)</span>
            <Input
              id="field-current-salary"
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
              id="field-notice"
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

/**
 * The provenance rail (design `11 · Application profile`, node `47:374`).
 *
 * The rule that makes the form safe: parsed résumé facts and confirmed
 * employer answers are separate, and a missing answer stops form filling
 * instead of triggering a guess. The "Review board questions →" action is an
 * anchor, not a route: the gaps card is on this same screen, above the form.
 */
function AnswersSourceCard() {
  return (
    <section className="flex min-w-0 flex-col gap-3 rounded-surface bg-forest-soft p-[18px]">
      <h2 className="text-[20px] leading-[29px] font-semibold text-primary">
        Your answers have a clear source.
      </h2>
      <p className="text-sm leading-relaxed text-muted-foreground">
        Parsed résumé facts and your confirmed employer answers are separate. A
        missing answer stops form filling instead of triggering a guess.
      </p>
      <p className="text-xs text-muted-foreground">
        Required fields are labeled. Tab moves between fields. Enter selects an
        option. Escape dismisses a popup.
      </p>
      <div>
        <Button variant="ghost" size="sm" onClick={focusQuestionGaps}>
          Review board questions →
        </Button>
      </div>
    </section>
  )
}

const EEO_FIELDS: { key: keyof EeoProfile; label: string }[] = [
  { key: "race_ethnicity", label: "Race / ethnicity" },
  { key: "gender", label: "Gender" },
  { key: "disability", label: "Disability status" },
  { key: "veteran_status", label: "Veteran status" },
]

/**
 * Voluntary self-identification (WS-20 · restyled from WS-45).
 *
 * The design's card leads with what this data **is** — "VOLUNTARY ·
 * SEPARATE", "Your choice. Never a ranking signal." — because the reader has
 * to know, before they type anything, that these answers are opt-in, stored
 * apart from the application profile, never inferred from the résumé, never
 * used to rank jobs, and deletable at any time.
 *
 * The fields are disclosed by "Manage voluntary answers" rather than always
 * on show: an account that has opted out should see the state ("Off · no
 * answers saved") and the delete action, not an empty form.
 */
function EeoCard({ profileId }: { profileId: string }) {
  const queryClient = useQueryClient()
  const query = useQuery({
    queryKey: ["eeo", profileId],
    queryFn: ({ signal }) => api.getEeo(profileId, signal),
  })
  const eeo = query.data?.eeo
  const [optIn, setOptIn] = useState<boolean | null>(null)
  const [values, setValues] = useState<Record<string, string> | null>(null)
  /*
    The editor is open when the account has already opted in, and closed
    otherwise — with an explicit override once the operator opens or closes
    it themselves. Derived, not reset by an effect, so the read and the
    disclosure can never disagree.
  */
  const [managingOverride, setManagingOverride] = useState<boolean | null>(null)
  const managing = managingOverride ?? Boolean(eeo?.opt_in)

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
    <Card data-testid="voluntary-answers">
      <CardHeader className="space-y-1.5">
        <p className="text-[11px] font-semibold tracking-[0.08em] text-muted-foreground uppercase">
          Voluntary · Separate
        </p>
        <CardTitle>Your choice. Never a ranking signal.</CardTitle>
        <CardDescription>
          EEO answers are opt-in, stored separately, and never used to rank
          jobs.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div>
          {/*
            The chip reads the **stored** state (the server's answer), not
            the editor's: what has been saved is a fact, and a checkbox mid
            edit does not change it. Saving refetches, and the chip moves.
          */}
          <span
            data-testid="eeo-state"
            className="inline-flex items-center rounded-[6px] border border-border-surface bg-card px-2.5 py-1 text-[11px] leading-4 font-semibold text-foreground"
          >
            {eeo?.opt_in ? "On · answers stored" : "Off · no answers saved"}
          </span>
        </div>
        <p className="text-sm leading-relaxed text-muted-foreground">
          You can inspect, change, or delete voluntary answers independently of
          your application profile.
        </p>

        {managing ? (
          <div className="space-y-4 border-t border-border-surface pt-4">
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
                {save.isPending ? "Saving…" : "Save"}
              </Button>
              <Button
                variant="ghost"
                onClick={() => setManagingOverride(false)}
              >
                Done
              </Button>
            </div>
          </div>
        ) : null}

        <div className="flex items-center gap-3">
          {!managing ? (
            <Button onClick={() => setManagingOverride(true)}>
              Manage voluntary answers
            </Button>
          ) : null}
          <Button
            variant="outline"
            onClick={() => remove.mutate()}
            disabled={remove.isPending}
          >
            {remove.isPending ? "Deleting…" : "Delete answers"}
          </Button>
        </div>

        {remove.isError ? <ErrorNotice error={remove.error} /> : null}

        <p className="text-xs leading-relaxed text-muted-foreground">
          Only supported work-eligibility countries are selectable. Missing
          employer answers stop execution for your review.
        </p>
      </CardContent>
    </Card>
  )
}
