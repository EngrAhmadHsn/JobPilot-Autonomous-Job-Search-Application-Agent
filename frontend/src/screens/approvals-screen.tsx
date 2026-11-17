import { zodResolver } from "@hookform/resolvers/zod"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useFieldArray, useForm, useWatch } from "react-hook-form"
import { useCallback, useEffect, useRef, useState } from "react"
import { z } from "zod"

import { ErrorNotice } from "@/components/common/error-notice"
import { DocumentPicker } from "@/components/documents/document-picker"
import { FieldList } from "@/components/common/field-list"
import { PageHeader, Section } from "@/components/common/page-header"
import { StatusBadge } from "@/components/common/status-badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
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
} from "@/screens/review/in-control-notice"
import { PackageChecklist } from "@/screens/review/package-checklist"
import { QuestionCard } from "@/screens/review/question-card"
import {
  clearApprovalMirror,
  readApprovalMirror,
  writeApprovalMirror,
  type ApprovalMirror,
} from "@/screens/review/use-approval-mirror"

/**
 * The review-and-approval screen — the human-approval boundary.
 *
 * This is the screen the whole product exists for. It does two things, in
 * this order and never the other way round:
 *
 * 1. it **prepares** an application, which persists the exact payload that
 *    would be submitted, and shows the operator that payload;
 * 2. it records a **human decision** on that prepared record.
 *
 * The composition is the reference panel's (WS-38): the in-control notice,
 * the Application Package checklist, the board's own questions, the stored
 * packet's facts, and the approve action — with honest state language
 * throughout. Approving answers `202` with a run id: it queues durable
 * work, it does not submit, and every label on this screen says so.
 *
 * There is no other way to reach a submission from this console: the
 * approve control is the only irreversible one, it sits behind a
 * confirmation dialog, it is disabled while the call is in flight, and no
 * optimistic "submitted" is ever shown. After a reload the screen re-reads
 * the stored decision from `GET /api/applications/approvals/{id}` (the
 * localStorage mirror only remembers *which* id to ask about), so the
 * persisted truth survives the reload that empties React Query.
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
    <section className="rounded-2xl border border-border bg-card p-6">
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

export function ApprovalsScreen() {
  const profileId = useCurrentProfileId()
  const queryClient = useQueryClient()
  const [applicationId, setApplicationId] = useState<string | null>(null)
  const [dialog, setDialog] = useState<"approve" | "reject" | null>(null)
  /** True while the operator edits the form with a decision already recorded. */
  const [editing, setEditing] = useState(false)

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
  const coverLetterProvided = Boolean(prepare.variables?.cover_letter?.trim())
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

  return (
    <div className="space-y-10">
      <PageHeader
        title="Review your application"
        description="Preparing checks the target and stores exactly what will be sent. Your approval is the boundary nothing crosses on its own: approving sends the stored packet you see, not a fresh version."
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

      <div className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_320px] lg:items-start">
        <div className="min-w-0 space-y-6">
          {prepared ? (
            <Card className="rounded-2xl">
              <CardContent className="space-y-5 pt-6">
                <div className="flex flex-wrap items-center gap-3">
                  <h2 className="font-heading text-lg font-semibold tracking-tight text-foreground">
                    What will be submitted
                  </h2>
                  <StatusBadge status={packetStatus} />
                </div>
                <p className="text-sm leading-relaxed text-muted-foreground">
                  Nothing has been submitted yet. The payload below was stored
                  by the server — approving executes exactly this payload; it is
                  not rebuilt from the form.
                </p>

                <InControlNotice adapterName={prepared.adapter_name} />

                {/*
                  The two cards share a row when there are board questions to
                  read beside the checklist; with no measured form (the
                  fail-soft path) the checklist spans the column alone rather
                  than leaving an empty half next to it.
                */}
                <div
                  className={
                    questions.length > 0
                      ? "grid items-start gap-4 xl:grid-cols-2"
                      : "grid items-start gap-4"
                  }
                >
                  <PackageChecklist
                    summary={prepared.prepared_summary}
                    questions={questions}
                    customFieldCount={
                      customFieldValues.filter(
                        (field) => field.key.trim() && field.value.trim()
                      ).length
                    }
                    coverLetterProvided={coverLetterProvided}
                  />
                  <QuestionCard questions={questions} blockers={blockers} />
                </div>

                <div className="rounded-xl border border-border bg-card/60 p-3.5">
                  <h3 className="font-heading text-sm font-semibold tracking-tight text-foreground">
                    The stored payload
                  </h3>
                  <p className="mt-0.5 mb-2 text-xs leading-relaxed text-muted-foreground">
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
                      <Input id="reason" {...decisionForm.register("reason")} />
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
              </CardContent>
            </Card>
          ) : (
            <form
              className="space-y-5"
              onSubmit={prepareForm.handleSubmit((values) =>
                prepare.mutate(values)
              )}
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
                    type="email"
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
        </div>

        {/*
          The panel sticks below the header — the header's height is
          published as `--header-height` and measured, so the panel is never
          cut off by it. A panel taller than the space it sticks in scrolls
          inside itself rather than under the viewport edge.
        */}
        <aside className="lg:sticky lg:top-[calc(var(--header-height,7rem)+1rem)]">
          <div className="space-y-4">
            <ControlPanel />
            {prepared ? (
              <Card className="rounded-2xl">
                <CardContent className="space-y-3 pt-6">
                  <h2 className="font-heading text-sm font-semibold tracking-tight text-foreground">
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
                </CardContent>
              </Card>
            ) : (
              <Card className="rounded-2xl lg:max-h-[calc(100vh-var(--header-height,7rem)-2rem)] lg:overflow-y-auto">
                <CardContent className="space-y-4 pt-6">
                  <h2 className="font-heading text-sm font-semibold tracking-tight text-foreground">
                    Before you prepare
                  </h2>
                  <p className="text-sm leading-relaxed text-muted-foreground">
                    Preparing checks the target domain, builds the payload and
                    stores it as an approval request. It does not contact the
                    employer, and it does not submit anything — that takes a
                    separate, human decision, and approving queues durable work
                    rather than submitting.
                  </p>
                </CardContent>
              </Card>
            )}
          </div>
        </aside>
      </div>

      {decided ? (
        <Section
          title="The result"
          description="What the decision response reported, with the evidence that came with it."
        >
          <DecisionResult result={decided} applicationId={applicationId} />
        </Section>
      ) : null}
    </div>
  )
}
