import { useState } from "react"

import { PenLine } from "lucide-react"

import { Banner } from "@/components/common/banner"
import { Button } from "@/components/ui/button"
import type { TailoredEditRequest, TailoredResume } from "@/lib/api/types"

import { FormatChip } from "./resume-diff"
import type { RenderReport } from "./diff-model"

/*
  The studio's section editor (WS-47).

  **What editing is here, and what it is not.** The editor changes *wording*:
  the summary, the experience bullets, the cover letter. It does not offer
  formatting controls (the in-place editor cannot regenerate run formatting —
  the toolbar row states the deliverable's real format instead), and it does
  not offer the projects section when the deliverable is the caller's own
  document edited in place, because that editor never rewrites projects —
  an editor for a section that cannot reach the deliverable would be a lie
  about what saving does.

  **The save is the pipeline, minus the model.** The server applies the
  sections onto the existing entries in order (one bullet per line, re-chunked
  positionally — no entry can be added, removed or renamed), revalidates
  factuality against the profile, re-runs the ATS analysis, regenerates the
  deliverable through the WS-31 in-place path, and answers with the updated
  record. A factuality violation is *not* an error: the response carries the
  stripped content and the report, and the screen renders it as content.

  **A failed save never throws the work away.** The editor stays open with
  the draft, and the server's own actionable message is shown verbatim — the
  caller can fix the cause (or retry) without retyping anything.
*/

const TEXTAREA_CLASSES =
  "w-full rounded-xl border border-input bg-card px-3.5 py-3 text-sm leading-relaxed text-foreground transition-colors outline-none placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 disabled:cursor-not-allowed disabled:opacity-70"

/** The experience bullets as one bullet per line, for the textarea. */
function flattenBullets(tailored: TailoredResume): string {
  return tailored.experience
    .flatMap((entry) => entry.bullets)
    .join("\n")
}

export function ResumeEditor({
  tailored,
  render,
  jobTitle,
  company,
  saving,
  error,
  onSave,
  onDiscard,
}: {
  tailored: TailoredResume
  render: RenderReport
  jobTitle: string
  company: string
  saving: boolean
  /** The server's own message when the last save failed, verbatim. */
  error: string | null
  onSave: (payload: TailoredEditRequest) => void
  onDiscard: () => void
}) {
  const [summary, setSummary] = useState(tailored.summary)
  const [bullets, setBullets] = useState(() => flattenBullets(tailored))
  const [letter, setLetter] = useState(tailored.cover_letter)
  const bulletLines = bullets.split("\n").filter((line) => line.trim().length > 0)

  return (
    <div className="flex min-w-0 flex-col gap-3.5 rounded-surface bg-forest-soft p-4">
      {/* The toolbar row: the same format truth, and the save's real controls. */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-2.5">
          <FormatChip render={render} />
          <span className="text-xs text-muted-foreground">
            Editing your draft — a save revalidates it and regenerates the
            deliverable.
          </span>
        </div>
        <div className="flex items-center gap-2">
          <Button size="sm" onClick={() => onSave({ summary, experience: bullets, cover_letter: letter })} disabled={saving}>
            <PenLine className="size-3.5" aria-hidden />
            {saving ? "Saving…" : "Save changes"}
          </Button>
          <Button size="sm" variant="outline" onClick={onDiscard} disabled={saving}>
            Discard changes
          </Button>
        </div>
      </div>

      {error ? (
        <Banner tone="warning" title="The save did not go through">
          <p>{error}</p>
          <p className="mt-1 text-xs">
            Your edits are still here — fix the cause or try again; nothing was
            saved.
          </p>
        </Banner>
      ) : null}

      <article className="flex min-w-0 flex-col gap-3.5 rounded-surface border border-border-surface bg-card p-[30px]">
        <h2 className="text-[22px] font-semibold uppercase leading-8 text-primary">
          {jobTitle}
        </h2>
        <p className="text-xs leading-[17px] text-muted-foreground">
          {company} · editing your draft · source preserved
        </p>
        <div className="h-px w-full shrink-0 bg-border-surface" aria-hidden />

        <section className="min-w-0 space-y-2">
          <label
            htmlFor="studio-edit-summary"
            className="text-[13px] font-semibold uppercase leading-[19px] text-primary"
          >
            Professional summary
          </label>
          <textarea
            id="studio-edit-summary"
            value={summary}
            onChange={(event) => setSummary(event.target.value)}
            rows={4}
            disabled={saving}
            spellCheck
            className={TEXTAREA_CLASSES}
          />
          <p className="text-[11px] leading-4 text-muted-foreground tabular-nums">
            {summary.length} characters
          </p>
        </section>

        <section className="min-w-0 space-y-2">
          <label
            htmlFor="studio-edit-experience"
            className="text-[13px] font-semibold uppercase leading-[19px] text-primary"
          >
            Experience bullets
          </label>
          <textarea
            id="studio-edit-experience"
            value={bullets}
            onChange={(event) => setBullets(event.target.value)}
            rows={6}
            disabled={saving}
            spellCheck
            className={TEXTAREA_CLASSES}
          />
          <p className="text-[11px] leading-4 text-muted-foreground">
            One bullet per line. The lines are applied to your entries in
            order — entries themselves (company, title) stay as the tailoring
            produced them, and lines beyond an entry&apos;s originals are
            appended after its last bullet. Currently{" "}
            <span className="tabular-nums">{bulletLines.length}</span> bullet
            line(s).
          </p>
        </section>

        <section className="min-w-0 space-y-2">
          <label
            htmlFor="studio-edit-cover-letter"
            className="text-[13px] font-semibold uppercase leading-[19px] text-primary"
          >
            Cover letter
          </label>
          <textarea
            id="studio-edit-cover-letter"
            value={letter}
            onChange={(event) => setLetter(event.target.value)}
            rows={8}
            disabled={saving}
            spellCheck
            className={TEXTAREA_CLASSES}
          />
          <p className="text-[11px] leading-4 text-muted-foreground tabular-nums">
            {letter.length} characters
          </p>
        </section>

        <p className="text-[11px] leading-4 text-muted-foreground">
          The validator still runs on a save: anything your résumé does not
          state is stripped and reported, and the wording that survives is
          what the regenerated deliverable carries.
        </p>
      </article>
    </div>
  )
}
