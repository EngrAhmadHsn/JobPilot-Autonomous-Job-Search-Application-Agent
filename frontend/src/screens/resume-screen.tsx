import { useMutation, useQuery } from "@tanstack/react-query"
import { useState } from "react"

import { Banner } from "@/components/common/banner"
import { ErrorNotice } from "@/components/common/error-notice"
import { PlainText } from "@/components/common/plain-text"
import { ProgressState } from "@/components/common/progress-state"
import { ProfileView } from "@/components/profile/profile-view"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"

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
 * The Resume screen.
 *
 * The screen does three things: it gets a resume into the system, it shows
 * what the parser understood, and it makes the *current* profile explicit —
 * every other screen works against that profile, and the API has no listing
 * of profiles (BA-4), so the console keeps the id locally and shows it.
 */
export function ResumeScreen() {
  const currentProfileId = useCurrentProfileId()
  const [file, setFile] = useState<File | null>(null)
  const [fileError, setFileError] = useState<string | null>(null)

  const upload = useMutation({
    mutationFn: (resume: File) => api.uploadResume(resume),
    onSuccess: (result) => {
      setCurrentProfileId(result.profile_id)
    },
  })

  const storedProfile = useQuery({
    queryKey: ["profile", currentProfileId],
    queryFn: ({ signal }) => api.getResume(currentProfileId as string, signal),
    enabled: Boolean(currentProfileId),
  })

  const uploaded = upload.data
  // The OpenAPI schema marks the warning list optional (FastAPI's default
  // factory), so the console reads it defensively rather than assuming.
  const warnings = uploaded?.warnings ?? []

  const handleFile = (candidate: File | null) => {
    setFile(candidate)
    setFileError(candidate ? checkFile(candidate) : null)
    upload.reset()
  }

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>Upload a resume</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <p className="text-sm text-muted-foreground">
            A DOCX, TXT or MD file of at most 5 MB. The server parses it into a
            candidate profile and stores it; nothing is sent anywhere else.
          </p>

          <div className="space-y-2">
            <label htmlFor="resume-file" className="text-sm font-medium">
              Resume file
            </label>
            <Input
              id="resume-file"
              type="file"
              accept=".docx,.txt,.md"
              onChange={(event) => handleFile(event.target.files?.[0] ?? null)}
              aria-describedby="resume-file-help"
            />
            <p id="resume-file-help" className="text-xs text-muted-foreground">
              {file
                ? `${file.name} · ${formatBytes(file.size)}`
                : "No file chosen."}
            </p>
          </div>

          {fileError ? (
            <Banner tone="warning" title="This file will be refused">
              {fileError}
            </Banner>
          ) : null}

          {upload.isPending ? (
            <ProgressState
              key="upload"
              title="Uploading and parsing the resume"
              description="The server parses the file into a profile. This takes a moment."
            />
          ) : null}

          {upload.isError ? <ErrorNotice error={upload.error} /> : null}

          {upload.isSuccess && uploaded ? (
            <Banner tone="success" title="The resume was parsed and stored">
              <p>
                The profile id is{" "}
                <code className="rounded bg-muted px-1 py-0.5 font-mono text-[11px]">
                  {uploaded.profile_id}
                </code>
                . It is now the current profile for every other screen.
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
            {upload.isPending ? "Uploading…" : "Upload and parse"}
          </Button>
        </CardContent>
      </Card>

      {upload.isSuccess && uploaded && warnings.length > 0 ? (
        <Card>
          <CardHeader>
            <CardTitle>Validation warnings ({warnings.length})</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            <p className="text-sm text-muted-foreground">
              The server&apos;s deterministic validation found things the
              document does not state. They do not stop the profile from being
              used, but a match built on a profile with no email or no skills
              will be weaker.
            </p>
            <ul className="list-disc space-y-1 pl-5 text-sm">
              {warnings.map((warning) => (
                <li key={warning}>
                  <PlainText as="span">{warning}</PlainText>
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      ) : null}

      {currentProfileId ? (
        <Card>
          <CardHeader>
            <CardTitle>Current profile</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <p className="text-sm">
              <code className="rounded bg-muted px-1 py-0.5 font-mono text-[11px]">
                {currentProfileId}
              </code>{" "}
              <span className="text-muted-foreground">
                is the profile the other screens work with.
              </span>
            </p>

            {storedProfile.isPending ? (
              <ProgressState key="profile" title="Loading the stored profile" />
            ) : null}

            {storedProfile.isError ? (
              <ErrorNotice
                error={storedProfile.error}
                onRetry={() => storedProfile.refetch()}
              />
            ) : null}

            {storedProfile.data ? (
              <>
                <Banner tone="neutral" title="About the validation warnings">
                  <p>
                    The warnings are produced when the file is parsed and are
                    not stored with the profile, so they are not shown here.
                    Re-upload the file to see them again.
                  </p>
                </Banner>
                <ProfileView profile={storedProfile.data.profile} />
              </>
            ) : null}
          </CardContent>
        </Card>
      ) : null}
    </div>
  )
}
