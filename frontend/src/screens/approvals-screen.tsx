import { zodResolver } from "@hookform/resolvers/zod"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useFieldArray, useForm, useWatch } from "react-hook-form"
import { CircleAlert, FileText, Lock, ScrollText, User } from "lucide-react"
import { useCallback, useEffect, useRef, useState } from "react"
import { z } from "zod"

import { ErrorNotice } from "@/components/common/error-notice"
import { DocumentPicker } from "@/components/documents/document-picker"
import { FieldList } from "@/components/common/field-list"
import { PageHeader } from "@/components/ui/page-header"
import { StatusBadge } from "@/components/common/status-badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"

import { ApiError } from "@/lib/api/client"
import { api } from "@/lib/api/endpoints"
import { formatList } from "@/lib/format"
import { useCurrentProfileId } from "@/lib/profile"

import { ApprovalStateBanner } from "@/screens/review/approval-state-banner"
import { DecisionResult } from "@/screens/review/decision-result"
import { DecideDialog } from "@/screens/review/decide-dialog"
import {
  ControlPanel,
  InControlNotice,
  isLocalTestBoard,
} from "@/screens/review/in-control-notice"
import { QuestionCard } from "@/screens/review/question-card"
import {
  clearApprovalMirror,
  readApprovalMirror,
  writeApprovalMirror,
  type ApprovalMirror,
} from "@/screens/review/use-approval-mirror"

/**
 * The review-and-approval screen — the human-approval boundary, rebuilt to
 * the design file's screen `16:122` (WS-42).
 *
 * This is the screen the whole product exists for. It does two things, in
 * this order and never the other way round:
 *
 * 1. it **prepares** an application, which persists the exact payload that
 *    would be submitted, and shows the operator that payload;
 * 2. it records a **human decision** on that prepared record.
 *
 * The composition is the design's: the flow stepper (`49:1033`), the
 * prepared-application packet as a paper card (`49:1050`) whose document
 * rows carry the real stored values, the sage approval boundary
 * (`49:1092`), and the question queue (`49:1096`) beside a clay
 * not-ready panel (`49:1125`).
 *
 * Two deliberate departures, both because the console renders real data the
 * design's example never had to carry:
 *
 * - **No per-question save.** The design's question card offers radio
 *   options and "Save answer". The backend has no per-answer persistence —
 *   an answer exists only as a custom field inside a freshly prepared
 *   payload — so the queue shows the board's own ordered list with each
 *   answer's source, and the clay panel's action routes the operator into
 *   the prepare form with the question's field **prefilled**, which is the
 *   one way an answer actually becomes part of the payload.
 * - **Approve stays available with blockers.** The design implies a hard
 *   gate; the product's own behavior is safer than a hard gate: the queued
 *   run stops at the questions the profile does not answer and hands them
 *   back, rather than guessing (WS-32). The clay panel says both things.
 *
 * Approving answers `202` with a run id: it queues durable work, it does
 * not submit, and every label on this screen says so. There is no other way
 * to reach a submission from this console: the approve control is the only
 * irreversible one, it sits behind a confirmation dialog, it is disabled
 * while the call is in flight, and no optimistic "submitted" is ever shown.
 * After a reload the screen re-reads the stored decision from
 * `GET /api/applications/approvals/{id}` (the localStorage mirror only
 * remembers *which* id to ask about), so the persisted truth survives the
 * reload that empties React Query.
 */

/**
 * The prepare form.
 *
 * The rules are the backend's rules: a job title, a company, a job URL on
 * the allowlist, and a candidate. The client-side validation exists to give
 * the operator a fast answer; the server's 400 is the authority.
 */
const prepareSchema = z.object({
  job_title: z.string().min(1, "The job title is required"),
  company_name: z.string().min(1, "The company name is required"),
  job_url: z
    .string()
    .min(1, "The job URL is required")
    .url("The job URL must be a full URL"),
  candidate_name: z.string().min(1, "The candidate name is required"),
  email: z
    .string()
    .min(1, "The email address is required")
    .email("The email address must be valid"),
  phone: z.string().min(1, "The phone number is required"),
  resume_path: z.string().optional(),
  cover_letter: z.string().optional(),
  custom_fields: z.array(z.object({ key: z.string(), value: z.string() })),
})

type PrepareForm = z.infer<typeof prepareSchema>

/**
 * The decision form: why.
 *
 * **There is no approver field** (WS-14). The approver is the
 * authenticated principal, so asking the operator to type a name would
 * collect a value the server ignores — and would suggest that the name
 * is what gets recorded, which is no longer true. The decision is
 * attributed to the account the operator is signed in as.
 */
const decisionSchema = z.object({
  reason: z.string().optional(),
})

type DecisionForm = z.infer<typeof decisionSchema>

/** The design's ghost action pill (nodes `49:1053` / `49:1064`). */
const GHOST_PILL =
  "inline-flex h-9 shrink-0 items-center rounded-lg px-3.5 py-2 text-[13px] font-semibold leading-[19px] text-primary transition-colors outline-none hover:bg-accent focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"

/** The hairline the design draws between a packet card's sections. */
function Divider() {
  return <div className="h-px w-full shrink-0 bg-border-surface" aria-hidden />
}

/** A labelled form control with its validation message. */
function Field({
  id,
  label,
  hint,
  optional,
  error,
  children,
}: {
  id: string
  label: string
  hint?: string
  optional?: boolean
  error?: string
  children: React.ReactNode
}) {
  return (
    <div className="space-y-1.5">
      <div className="flex items-baseline gap-2">
        <label htmlFor={id} className="text-sm font-medium text-foreground">
          {label}
        </label>
        {optional ? (
          <span className="rounded-full border border-border px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground">
            optional
          </span>
        ) : null}
      </div>
      {children}
      {hint ? (
        <p className="text-xs leading-relaxed text-muted-foreground">{hint}</p>
      ) : null}
      {error ? <p className="text-xs text-destructive">{error}</p> : null}
    </div>
  )
}

/** A group of fields in the form. */
function FormSection({
  title,
  description,
  children,
}: {
  title: string
  description: string
  children: React.ReactNode
}) {
  return (
    <section className="rounded-surface border border-border-surface bg-card p-6">
      <h2 className="font-heading text-base font-semibold tracking-tight text-foreground">
        {title}
      </h2>
      <p className="mt-1 mb-5 max-w-[60ch] text-sm leading-relaxed text-muted-foreground">
        {description}
      </p>
      {/*
        `grid-cols-1` is load-bearing: Tailwind's `minmax(0, 1fr)` lets the
        track shrink below its content's min-content width, which the
        DocumentPicker's nowrap metadata needs at 390 px. The implicit
        `auto` track (no explicit template) sizes to min-content and pushed
        the form past the viewport.
      */}
      <div className="grid grid-cols-1 gap-5 sm:grid-cols-2">{children}</div>
    </section>
  )
}

/**
 * One row of the prepared packet (design `49:1057`): icon, eyebrow, the
 * stored value, its provenance, and a **Show** toggle that reveals the
 * exact stored content.
 *
 * The design's rows carry "Preview →" / "Read →" / "View →" actions. The
 * console has no document-preview route to send those to, and a control
 * that opens nothing is a lie — so the affordance is an inline reveal of
 * the real stored bytes/text instead, which is what the operator actually
 * needs to check before authorizing.
 */
function PacketRow({
  icon: Icon,
  eyebrow,
  title,
  sub,
  detail,
}: {
  icon: typeof FileText
  eyebrow: string
  title: string
  sub: string
  /** The exact stored content the toggle reveals, when there is any. */
  detail?: React.ReactNode
}) {
  const [open, setOpen] = useState(false)
  return (
    <div className="min-w-0">
      <div className="flex items-center gap-3">
        <Icon
          className="size-5 shrink-0 text-forest/70"
          strokeWidth={1.7}
          aria-hidden
        />
        <div className="min-w-0 flex-1 space-y-0.5">
          <p className="text-[11px] font-semibold leading-4 text-muted-foreground">
            {eyebrow}
          </p>
          <p className="text-sm font-semibold leading-5 text-primary">
            {title}
          </p>
          <p className="text-xs leading-[17px] text-muted-foreground">{sub}</p>
        </div>
        {detail ? (
          <button
            type="button"
            aria-expanded={open}
            onClick={() => setOpen((value) => !value)}
            className={GHOST_PILL}
          >
            {open ? "Hide" : "Show →"}
          </button>
        ) : null}
      </div>
      {open && detail ? (
        <div className="mt-2.5 rounded-xl border border-border-surface bg-card/60 p-3 text-xs text-muted-foreground">
          {detail}
        </div>
      ) : null}
    </div>
  )
}

/** The review packet's stored facts, as label/value pairs. */
function PacketFacts({
  summary,
  approvalId,
  applicationId,
}: {
  summary: {
    job_title: string
    company_name: string
    job_url: string
    adapter_name: string
    field_names?: string[]
  }
  approvalId: string
  applicationId: string | null
}) {
  return (
    <FieldList
      items={[
        { label: "Job", value: summary.job_title },
        { label: "Company", value: summary.company_name },
        {
          label: "Job URL",
          value: (
            <span className="font-mono text-[11px] wrap-anywhere">
              {summary.job_url}
            </span>
          ),
        },
        { label: "Adapter", value: summary.adapter_name },
        {
          label: "Form fields",
          value: formatList(summary.field_names),
        },
        {
          label: "Approval id",
          value: <span className="font-mono text-[11px]">{approvalId}</span>,
        },
        {
          label: "Tracked application",
          value: applicationId ? (
            <span className="font-mono text-[11px]">{applicationId}</span>
          ) : (
            "—"
          ),
        },
      ]}
    />
  )
}

/**
 * The application flow, as the design numbers it (`49:1033`): Evaluate on
 * Discover, Prepare here, Review & approve here, Employer handoff after a
 * recorded approval. The active step is derived from the packet's real
 * state — a rejected or expired decision sends the reader back to Prepare,
 * because that is genuinely where they are.
 */
function ApprovalStepper({ active }: { active: 1 | 2 | 3 | 4 }) {
  const steps = [
    "Evaluate",
    "Prepare",
    "Review & approve",
    "Employer handoff",
  ] as const
  return (
    <ol
      aria-label="The application flow"
      className="flex flex-wrap items-center gap-2.5"
    >
      {steps.map((label, index) => {
        const n = index + 1
        const isActive = n === active
        return (
          <li
            key={label}
            className="flex items-center gap-2.5"
            aria-current={isActive ? "step" : undefined}
          >
            {isActive ? (
              <span className="inline-flex h-[37px] items-center rounded-lg bg-primary px-3.5 py-2 text-[13px] font-semibold leading-[19px] text-primary-foreground">
                {n} {label}
              </span>
            ) : (
              <span className="inline-flex items-center rounded-[6px] bg-forest-soft px-2.5 py-1 text-[11px] font-semibold leading-4 text-primary">
                {n} {label}
              </span>
            )}
            {index < steps.length - 1 ? (
              <span
                aria-hidden
                className="inline-flex items-center rounded-[6px] bg-forest-soft px-2.5 py-1 text-[11px] font-semibold leading-4 text-primary"
              >
                →
              </span>
            ) : null}
          </li>
        )
      })}
    </ol>
  )
}

export function ApprovalsScreen() {
  const profileId = useCurrentProfileId()
  const queryClient = useQueryClient()
  const [applicationId, setApplicationId] = useState<string | null>(null)
  const [dialog, setDialog] = useState<"approve" | "reject" | null>(null)
  /** True while the operator edits the form with a decision already recorded. */
  const [editing, setEditing] = useState(false)

  /*
    What the operator actually submitted, captured at prepare time. The
    prepare response stores the payload but does not echo the candidate's
    own text fields back, and the packet's document rows show the stored
    values — so the submit handler keeps them here.
  */
  const [submitted, setSubmitted] = useState<{
    candidate_name: string
    email: string
    phone: string
    cover_letter: string
    resume_path: string
  } | null>(null)

  /*
    The pointer to the approval the console last worked on. It survives a
    reload; the state it points at is always re-read from the server below.
  */
  const [mirror, setMirrorState] = useState<ApprovalMirror | null>(
    readApprovalMirror
  )
  // Stable: it reads nothing but the state setter and module functions, so
  // effects can depend on it honestly.
  const updateMirror = useCallback(
    (updater: (prev: ApprovalMirror | null) => ApprovalMirror | null) => {
      setMirrorState((prev) => {
        const next = updater(prev)
        if (next) {
          writeApprovalMirror(next)
        } else {
          clearApprovalMirror()
        }
        return next
      })
    },
    []
  )

  const prepareForm = useForm<PrepareForm>({
    resolver: zodResolver(prepareSchema),
    defaultValues: {
      job_title: "",
      company_name: "",
      job_url: "",
      candidate_name: "",
      email: "",
      phone: "",
      resume_path: "",
      cover_letter: "",
      custom_fields: [],
    },
  })
  const customFields = useFieldArray({
    control: prepareForm.control,
    name: "custom_fields",
  })
  const resumePath =
    useWatch({ control: prepareForm.control, name: "resume_path" }) ?? ""
  const customFieldValues =
    useWatch({ control: prepareForm.control, name: "custom_fields" }) ?? []

  const decisionForm = useForm<DecisionForm>({
    resolver: zodResolver(decisionSchema),
    defaultValues: { reason: "" },
  })

  // The saved profile prefills the candidate's details, so the operator
  // does not retype what the agent already knows. The values are only
  // written once, and only into fields that are still empty.
  const prefilled = useRef(false)
  const storedProfile = useQuery({
    queryKey: ["profile", profileId],
    queryFn: ({ signal }) => api.getResume(profileId as string, signal),
    enabled: Boolean(profileId),
  })
  useEffect(() => {
    const profile = storedProfile.data?.profile
    if (!profile || prefilled.current) return
    prefilled.current = true
    const info = profile.personal_information
    const values = {
      candidate_name: info.name,
      email: info.email,
      phone: info.phone,
    }
    for (const [field, value] of Object.entries(values)) {
      if (!value) continue
      if (!prepareForm.getValues(field as keyof PrepareForm)) {
        prepareForm.setValue(field as keyof PrepareForm, value)
      }
    }
  }, [storedProfile.data, prepareForm])

  /*
    The persisted decision, re-read from the server. The mirror supplies the
    id; the GET supplies the truth. A 404 means the pointer names an
    approval this account does not own (or that no longer exists): the dead
    pointer is cleared in storage and the screen falls back to the prepare
    form, rather than showing an error the operator cannot act on. The
    clearing happens in the query's own callback — an event handler, not an
    effect — and the banner's visibility derives from the same answer.
  */
  const approvalState = useQuery({
    queryKey: ["approval-state", mirror?.approval_id],
    queryFn: async ({ signal }) => {
      try {
        return await api.getApproval(mirror!.approval_id, signal)
      } catch (error) {
        if (error instanceof ApiError && error.status === 404) {
          clearApprovalMirror()
        }
        throw error
      }
    },
    enabled: Boolean(mirror),
    retry: false,
  })
  const approvalMissing =
    approvalState.error instanceof ApiError &&
    approvalState.error.status === 404

  const prepare = useMutation({
    mutationFn: (values: PrepareForm) =>
      api.prepareApplication({
        job_title: values.job_title,
        company_name: values.company_name,
        job_url: values.job_url,
        candidate_name: values.candidate_name,
        email: values.email,
        phone: values.phone,
        resume_path: values.resume_path?.trim()
          ? values.resume_path.trim()
          : undefined,
        cover_letter: values.cover_letter?.trim()
          ? values.cover_letter
          : undefined,
        custom_fields: Object.fromEntries(
          values.custom_fields
            .filter((field) => field.key.trim() && field.value.trim())
            .map((field) => [field.key.trim(), field.value])
        ),
        profile_id: profileId ?? undefined,
      }),
    onSuccess: (result) => {
      setApplicationId(result.application_id ?? null)
      setEditing(false)
      // The new approval becomes the pointer; the GET below re-reads its
      // (pending) state from the server, which is what makes the banner
      // and any reload agree.
      updateMirror(() => ({
        approval_id: result.approval_id,
        application_id: result.application_id ?? null,
        run_id: null,
      }))
      void queryClient.invalidateQueries({
        queryKey: ["approval-state", result.approval_id],
      })
    },
  })

  const decide = useMutation({
    mutationFn: ({
      approvalId,
      values,
      action,
    }: {
      approvalId: string
      values: DecisionForm
      action: "approve" | "reject"
    }) =>
      action === "approve"
        ? api.approve(approvalId, { reason: values.reason })
        : api.reject(approvalId, { reason: values.reason }),
    onSuccess: (result) => {
      setDialog(null)
      // The run id only exists on the 202 response; record it beside the
      // pointer so a reload can show it labelled as what was queued. The
      // decision itself is re-read from the GET.
      updateMirror((prev) =>
        prev ? { ...prev, run_id: result.run_id ?? prev.run_id } : prev
      )
      void queryClient.invalidateQueries({
        queryKey: ["approval-state", result.approval_id],
      })
    },
    onError: () => {
      // A refusal (already decided, expired, gone job, busy queue) is shown
      // in the packet; the dialog has nothing more to wait for.
      setDialog(null)
    },
  })

  const prepared = prepare.data
  const decided = decide.data
  const blockers = prepared?.blocking_questions ?? []
  const questions = prepared?.form_questions ?? []
  const coverLetterProvided = Boolean(submitted?.cover_letter?.trim())
  /*
    The packet's status badge shows the approval row's **persisted** state
    once a decision has been recorded (the GET was invalidated and answers
    `approved`/`rejected`), not the prepare response's frozen `awaiting_
    approval` snapshot. Before a decision the two agree; after one, the
    server's word wins.
  */
  const packetStatus =
    prepared &&
    approvalState.data &&
    approvalState.data.approval_id === prepared.approval_id &&
    decided
      ? approvalState.data.status
      : (prepared?.status ?? null)

  /*
    The stepper's active step, derived from the packet's real state.
  */
  const stepperActive: 1 | 2 | 3 | 4 = !prepared
    ? 2
    : packetStatus === "approved"
      ? 4
      : packetStatus === "rejected" || packetStatus === "expired"
        ? 2
        : 3

  /** The needs-a-human count the clay panel and the queue both report. */
  const needsHumanCount = blockers.length

  /**
   * Route the operator into the prepare form with the first blocking
   * question's field prefilled as a custom field — the one way an answer
   * actually becomes part of a prepared payload.
   */
  const answerBlockers = () => {
    const first = questions.find((question) => blockers.includes(question.label))
    const key = first?.fields?.[0] ?? blockers[0]
    prepare.reset()
    decide.reset()
    setEditing(true)
    const existing = prepareForm.getValues("custom_fields")
    if (key && !existing.some((field) => field.key === key)) {
      customFields.append({ key, value: "" })
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="One last look. Your decision."
        description="Review the exact packet before you authorize the next step."
      />

      {/*
        The persisted approval state, read back from the server. It renders
        when the review panel is not open — after a reload, or while the
        operator re-prepares — so the decision survives what React Query
        does not. While the packet is open, the panel and the result below
        carry the state.
      */}
      {!prepared && mirror && approvalState.isError && !approvalMissing ? (
        <ErrorNotice
          error={approvalState.error}
          onRetry={() => void approvalState.refetch()}
        />
      ) : null}
      {!prepared &&
      mirror &&
      !approvalMissing &&
      approvalState.data &&
      !(editing && approvalState.data.status === "pending") ? (
        <ApprovalStateBanner state={approvalState.data} runId={mirror.run_id} />
      ) : null}

      <ApprovalStepper active={stepperActive} />

      <div className="grid gap-6 xl:grid-cols-[minmax(0,2fr)_minmax(0,1fr)] xl:items-start">
        <div className="min-w-0 space-y-3">
          {prepared ? (
            <section className="flex min-w-0 flex-col gap-3.5 rounded-surface border border-border-surface bg-card p-5">
              <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                What will be submitted
              </p>
              <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
                <div className="flex min-w-0 flex-wrap items-center gap-2.5">
                  <h2 className="text-[20px] font-semibold leading-[29px] text-primary">
                    {prepared.prepared_summary.job_title}
                  </h2>
                  <StatusBadge status={packetStatus} />
                </div>
                <a
                  href={prepared.prepared_summary.job_url}
                  target="_blank"
                  rel="noreferrer"
                  className={GHOST_PILL}
                >
                  Open listing ↗
                </a>
              </div>
              <p className="text-[13px] leading-[19px] text-muted-foreground">
                {[
                  prepared.prepared_summary.company_name,
                  prepared.prepared_summary.adapter_name,
                  isLocalTestBoard(prepared.prepared_summary.adapter_name)
                    ? "Local test board"
                    : "Real-board assist",
                ].join(" · ")}
              </p>
              <p className="max-w-prose text-sm leading-relaxed text-muted-foreground">
                Nothing has been submitted yet. The payload below was stored
                by the server — approving executes exactly this payload; it is
                not rebuilt from the form.
              </p>

              {prepared.prepared_summary.requires_manual_review ? (
                <p className="flex items-center gap-2 text-sm text-terracotta-foreground">
                  <CircleAlert className="size-4 shrink-0" aria-hidden />
                  This form needs a human to complete it.
                </p>
              ) : null}

              <Divider />

              <PacketRow
                icon={FileText}
                eyebrow="Résumé"
                title={
                  prepared.prepared_summary.resume_path
                    ? prepared.prepared_summary.resume_path.replace(
                        /^.*[/\\]/,
                        ""
                      )
                    : "None stored with the payload"
                }
                sub={
                  prepared.prepared_summary.resume_path
                    ? "The file the run will upload, stored with the payload"
                    : "Nothing was attached to this packet"
                }
                detail={
                  prepared.prepared_summary.resume_path ? (
                    <code className="block break-all font-mono text-[11px]">
                      {prepared.prepared_summary.resume_path}
                    </code>
                  ) : undefined
                }
              />

              <Divider />

              <PacketRow
                icon={ScrollText}
                eyebrow="Cover letter"
                title={coverLetterProvided ? "Provided" : "None provided"}
                sub={
                  coverLetterProvided
                    ? "Draft · stored with the payload as text"
                    : "Not provided — the form submits without one"
                }
                detail={
                  coverLetterProvided && submitted ? (
                    submitted.cover_letter
                  ) : undefined
                }
              />

              <Divider />

              <PacketRow
                icon={User}
                eyebrow="Candidate details"
                title="Name, email, contact number"
                sub="What the form will fill — from your profile unless you changed it"
                detail={
                  submitted ? (
                    <ul className="space-y-1">
                      <li>
                        <span className="font-medium text-foreground">
                          Name:
                        </span>{" "}
                        {submitted.candidate_name}
                      </li>
                      <li>
                        <span className="font-medium text-foreground">
                          Email:
                        </span>{" "}
                        {submitted.email}
                      </li>
                      <li>
                        <span className="font-medium text-foreground">
                          Phone:
                        </span>{" "}
                        {submitted.phone}
                      </li>
                    </ul>
                  ) : undefined
                }
              />

              <Divider />

              <PacketRow
                icon={FileText}
                eyebrow="Profile facts the agent may use"
                title={
                  formatList(prepared.prepared_summary.profile_fact_names) ||
                  "None"
                }
                sub="The payload's own allow-list of facts, stored with the packet"
                detail={
                  <code className="block break-all font-mono text-[11px]">
                    {formatList(prepared.prepared_summary.field_names)}
                  </code>
                }
              />

              {customFieldValues.filter((field) => field.key.trim()).length >
              0 ? (
                <>
                  <Divider />
                  <PacketRow
                    icon={FileText}
                    eyebrow="Answers you provided"
                    title={`${customFieldValues.filter((field) => field.key.trim()).length} custom field(s) typed into the prepare form`}
                    sub="Submitted with the payload as the form's extra answers"
                  />
                </>
              ) : null}

              {questions.length > 0 ? (
                <>
                  <Divider />
                  <div className="flex flex-wrap items-center gap-2.5">
                    <span className="inline-flex items-center rounded-[6px] bg-forest-soft px-2.5 py-1 text-[11px] font-semibold leading-4 text-primary">
                      {questions.filter(
                        (question) =>
                          !blockers.includes(question.label) &&
                          question.verdict === "answerable"
                      ).length}{" "}
                      of {questions.length} answers confirmed
                    </span>
                    <button
                      type="button"
                      onClick={() =>
                        document
                          .getElementById("board-questions")
                          ?.scrollIntoView({ block: "start" })
                      }
                      className={GHOST_PILL}
                    >
                      View all questions →
                    </button>
                  </div>
                </>
              ) : null}

              <Divider />

              <div className="space-y-1">
                <h3 className="text-sm font-semibold text-foreground">
                  The stored payload
                </h3>
                <p className="text-xs leading-relaxed text-muted-foreground">
                  What the run will receive, as the server stored it.
                </p>
                <PacketFacts
                  summary={prepared.prepared_summary}
                  approvalId={prepared.approval_id}
                  applicationId={prepared.application_id ?? null}
                />
              </div>

              {blockers.length > 0 ? (
                <p className="text-sm leading-relaxed text-terracotta-foreground">
                  Approving now queues the run; it will stop at the{" "}
                  {blockers.length} question
                  {blockers.length === 1 ? "" : "s"} the profile does not
                  answer and hand them to you, rather than guess.
                </p>
              ) : null}

              {decided ? (
                <p className="text-sm text-muted-foreground">
                  Decision recorded — the result is below.
                </p>
              ) : (
                <div className="space-y-4 border-t border-border pt-5">
                  <p className="text-sm text-muted-foreground">
                    The decision is recorded against your account, with the
                    time.
                  </p>
                  <Field id="reason" label="Reason" optional>
                    <Input
                      id="reason"
                      {...decisionForm.register("reason")}
                    />
                  </Field>

                  <div className="flex flex-wrap gap-2">
                    <Button
                      type="button"
                      disabled={decide.isPending}
                      onClick={() => setDialog("approve")}
                    >
                      Approve &amp; continue
                    </Button>
                    <Button
                      type="button"
                      variant="outline"
                      disabled={decide.isPending}
                      onClick={() => setDialog("reject")}
                    >
                      Reject
                    </Button>
                    <Button
                      type="button"
                      variant="ghost"
                      disabled={decide.isPending}
                      onClick={() => {
                        prepare.reset()
                        decide.reset()
                        setEditing(true)
                      }}
                    >
                      Edit application
                    </Button>
                  </div>

                  {/*
                    The URL is the one thing here that can be long without
                    a space. `wrap-anywhere`, not `break-words`: a URL is a
                    single token, and `break-word` only breaks inside a box
                    that has already sized itself to that token's full
                    width.
                  */}
                  <p className="text-xs leading-relaxed wrap-anywhere text-muted-foreground">
                    Approving queues the run against{" "}
                    <span className="font-mono text-[11px]">
                      {prepared.prepared_summary.job_url}
                    </span>
                    . The decision cannot be taken back once recorded.
                  </p>

                  <DecideDialog
                    action={dialog}
                    jobLabel={`${prepared.prepared_summary.job_title} at ${prepared.prepared_summary.company_name}`}
                    jobUrl={prepared.prepared_summary.job_url}
                    pending={decide.isPending}
                    onAction={() =>
                      decisionForm.handleSubmit((values) =>
                        decide.mutate({
                          approvalId: prepared.approval_id,
                          values,
                          action: dialog ?? "approve",
                        })
                      )()
                    }
                    onDismiss={() => setDialog(null)}
                  />

                  {decide.isError ? (
                    <ErrorNotice error={decide.error} />
                  ) : null}
                </div>
              )}
            </section>
          ) : (
            <form
              className="space-y-5"
              onSubmit={prepareForm.handleSubmit((values) => {
                setSubmitted({
                  candidate_name: values.candidate_name,
                  email: values.email,
                  phone: values.phone,
                  cover_letter: values.cover_letter ?? "",
                  resume_path: values.resume_path ?? "",
                })
                prepare.mutate(values)
              })}
            >
              <FormSection
                title="Job details"
                description="Where the application will go. This deployment may only prepare for hosts it is allowed to use."
              >
                <Field
                  id="job_title"
                  label="Job title"
                  error={prepareForm.formState.errors.job_title?.message}
                >
                  <Input
                    id="job_title"
                    {...prepareForm.register("job_title")}
                  />
                </Field>
                <Field
                  id="company_name"
                  label="Company"
                  error={prepareForm.formState.errors.company_name?.message}
                >
                  <Input
                    id="company_name"
                    {...prepareForm.register("company_name")}
                  />
                </Field>
                <div className="sm:col-span-2">
                  <Field
                    id="job_url"
                    label="Job URL"
                    error={prepareForm.formState.errors.job_url?.message}
                  >
                    <Input
                      id="job_url"
                      placeholder="https://boards.greenhouse.io/..."
                      {...prepareForm.register("job_url")}
                    />
                  </Field>
                </div>
              </FormSection>

              <FormSection
                title="Candidate information"
                description="These are the details the form will be filled with. They come from your saved profile unless you change them."
              >
                <Field
                  id="candidate_name"
                  label="Candidate name"
                  error={prepareForm.formState.errors.candidate_name?.message}
                >
                  <Input
                    id="candidate_name"
                    {...prepareForm.register("candidate_name")}
                  />
                </Field>
                <Field
                  id="email"
                  label="Email"
                  error={prepareForm.formState.errors.email?.message}
                >
                  <Input
                    id="email"
                    {...prepareForm.register("email")}
                  />
                </Field>
                <Field
                  id="phone"
                  label="Phone"
                  error={prepareForm.formState.errors.phone?.message}
                >
                  <Input id="phone" {...prepareForm.register("phone")} />
                </Field>
              </FormSection>

              <FormSection
                title="Documents and custom fields"
                description="The résumé is one of your own documents — the one you uploaded, or one the agent tailored for a job. A cover letter is optional, and custom fields are the questions the employer's form asks that the agent cannot answer from your profile."
              >
                <div className="sm:col-span-2">
                  <DocumentPicker
                    value={resumePath}
                    onChange={(path) =>
                      prepareForm.setValue("resume_path", path, {
                        shouldDirty: true,
                      })
                    }
                  />
                </div>
                <Field
                  id="cover_letter"
                  label="Cover letter"
                  optional
                  hint="Text the form will submit as-is."
                >
                  <Input
                    id="cover_letter"
                    {...prepareForm.register("cover_letter")}
                  />
                </Field>

                <div className="space-y-2 sm:col-span-2">
                  <span className="text-sm font-medium text-foreground">
                    Custom form fields
                  </span>
                  {customFields.fields.map((field, index) => (
                    <div key={field.id} className="flex gap-2">
                      <Input
                        placeholder="Field name"
                        aria-label={`Custom field ${index + 1} name`}
                        value={customFieldValues[index]?.key ?? ""}
                        onChange={(event) =>
                          prepareForm.setValue(
                            `custom_fields.${index}.key`,
                            event.target.value,
                            {
                              shouldDirty: true,
                            }
                          )
                        }
                      />
                      <Input
                        placeholder="Value"
                        aria-label={`Custom field ${index + 1} value`}
                        value={customFieldValues[index]?.value ?? ""}
                        onChange={(event) =>
                          prepareForm.setValue(
                            `custom_fields.${index}.value`,
                            event.target.value,
                            {
                              shouldDirty: true,
                            }
                          )
                        }
                      />
                      <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        onClick={() => customFields.remove(index)}
                      >
                        Remove
                      </Button>
                    </div>
                  ))}
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={() => customFields.append({ key: "", value: "" })}
                  >
                    Add a field
                  </Button>
                </div>

                <div className="space-y-3 sm:col-span-2">
                  <Button type="submit" size="lg" disabled={prepare.isPending}>
                    {prepare.isPending ? "Preparing…" : "Prepare application"}
                  </Button>
                  {prepare.isPending ? (
                    <div className="space-y-2">
                      <p className="text-sm text-foreground">
                        Checking the target and building the payload…
                      </p>
                      <div className="agent-progress h-1.5 w-full rounded-full" />
                    </div>
                  ) : null}
                  {prepare.isError ? (
                    <ErrorNotice error={prepare.error} />
                  ) : null}
                </div>
              </FormSection>
            </form>
          )}

          {prepared ? (
            <InControlNotice
              adapterName={prepared.prepared_summary.adapter_name}
            />
          ) : null}
        </div>

        {/*
          The question column is the design's right rail (`49:1095`): the
          queue, the clay not-ready panel, then the ids the rest of the
          console refers to. It sticks below the header — the header's
          height is published as `--header-height` and measured, so the
          rail is never cut off by it.
        */}
        <aside className="min-w-0 space-y-3 xl:sticky xl:top-[calc(var(--header-height,7rem)+1rem)]">
          {prepared ? (
            <>
              <QuestionCard questions={questions} blockers={blockers} />

              {needsHumanCount > 0 ? (
                <section className="flex flex-col gap-2.5 rounded-surface bg-terracotta-soft p-[18px]">
                  <div className="flex items-center gap-2">
                    <Lock
                      className="size-4 shrink-0 text-terracotta-foreground"
                      aria-hidden
                    />
                    <h2 className="text-[15px] font-semibold leading-snug text-terracotta-foreground">
                      Not ready to authorize
                    </h2>
                  </div>
                  <p className="text-sm leading-relaxed text-terracotta-foreground">
                    {needsHumanCount} answer
                    {needsHumanCount === 1 ? "" : "s"} need
                    {needsHumanCount === 1 ? "s" : ""} a human. Approving now
                    queues a run that stops at them and hands them back to
                    you rather than guessing — or answer them in the prepare
                    form first, which is the only way an answer becomes part
                    of the payload.
                  </p>
                  <div>
                    <button
                      type="button"
                      onClick={answerBlockers}
                      className="inline-flex h-8 items-center rounded-lg bg-card/80 px-3 text-[13px] font-semibold text-terracotta-foreground transition-colors outline-none hover:bg-card focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
                    >
                      Answer in the prepare form →
                    </button>
                  </div>
                </section>
              ) : null}

              <section className="flex flex-col gap-2 rounded-surface border border-border-surface bg-card p-5">
                <h2 className="text-sm font-semibold text-foreground">
                  The review record
                </h2>
                <p className="text-xs leading-relaxed text-muted-foreground">
                  The ids everything else refers to: the approval this
                  decision is recorded on, the tracked application it belongs
                  to.
                </p>
                <FieldList
                  items={[
                    {
                      label: "Approval",
                      value: (
                        <span className="font-mono text-[11px]">
                          {prepared.approval_id}
                        </span>
                      ),
                    },
                    {
                      label: "Status",
                      value: <StatusBadge status={packetStatus} />,
                    },
                    {
                      label: "Application",
                      value: prepared.application_id ? (
                        <span className="font-mono text-[11px]">
                          {prepared.application_id}
                        </span>
                      ) : (
                        "—"
                      ),
                    },
                    { label: "Adapter", value: prepared.adapter_name },
                  ]}
                />
              </section>
            </>
          ) : (
            <section className="flex flex-col gap-2 rounded-surface border border-border-surface bg-card p-5">
              <h2 className="text-sm font-semibold text-foreground">
                Before you prepare
              </h2>
              <p className="text-sm leading-relaxed text-muted-foreground">
                Preparing checks the target domain, builds the payload and
                stores it as an approval request. It does not contact the
                employer, and it does not submit anything — that takes a
                separate, human decision, and approving queues durable work
                rather than submitting.
              </p>
            </section>
          )}

          <ControlPanel />
        </aside>
      </div>

      {decided ? (
        <section className="space-y-3">
          <h2 className="type-section">The result</h2>
          <p className="max-w-[62ch] text-sm leading-relaxed text-muted-foreground">
            What the decision response reported, with the evidence that came
            with it.
          </p>
          <DecisionResult result={decided} applicationId={applicationId} />
        </section>
      ) : null}
    </div>
  )
}
