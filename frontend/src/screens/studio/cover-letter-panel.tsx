import { useState } from "react"

import { ClipboardCopy } from "lucide-react"

import { Banner } from "@/components/common/banner"
import { PlainText } from "@/components/common/plain-text"
import { Button } from "@/components/ui/button"

/*
  The cover letter (WS-37 task 6).

  **Independence:** the letter and the resume are separately versioned on
  the server, and this editor keeps that true in miniature — its state is
  the letter's alone. No edit here touches the resume diff, the reports or
  the delivered file, and no edit anywhere else touches this text.

  **What persistence supports, and where it lives:** this tab's draft stays
  in the window — the copy button moves the text where it can be kept, and
  a fresh draft arrives with a fresh tailoring run. Since WS-47 the letter
  *can* be saved to the server, but only through the studio's Edit draft on
  the Inline diff tab (which saves it together with the resume sections and
  revalidates both); the banner says so rather than implying no save exists.
*/

export function CoverLetterPanel({
  letter,
  jobTitle,
  company,
}: {
  letter: string
  jobTitle: string
  company: string
}) {
  const [draft, setDraft] = useState(letter)
  const [copied, setCopied] = useState(false)

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(draft)
      setCopied(true)
    } catch {
      // A refused clipboard is honest feedback, not a silent failure: the
      // textarea remains the source, and the operator can select and copy.
      setCopied(false)
    }
  }

  return (
    <div className="space-y-5">
      <Banner tone="info" title="This draft is not saved on the server">
        <p>
          The tailoring stores the letter as delivered. Edits you make here live
          only in this window — copy the text out before you leave the page. A
          new letter comes with a new tailoring run (Tailor again, top of the
          screen); nothing you type changes the resume, its reports or the
          delivered file. To save the letter to the server, use Edit draft on
          the Inline diff tab — a save there revalidates it together with the
          resume sections.
        </p>
      </Banner>

      <div className="space-y-2">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <label
            htmlFor="cover-letter-draft"
            className="font-heading text-base font-semibold tracking-tight text-foreground"
          >
            Cover letter for {jobTitle} at {company}
          </label>
          <Button
            variant="outline"
            size="sm"
            onClick={() => void copy()}
            disabled={draft.length === 0}
          >
            <ClipboardCopy className="size-3.5" aria-hidden />
            {copied ? "Copied" : "Copy the letter"}
          </Button>
        </div>
        <textarea
          id="cover-letter-draft"
          value={draft}
          onChange={(event) => {
            setDraft(event.target.value)
            setCopied(false)
          }}
          rows={14}
          spellCheck
          className="w-full rounded-xl border border-input bg-card px-3.5 py-3 text-sm leading-relaxed text-foreground transition-colors outline-none placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
        />
        <p className="text-xs text-muted-foreground tabular-nums">
          {draft.length} characters
        </p>
      </div>

      <div className="rounded-xl border border-border bg-card/60 p-4">
        <p className="text-xs font-semibold text-foreground">
          Where the letter's claims come from
        </p>
        <PlainText className="mt-1.5 text-sm text-muted-foreground">
          The draft was written from your own résumé's facts for this role — the
          validator stripped anything your document does not state. No employer
          fact was invented: what the letter says about the company comes from
          the listing text on the Research tab, and nothing else.
        </PlainText>
      </div>
    </div>
  )
}
