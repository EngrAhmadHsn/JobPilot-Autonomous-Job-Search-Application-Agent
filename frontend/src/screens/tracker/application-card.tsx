import { Link } from "react-router-dom"

import { cn } from "cn"

import { stagger } from "@/lib/stagger"
import type { ApplicationSummary } from "@/lib/api/types"

import { stageChip, stageCta, stageHelper, stageTimestamp } from "./stage-copy"

/*
  One application on the board (WS-39 card, rebuilt to the design in WS-42).

  The design file's card (nodes 49:1157–49:1182) is a five-part column:
  the company, the job title, a **stage chip**, a one-line helper, then a
  divider over a **CTA pill** and a **timestamp**. The chip, helper, CTA and
  timestamp come from `stage-copy.ts`, which keeps the design's sentences
  where they are true of this backend and the console's vocabulary where
  they are not — the board's own legend (49:1255) is the honesty contract
  those words live under.

  Two structure notes:

  - The card is no longer one whole-card link (nested links are invalid
    HTML once the CTA became a link of its own): the job title is the link,
    and the CTA pill is a second, explicit one. Both go to the same detail
    screen.
  - Every value is the server's. The chip and helper re-phrase a status,
    never invent one; the timestamp is computed from a real field; a
    missing timestamp renders as an empty footer, not a fabricated one.
*/
export function ApplicationCard({
  application,
  index,
}: {
  application: ApplicationSummary
  index: number
}) {
  const chip = stageChip(application.status)
  const helper = stageHelper(application.status)
  const cta = stageCta(application.status)
  const timestamp = stageTimestamp(application)
  const detail = `/app/tracker/${encodeURIComponent(application.id)}`

  return (
    <li {...stagger(index)}>
      <div className="flex flex-col gap-3 rounded-[var(--radius-surface)] border border-border-surface bg-paper p-4">
        <span className="text-xs leading-[17px] font-semibold wrap-anywhere text-muted-foreground">
          {application.company_name}
        </span>

        <h4 className="text-lg leading-[26px] font-semibold wrap-anywhere text-primary">
          <Link
            to={detail}
            className="underline-offset-4 outline-none hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
          >
            {application.job_title}
          </Link>
        </h4>

        <span
          className={cn(
            "inline-block max-w-full rounded-md px-[9px] py-1 text-[11px] leading-4 font-semibold text-primary",
            chip.tone
          )}
        >
          {chip.label}
        </span>

        <span
          title={helper}
          className="text-xs leading-[17px] text-muted-foreground"
        >
          {helper}
        </span>

        <div aria-hidden="true" className="h-px bg-border-surface" />

        <span>
          <Link
            to={detail}
            className="inline-block rounded-lg border border-[#dce1d6] bg-paper px-3.5 py-2 text-[13px] leading-[19px] font-semibold text-primary underline-offset-4 outline-none hover:bg-accent focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
          >
            {cta}
          </Link>
        </span>

        {timestamp ? (
          <span className="text-[11px] leading-4 text-muted-foreground">
            {timestamp}
          </span>
        ) : null}
      </div>
    </li>
  )
}
