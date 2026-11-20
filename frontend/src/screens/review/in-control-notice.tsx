import { ShieldCheck } from "lucide-react"
import type { ReactNode } from "react"

import { PlainText } from "@/components/common/plain-text"
import { LinkButton } from "@/components/ui/link-button"

/**
 * The two paths an approval can queue work onto, and why they must never
 * blur together.
 *
 * The adapter registry (`src/security/registry_setup.py`) grants the
 * **submit** capability to exactly one adapter: `fake-ats-playwright`, the
 * local test board. Every real-board adapter holds **prepare** only — the
 * registry refuses their submissions — so a real board never receives an
 * autonomous submission from this product. The copy below says which world
 * the packet targets, in the operator's own words, so the two are visible
 * at a glance and nothing suggests an employer is reached without a human.
 */
export function isLocalTestBoard(adapterName: string): boolean {
  return adapterName.startsWith("fake-ats")
}

/*
  The design file draws this slot as a sage "Approval boundary" panel
  (node `49:1092`): "Your approval is specific. Your final submit stays
  yours." over "JobPilot may fill the employer form. You review it and
  press the final Submit button on the employer site. No application has
  been sent." Both sentences are written for the real-board path and both
  are true of it, so the real-board variant carries them verbatim — plus
  one operational sentence the design's example could not carry: this
  deployment's real-board adapters hold no submit capability at all.

  The fake-ATS path needs a different sentence, because the design's would
  be false there: the local test board *does* submit — to the test server
  on this machine, which is the designed demo path. Same panel, honest
  copy for the packet's own adapter.
*/

/** The design panel's shape: sage wash, 18px pad, 15/600 over 13/400. */
function BoundaryPanel({
  heading,
  children,
}: {
  heading: string
  children: ReactNode
}) {
  return (
    <section className="flex flex-col gap-2 rounded-surface bg-forest-soft p-[18px]">
      <h2 className="text-[15px] font-semibold leading-[22px] text-primary">
        {heading}
      </h2>
      <p className="max-w-prose text-[13px] leading-[19px] text-muted-foreground">
        {children}
      </p>
    </section>
  )
}

/**
 * The approval boundary: the panel the design puts under the packet,
 * carrying the honest version of "the agent will wait for your approval
 * before submission" for whichever world the packet targets.
 */
export function InControlNotice({ adapterName }: { adapterName: string }) {
  if (isLocalTestBoard(adapterName)) {
    return (
      <BoundaryPanel heading="You're in control. Nothing runs before you approve it.">
        This packet targets{" "}
        <code className="font-mono text-[11px]">{adapterName}</code>, the
        local test board of this deployment — not an employer. Approving
        records your decision and queues a run against that test server,
        which runs on this machine. Nothing reaches any employer, and the
        run is only queued once you approve.
      </BoundaryPanel>
    )
  }
  return (
    <BoundaryPanel heading="Your approval is specific. Your final submit stays yours.">
      JobPilot may fill the employer form. You review it and press the final
      Submit button on the employer site. No application has been sent —
      approving queues the run, and this deployment's real-board adapters
      hold no submit capability at all: the run stops where a human takes
      over.
    </BoundaryPanel>
  )
}

/**
 * The standing aside from the reference panel: "You remain in control".
 *
 * It stays on the page whether or not a packet is open, because it is the
 * one promise every other element on this screen rests on. The link points
 * at the audit trail — the real place every agent step is recorded — rather
 * than at an explanation the console would have to invent.
 */
export function ControlPanel() {
  return (
    <div className="rounded-surface border border-terracotta bg-terracotta-soft/60 p-4">
      <div className="flex items-start gap-3">
        <ShieldCheck className="mt-0.5 size-5 shrink-0 text-terracotta-foreground" />
        <div className="min-w-0 space-y-2">
          <h2 className="font-heading text-sm font-semibold tracking-tight text-terracotta-foreground">
            You remain in control
          </h2>
          <PlainText className="text-terracotta-foreground">
            The agent cannot make an unsupported answer, bypass a challenge, or
            submit without a human decision. Every step it takes is in the audit
            trail.
          </PlainText>
          <LinkButton to="/app/activity" variant="ghost" size="sm">
            See the audit trail
          </LinkButton>
        </div>
      </div>
    </div>
  )
}
