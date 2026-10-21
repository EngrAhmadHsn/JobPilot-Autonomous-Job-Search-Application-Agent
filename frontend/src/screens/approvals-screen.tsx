import { zodResolver } from "@hookform/resolvers/zod"
import { useMutation } from "@tanstack/react-query"
import { useFieldArray, useForm, useWatch } from "react-hook-form"
import { useState } from "react"
import { z } from "zod"

import { Banner } from "@/components/common/banner"
import { ErrorNotice } from "@/components/common/error-notice"
import { FieldList, SectionTitle } from "@/components/common/field-list"
import { PlainText } from "@/components/common/plain-text"
import { EmptyState, ProgressState } from "@/components/common/progress-state"
import { StatusBadge, StatusExplainer } from "@/components/common/status-badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
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

/** The decision form: who decided, and why. */
const decisionSchema = z.object({
  approver: z.string().min(1, "The approver's name is required"),
  reason: z.string().optional(),
})

type DecisionForm = z.infer<typeof decisionSchema>

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
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          The decision
          <StatusBadge status={result.status} />
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
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
            <SectionTitle>
              The form asked questions the evidence does not answer
            </SectionTitle>
            <ul className="list-disc space-y-1 pl-5 text-sm">
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
            <SectionTitle>The server refused the form</SectionTitle>
            <ul className="list-disc space-y-1 pl-5 text-sm">
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
            <SectionTitle>Evidence</SectionTitle>
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
                  className="max-w-full rounded-lg border border-border"
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
  const customFieldValues =
    useWatch({ control: prepareForm.control, name: "custom_fields" }) ?? []

  const decisionForm = useForm<DecisionForm>({
    resolver: zodResolver(decisionSchema),
    defaultValues: { approver: "", reason: "" },
  })

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
        ? api.approve(approvalId, {
            approver: values.approver,
            reason: values.reason,
          })
        : api.reject(approvalId, {
            approver: values.approver,
            reason: values.reason,
          }),
  })

  const prepared = prepare.data

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>Prepare an application</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <p className="text-sm text-muted-foreground">
            Preparing does <strong>not</strong> submit anything. It checks the
            target, builds the payload and stores it, so that the payload the
            approver reviews is exactly the payload that will be executed.
          </p>

          <form
            className="grid gap-3 sm:grid-cols-2"
            onSubmit={prepareForm.handleSubmit((values) =>
              prepare.mutate(values)
            )}
          >
            <Field
              label="Job title"
              error={prepareForm.formState.errors.job_title?.message}
            >
              <Input id="job_title" {...prepareForm.register("job_title")} />
            </Field>
            <Field
              label="Company"
              error={prepareForm.formState.errors.company_name?.message}
            >
              <Input
                id="company_name"
                {...prepareForm.register("company_name")}
              />
            </Field>
            <Field
              label="Job URL"
              error={prepareForm.formState.errors.job_url?.message}
            >
              <Input
                id="job_url"
                placeholder="https://boards.greenhouse.io/..."
                {...prepareForm.register("job_url")}
              />
            </Field>
            <Field
              label="Candidate name"
              error={prepareForm.formState.errors.candidate_name?.message}
            >
              <Input
                id="candidate_name"
                {...prepareForm.register("candidate_name")}
              />
            </Field>
            <Field
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
              label="Phone"
              error={prepareForm.formState.errors.phone?.message}
            >
              <Input id="phone" {...prepareForm.register("phone")} />
            </Field>
            <Field label="Resume path (optional)">
              <Input
                id="resume_path"
                placeholder="A path on the server, inside its own data directory"
                {...prepareForm.register("resume_path")}
              />
            </Field>
            <Field label="Cover letter (optional)">
              <Input
                id="cover_letter"
                {...prepareForm.register("cover_letter")}
              />
            </Field>

            <div className="space-y-2 sm:col-span-2">
              <SectionTitle>Custom form fields</SectionTitle>
              {customFields.fields.map((field, index) => (
                <div key={field.id} className="flex gap-2">
                  <Input
                    placeholder="Field name"
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

            <div className="sm:col-span-2">
              <Button type="submit" disabled={prepare.isPending}>
                {prepare.isPending ? "Preparing…" : "Prepare for approval"}
              </Button>
            </div>
          </form>

          {prepare.isPending ? (
            <ProgressState key="prepare" title="Preparing the application" />
          ) : null}

          {prepare.isError ? <ErrorNotice error={prepare.error} /> : null}
        </CardContent>
      </Card>

      {prepared ? (
        <Card>
          <CardHeader>
            <CardTitle>What will be submitted</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <Banner tone="info" title="Nothing has been submitted yet">
              <p>
                The payload below was stored by the server. Approving executes
                exactly this payload — it is not rebuilt from the form.
              </p>
            </Banner>

            <FieldList
              items={[
                { label: "Job", value: prepared.prepared_summary.job_title },
                {
                  label: "Company",
                  value: prepared.prepared_summary.company_name,
                },
                { label: "Job URL", value: prepared.prepared_summary.job_url },
                {
                  label: "Adapter",
                  value: prepared.prepared_summary.adapter_name,
                },
                {
                  label: "Form fields",
                  value: formatList(prepared.prepared_summary.field_names),
                },
                {
                  label: "Profile facts the agent may use",
                  value: formatList(
                    prepared.prepared_summary.profile_fact_names
                  ),
                },
                {
                  label: "Resume path",
                  value: prepared.prepared_summary.resume_path ?? "—",
                },
                {
                  label: "Manual review",
                  value: prepared.prepared_summary.requires_manual_review
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
              className="grid gap-3 sm:grid-cols-[1fr_2fr_auto] sm:items-end"
              onSubmit={decisionForm.handleSubmit((values) =>
                decide.mutate({
                  approvalId: prepared.approval_id,
                  values,
                  action: "approve",
                })
              )}
            >
              <Field
                label="Approver"
                error={decisionForm.formState.errors.approver?.message}
              >
                <Input
                  id="approver"
                  placeholder="Your name"
                  {...decisionForm.register("approver")}
                />
              </Field>
              <Field label="Reason (optional)">
                <Input id="reason" {...decisionForm.register("reason")} />
              </Field>
              <div className="flex gap-2">
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
                  {decide.isPending ? "Deciding…" : "Approve and submit"}
                </Button>
              </div>
            </form>

            <Banner
              tone="danger"
              title="Approving submits the application to the employer"
            >
              <p>
                This is the one irreversible step in the console. The browser
                will fill the form and submit it to{" "}
                {prepared.prepared_summary.job_url}. It cannot be taken back.
              </p>
            </Banner>

            {decide.isError ? <ErrorNotice error={decide.error} /> : null}
          </CardContent>
        </Card>
      ) : (
        <EmptyState
          title="Nothing prepared yet"
          description="Prepare an application to see exactly what would be submitted, and to record a decision on it."
        />
      )}

      {decide.data ? (
        <DecisionResult result={decide.data} applicationId={applicationId} />
      ) : null}
    </div>
  )
}

/** A labelled form control with its validation message. */
function Field({
  label,
  error,
  children,
}: {
  label: string
  error?: string
  children: React.ReactNode
}) {
  return (
    <label className="space-y-1">
      <span className="text-sm font-medium">{label}</span>
      {children}
      {error ? <p className="text-xs text-destructive">{error}</p> : null}
    </label>
  )
}
