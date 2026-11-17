import { ShieldCheck } from "lucide-react"

import { Banner } from "@/components/common/banner"
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

/**
 * The in-control notice: the amber line the reference panel puts above the
 * review, carrying the honest version of "the agent will wait for your
 * approval before submission".
 *
 * The two variants are deliberately different sentences, not one sentence
 * with a name swapped in: the fake-ATS path queues a run that *does* submit
 * — to the local test server, where that is the designed demo path — and
 * the real-board path queues a run that fills what it may and hands the
 * rest back. Saying "the agent will submit" for the second would be false;
 * saying "nothing is ever submitted" for the first would be false too.
 */
export function InControlNotice({ adapterName }: { adapterName: string }) {
  if (isLocalTestBoard(adapterName)) {
    return (
      <Banner
        tone="warning"
        title="You're in control. Nothing runs before you approve it."
      >
        <p>
          This packet targets{" "}
          <code className="font-mono text-[11px]">{adapterName}</code>, the
          local test board of this deployment — not an employer. Approving
          records your decision and queues a run against that test server, which
          runs on this machine. Nothing reaches any employer, and the run is
          only queued once you approve.
        </p>
      </Banner>
    )
  }
  return (
    <Banner
      tone="warning"
      title="You're in control. The final submit is yours."
    >
      <p>
        This application walks a real board's form. The agent fills in what it
        may, and anything only a person may do — the final submit, a CAPTCHA, a
        sign-in step — is handed back to you. Those are never bypassed, and this
        deployment's real-board adapters hold no submit capability at all:
        approving queues the run, and the run stops where a human takes over.
      </p>
    </Banner>
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
    <div className="rounded-2xl border border-terracotta bg-terracotta-soft/60 p-4">
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
