import { zodResolver } from "@hookform/resolvers/zod"
import { useMutation, useQuery } from "@tanstack/react-query"
import { useFieldArray, useForm, useWatch } from "react-hook-form"
import { useEffect, useRef, useState } from "react"
import { z } from "zod"

import { Banner } from "@/components/common/banner"
import { ErrorNotice } from "@/components/common/error-notice"
import { DocumentPicker } from "@/components/documents/document-picker"
import { FieldList } from "@/components/common/field-list"
import { PageHeader, Section } from "@/components/common/page-header"
import { PlainText } from "@/components/common/plain-text"
import { StatusBadge, StatusExplainer } from "@/components/common/status-badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Input } from "@/components/ui/input"

import { apiUrl } from "@/lib/api/client"
import { api } from "@/lib/api/endpoints"
import { formatList } from "@/lib/format"
import { useCurrentProfileId } from "@/lib/profile"
import { asString, asStringArray } from "@/lib/safe"
import type { ApprovalDecisionResponse } from "@/lib/api/types"

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
      <div className="grid gap-5 sm:grid-cols-2">{children}</div>
    </section>
  )
}

/** The result of a decision, with the evidence that came with it. */
function DecisionResult({
  result,
  applicationId,
}: {
  result: ApprovalDecisionResponse
  applicationId: string | null
}) {
  const metadata = result.metadata ?? {}
  const questions = asStringArray(metadata.questions)
  const errors = asStringArray(metadata.errors)
  const challenge = asString(metadata.challenge)
  const evidence = result.evidence
  // The evidence object is a free-form dictionary on the wire, so every value
  // is read through the safe accessors.
  const screenshotPath = asString(evidence?.screenshot_path)
  const separator = Math.max(
    screenshotPath.lastIndexOf("/"),
    screenshotPath.lastIndexOf(String.fromCharCode(92))
  )
  const screenshotName =
    separator >= 0 ? screenshotPath.slice(separator + 1) : screenshotPath

  return (
    <Card className="rounded-2xl">
      <CardContent className="space-y-4 pt-6">
        <div className="flex flex-wrap items-center gap-3">
          <h2 className="font-heading text-lg font-semibold tracking-tight text-foreground">
            The decision
          </h2>
          <StatusBadge status={result.status} />
        </div>

        <StatusExplainer status={result.status} />

        <Banner
          tone={result.success ? "success" : "warning"}
          title={
            result.success
              ? "The application was submitted"
              : "The application was not submitted"
          }
        >
          <PlainText as="span">{result.message}</PlainText>
        </Banner>

        {questions.length > 0 ? (
          <div className="space-y-1">
            <h3 className="text-sm font-medium text-foreground">
              The form asked questions the evidence does not answer
            </h3>
            <ul className="list-disc space-y-1 pl-5 text-sm text-muted-foreground">
              {questions.map((question) => (
                <li key={question}>
                  <PlainText as="span">{question}</PlainText>
                </li>
              ))}
            </ul>
          </div>
        ) : null}

        {errors.length > 0 ? (
          <div className="space-y-1">
            <h3 className="text-sm font-medium text-foreground">
              The server refused the form
            </h3>
            <ul className="list-disc space-y-1 pl-5 text-sm text-muted-foreground">
              {errors.map((error) => (
                <li key={error}>
                  <PlainText as="span">{error}</PlainText>
                </li>
              ))}
            </ul>
          </div>
        ) : null}

        {challenge ? (
          <Banner tone="warning" title="The flow stopped at a challenge">
            <p>
              The page presented{" "}
              <code className="font-mono text-[11px]">{challenge}</code>.
              Nothing was submitted and nothing was bypassed — complete it by
              hand.
            </p>
          </Banner>
        ) : null}

        {evidence ? (
          <div className="space-y-2">
            <h3 className="text-sm font-medium text-foreground">Evidence</h3>
            <FieldList
              items={[
                { label: "URL", value: asString(evidence.url) || "—" },
                {
                  label: "Confirmation",
                  value: asString(evidence.confirmation_text) ? (
                    <PlainText as="span">
                      {asString(evidence.confirmation_text)}
                    </PlainText>
                  ) : (
                    "—"
                  ),
                },
                {
                  label: "Evidence status",
                  value: asString(evidence.status) || "—",
                },
                { label: "Screenshot", value: screenshotPath || "—" },
                { label: "Trace", value: asString(evidence.trace_path) || "—" },
              ]}
            />

            {screenshotPath && applicationId && screenshotName ? (
              <figure className="space-y-1">
                <img
                  src={apiUrl(
                    `/api/applications/${encodeURIComponent(applicationId)}/evidence/${encodeURIComponent(screenshotName)}`
                  )}
                  alt="The screenshot captured as evidence of the submission"
                  className="max-w-full rounded-xl border border-border"
                />
                <figcaption className="text-xs text-muted-foreground">
                  The screenshot the browser captured at the moment of the
                  outcome.
                </figcaption>
              </figure>
            ) : null}
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">
            The result carried no evidence. Nothing is claimed on the strength
            of this decision.
          </p>
        )}
      </CardContent>
    </Card>
  )
}

/**
 * The Approvals screen.
 *
 * This is the screen the whole product exists for. It does two things, in
 * this order and never the other way round:
 *
 * 1. it **prepares** an application, which persists the exact payload that
 *    would be submitted, and shows the operator that payload's summary;
 * 2. it records a **human decision** on that prepared record.
 *
 * There is no other way to reach a submission from this console: the
 * approve button is the only irreversible control, it is disabled while the
 * call is in flight, and no optimistic "submitted" is ever shown.
 */
export function ApprovalsScreen() {
  const profileId = useCurrentProfileId()
  const [applicationId, setApplicationId] = useState<string | null>(null)

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
  })

  const prepared = prepare.data

  return (
    <div className="space-y-10">
      <PageHeader
        title="Prepare an application"
        description="Preparing builds the payload, checks the target and stores it. Nothing reaches the employer until a person approves it, and approving runs the payload exactly as it is stored here."
      />

      <div className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_320px] lg:items-start">
        <form
          className="space-y-5"
          onSubmit={prepareForm.handleSubmit((values) =>
            prepare.mutate(values)
          )}
        >
          <FormSection
            title="Job details"
            description="Where the application will go. The server checks the host against its allowlist before anything else."
          >
            <Field
              id="job_title"
              label="Job title"
              error={prepareForm.formState.errors.job_title?.message}
            >
              <Input id="job_title" {...prepareForm.register("job_title")} />
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
            description="The details the form will be filled with. They come from your saved profile unless you change them."
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
          </FormSection>
        </form>

        {/*
          The panel sticks below the header — the header's height is
          published as `--header-height` and measured, so the panel is never
          cut off by it. A panel taller than the space it sticks in scrolls
          inside itself rather than under the viewport edge.
        */}
        <aside className="lg:sticky lg:top-[calc(var(--header-height,7rem)+1rem)]">
          <div className="space-y-4">
            {prepared ? (
              <>
                <Card className="rounded-2xl border-forest/20 bg-forest-soft">
                  <CardContent className="space-y-4 pt-6">
                    <div className="flex flex-wrap items-center gap-2">
                      <h2 className="font-heading text-base font-semibold tracking-tight text-forest">
                        What will be submitted
                      </h2>
                      <StatusBadge status={prepared.status} />
                    </div>
                    <p className="text-sm font-medium text-forest">
                      Nothing has been submitted yet.
                    </p>
                    <p className="text-sm leading-relaxed text-forest/80">
                      The payload below was stored by the server. Approving
                      executes exactly this payload — it is not rebuilt from the
                      form.
                    </p>

                    <FieldList
                      items={[
                        {
                          label: "Job",
                          value: prepared.prepared_summary.job_title,
                        },
                        {
                          label: "Company",
                          value: prepared.prepared_summary.company_name,
                        },
                        {
                          label: "Job URL",
                          value: prepared.prepared_summary.job_url,
                        },
                        {
                          label: "Adapter",
                          value: prepared.prepared_summary.adapter_name,
                        },
                        {
                          label: "Form fields",
                          value: formatList(
                            prepared.prepared_summary.field_names
                          ),
                        },
                        {
                          label: "Profile facts the agent may use",
                          value: formatList(
                            prepared.prepared_summary.profile_fact_names
                          ),
                        },
                        {
                          label: "Résumé path",
                          value: prepared.prepared_summary.resume_path ?? "—",
                        },
                        {
                          label: "Manual review",
                          value: prepared.prepared_summary
                            .requires_manual_review
                            ? "The form needs a human to complete it"
                            : "No",
                        },
                        { label: "Approval id", value: prepared.approval_id },
                        {
                          label: "Tracked application",
                          value: prepared.application_id ?? "—",
                        },
                      ]}
                    />

                    <form
                      className="space-y-4 border-t border-forest/15 pt-4"
                      onSubmit={decisionForm.handleSubmit((values) =>
                        decide.mutate({
                          approvalId: prepared.approval_id,
                          values,
                          action: "approve",
                        })
                      )}
                    >
                      <div className="grid gap-4">
                        <p className="text-sm text-muted-foreground">
                          The decision is recorded against your account, with
                          the time.
                        </p>
                        <Field id="reason" label="Reason" optional>
                          <Input
                            id="reason"
                            {...decisionForm.register("reason")}
                          />
                        </Field>
                      </div>

                      <div className="flex flex-wrap gap-2">
                        <Button
                          type="button"
                          variant="outline"
                          disabled={decide.isPending}
                          onClick={() =>
                            decisionForm.handleSubmit((values) =>
                              decide.mutate({
                                approvalId: prepared.approval_id,
                                values,
                                action: "reject",
                              })
                            )()
                          }
                        >
                          Reject
                        </Button>
                        <Button
                          type="submit"
                          variant="destructive"
                          disabled={decide.isPending}
                        >
                          {decide.isPending
                            ? "Deciding…"
                            : "Approve and submit"}
                        </Button>
                      </div>

                      <p className="text-xs leading-relaxed text-forest/70">
                        Approving fills the form in a real browser and submits
                        it to {prepared.prepared_summary.job_url}. It cannot be
                        taken back.
                      </p>
                    </form>

                    {decide.isError ? (
                      <ErrorNotice error={decide.error} />
                    ) : null}
                  </CardContent>
                </Card>
              </>
            ) : (
              <Card className="rounded-2xl lg:max-h-[calc(100vh-var(--header-height,7rem)-2rem)] lg:overflow-y-auto">
                <CardContent className="space-y-4 pt-6">
                  <h2 className="font-heading text-base font-semibold tracking-tight text-foreground">
                    Before you prepare
                  </h2>
                  <p className="text-sm leading-relaxed text-muted-foreground">
                    Preparing checks the target domain, builds the payload and
                    stores it as an approval request. It does not contact the
                    employer, and it does not submit anything — that takes a
                    separate, human decision.
                  </p>
                  <Button
                    type="button"
                    size="lg"
                    className="w-full"
                    disabled={prepare.isPending}
                    onClick={prepareForm.handleSubmit((values) =>
                      prepare.mutate(values)
                    )}
                  >
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
                </CardContent>
              </Card>
            )}
          </div>
        </aside>
      </div>

      {decide.data ? (
        <Section title="The result">
          <DecisionResult result={decide.data} applicationId={applicationId} />
        </Section>
      ) : null}
    </div>
  )
}
