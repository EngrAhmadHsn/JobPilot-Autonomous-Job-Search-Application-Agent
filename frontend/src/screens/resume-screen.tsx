import { useMutation, useQuery } from "@tanstack/react-query"
import { FileText, Upload } from "lucide-react"
import { useRef, useState } from "react"
import { Link } from "react-router-dom"

import { Banner } from "@/components/common/banner"
import { ErrorNotice } from "@/components/common/error-notice"
import { PageHeader, Section } from "@/components/common/page-header"
import { PlainText } from "@/components/common/plain-text"
import { ProfileView } from "@/components/profile/profile-view"
import { Button } from "@/components/ui/button"

import { api } from "@/lib/api/endpoints"
import { formatBytes } from "@/lib/format"
import { setCurrentProfileId, useCurrentProfileId } from "@/lib/profile"

/**
 * The upload rules, mirrored from the server.
 *
 * `src/api/validation.py` is the control: it refuses a disallowed
 * extension, an oversized file, a file that is not a real document, and a
 * file it cannot parse. This client-side check is a **courtesy** — it tells
 * the operator what is wrong before the upload starts — and the server's
 * answer is always the one that counts.
 */
const ALLOWED_EXTENSIONS = [".docx", ".txt", ".md"]
const MAX_UPLOAD_BYTES = 5 * 1024 * 1024

function checkFile(file: File): string | null {
  const dot = file.name.lastIndexOf(".")
  const extension = dot >= 0 ? file.name.slice(dot).toLowerCase() : ""
  if (!ALLOWED_EXTENSIONS.includes(extension)) {
    return `The file extension is not allowed. The server accepts ${ALLOWED_EXTENSIONS.join(", ")}.`
  }
  if (file.size > MAX_UPLOAD_BYTES) {
    return `The file is ${formatBytes(file.size)}. The server accepts at most ${formatBytes(MAX_UPLOAD_BYTES)}.`
  }
  return null
}

/**
 * The drop zone.
 *
 * Dragging is an *addition*, never the only way in: the zone is a button
 * that opens the file dialog, so it works with a keyboard and with a
 * single pointer (WCAG 2.2 asks for exactly that).
 */
function DropZone({
  file,
  onFile,
  dragging,
  onDragging,
  inputRef,
}: {
  file: File | null
  onFile: (file: File | null) => void
  dragging: boolean
  onDragging: (dragging: boolean) => void
  inputRef: React.RefObject<HTMLInputElement | null>
}) {
  return (
    <div
      onDragOver={(event) => {
        event.preventDefault()
        onDragging(true)
      }}
      onDragLeave={() => onDragging(false)}
      onDrop={(event) => {
        event.preventDefault()
        onDragging(false)
        onFile(event.dataTransfer.files?.[0] ?? null)
      }}
      className={
        "rounded-2xl border border-dashed bg-card p-8 text-center transition-colors duration-200 sm:p-12 " +
        (dragging ? "border-primary bg-accent/60" : "border-border")
      }
    >
      <span
        aria-hidden="true"
        className="mx-auto flex size-14 items-center justify-center rounded-2xl bg-lime-soft text-forest"
      >
        <FileText className="size-7" strokeWidth={1.6} />
      </span>

      <p className="mt-4 font-heading text-lg font-semibold tracking-tight text-foreground">
        {file ? file.name : "Drop your résumé here"}
      </p>
      <p className="mt-1 text-sm text-muted-foreground">
        {file
          ? `${formatBytes(file.size)} · ready to analyse`
          : "or choose a file from your machine"}
      </p>

      <p className="mt-4 text-xs text-muted-foreground">
        DOCX, TXT or MD · up to 5 MB · parsed on this machine, never sent to a
        third party
      </p>

      <label htmlFor="resume-file" className="sr-only">
        Résumé file
      </label>
      <input
        ref={inputRef}
        id="resume-file"
        type="file"
        accept=".docx,.txt,.md"
        className="sr-only"
        onChange={(event) => onFile(event.target.files?.[0] ?? null)}
      />
      <Button
        type="button"
        variant="outline"
        className="mt-5"
        onClick={() => inputRef.current?.click()}
      >
        {file ? "Choose a different file" : "Choose a file"}
      </Button>
    </div>
  )
}

/** The three steps the console walks the operator through. */
const STEPS = [
  {
    title: "Build your profile",
    body: "Your résumé becomes a set of facts the agent can check every listing against.",
  },
  {
    title: "Explore matching jobs",
    body: "Every stored listing is scored, and the six component scores say why.",
  },
  {
    title: "Approve and apply",
    body: "You review every application. Nothing is sent to an employer until you approve it.",
  },
]

/**
 * The Resume screen.
 *
 * The first thing a new operator sees, so it is an **onboarding** rather
 * than a form: what the agent will do with the résumé, one obvious way to
 * give it one, and — once there is a profile — what the agent understood
 * and the next step.
 */
export function ResumeScreen() {
  const profileId = useCurrentProfileId()
  const inputRef = useRef<HTMLInputElement>(null)
  const [file, setFile] = useState<File | null>(null)
  const [fileError, setFileError] = useState<string | null>(null)
  const [dragging, setDragging] = useState(false)

  const upload = useMutation({
    mutationFn: (resume: File) => api.uploadResume(resume),
    onSuccess: (result) => {
      setCurrentProfileId(result.profile_id)
    },
  })

  const storedProfile = useQuery({
    queryKey: ["profile", profileId],
    queryFn: ({ signal }) => api.getResume(profileId as string, signal),
    enabled: Boolean(profileId),
  })

  const handleFile = (candidate: File | null) => {
    setFile(candidate)
    setFileError(candidate ? checkFile(candidate) : null)
    upload.reset()
  }

  const hasProfile = Boolean(profileId)
  const uploaded = upload.data

  return (
    <div className="space-y-12">
      <PageHeader
        title={
          hasProfile
            ? "Your career profile"
            : "Let's build your career profile."
        }
        description={
          hasProfile ? (
            <>
              This is what the agent read from your résumé. Every match it
              scores, and every application it prepares, is built from these
              facts — and only from these facts.
            </>
          ) : (
            <>
              Your résumé is read once, on this machine, and becomes a set of
              facts: what you have done, what you know, what you want next. The
              agent scores every job against those facts, tailors a résumé from
              them, and never claims anything it cannot find there.
            </>
          )
        }
      />

      {!hasProfile ? (
        <section className="border-t border-border pt-8">
          <h2 className="font-heading text-sm font-semibold tracking-tight text-foreground">
            How it works
          </h2>
          <ol className="mt-4 grid gap-6 sm:grid-cols-3">
            {STEPS.map((step, index) => (
              <li key={step.title} className="flex gap-3">
                <span
                  aria-hidden="true"
                  className="mt-0.5 flex size-6 shrink-0 items-center justify-center rounded-full bg-forest-soft text-[11px] font-semibold text-forest"
                >
                  {index + 1}
                </span>
                <div>
                  <p className="text-sm font-medium text-foreground">
                    {step.title}
                  </p>
                  <p className="mt-1 text-sm leading-relaxed text-muted-foreground">
                    {step.body}
                  </p>
                </div>
              </li>
            ))}
          </ol>
        </section>
      ) : null}

      {hasProfile ? (
        <Section
          title="Replace your résumé"
          description="Uploading a new one creates a new profile. The old one stays in the database."
        >
          <div className="max-w-3xl space-y-4">
            <DropZone
              file={file}
              onFile={handleFile}
              dragging={dragging}
              onDragging={setDragging}
              inputRef={inputRef}
            />

            {fileError ? (
              <Banner tone="warning" title="This file will be refused">
                {fileError}
              </Banner>
            ) : null}

            {upload.isPending ? (
              <div className="space-y-2">
                <p className="text-sm text-foreground">
                  Reading your résumé and building your profile…
                </p>
                <div className="agent-progress h-1.5 w-full rounded-full" />
              </div>
            ) : null}

            {upload.isError ? <ErrorNotice error={upload.error} /> : null}

            {upload.isSuccess && uploaded ? (
              <Banner tone="success" title="Your profile is ready">
                <p>
                  The agent read{" "}
                  <code className="font-mono text-[11px]">
                    {uploaded.profile_id}
                  </code>{" "}
                  and stored it as the current profile.
                </p>
              </Banner>
            ) : null}

            <Button
              type="button"
              disabled={!file || Boolean(fileError) || upload.isPending}
              onClick={() => {
                if (file) upload.mutate(file)
              }}
            >
              {upload.isPending ? "Analysing…" : "Upload and analyse résumé"}
            </Button>
          </div>
        </Section>
      ) : (
        <div className="reveal-once max-w-3xl space-y-4">
          <DropZone
            file={file}
            onFile={handleFile}
            dragging={dragging}
            onDragging={setDragging}
            inputRef={inputRef}
          />

          {fileError ? (
            <Banner tone="warning" title="This file will be refused">
              {fileError}
            </Banner>
          ) : null}

          {upload.isPending ? (
            <div className="space-y-2">
              <p className="text-sm text-foreground">
                Reading your résumé and building your profile…
              </p>
              <div className="agent-progress h-1.5 w-full rounded-full" />
            </div>
          ) : null}

          {upload.isError ? <ErrorNotice error={upload.error} /> : null}

          {upload.isSuccess && uploaded ? (
            <Banner tone="success" title="Your profile is ready">
              <p>
                The agent read{" "}
                <code className="font-mono text-[11px]">
                  {uploaded.profile_id}
                </code>{" "}
                and stored it as the current profile. The summary is below.
              </p>
            </Banner>
          ) : null}

          <Button
            type="button"
            size="lg"
            disabled={!file || Boolean(fileError) || upload.isPending}
            onClick={() => {
              if (file) upload.mutate(file)
            }}
          >
            <Upload className="size-4" aria-hidden="true" />
            {upload.isPending ? "Analysing…" : "Upload and analyse résumé"}
          </Button>
        </div>
      )}

      {upload.isSuccess && uploaded && uploaded.warnings.length > 0 ? (
        <Section
          title="What the résumé does not say"
          description="The server's deterministic validation found these gaps. They do not stop the profile from being used, but a profile with no email or no skills will match weakly."
        >
          <ul className="space-y-2">
            {uploaded.warnings.map((warning) => (
              <li
                key={warning}
                className="rounded-xl border border-terracotta/70 bg-terracotta-soft px-4 py-3 text-sm text-terracotta-foreground"
              >
                <PlainText as="span">{warning}</PlainText>
              </li>
            ))}
          </ul>
        </Section>
      ) : null}

      {profileId ? (
        <Section
          title="What the agent read"
          description="Everything below came out of your document. Nothing was inferred."
          action={
            <Button render={<Link to="/matches" />}>
              Explore matching jobs
            </Button>
          }
        >
          {storedProfile.isPending ? (
            <div className="space-y-2">
              <p className="text-sm text-foreground">Loading your profile…</p>
              <div className="agent-progress h-1.5 w-full rounded-full" />
            </div>
          ) : null}

          {storedProfile.isError ? (
            <ErrorNotice
              error={storedProfile.error}
              onRetry={() => storedProfile.refetch()}
            />
          ) : null}

          {storedProfile.data ? (
            <ProfileView profile={storedProfile.data.profile} />
          ) : null}
        </Section>
      ) : null}
    </div>
  )
}
