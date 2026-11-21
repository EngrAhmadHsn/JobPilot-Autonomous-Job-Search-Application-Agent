import { PlainText } from "@/components/common/plain-text"

/*
  The sponsorship signal as the design's single quiet line (WS-42, node
  `49:943` — "Sponsorship: unknown · no register data available", 12/400).

  WS-22 attaches a verdict from the imported sponsor registers to every match:
  `verified` (the register shows the employer sponsors visas), `not_found`
  (a register was checked and holds no record for this employer), and
  `no_data` (no register covers this listing at all). All three render here,
  in one line each, because the workstream's rule is that sponsorship is
  shown only from verified registers *and honestly as unknown otherwise* —
  never a guess in either direction, never a silent absence.

  The job-detail route renders the fuller "Match guardrails" block from the
  same data (its rail, node `49:1958`); this component is the Discover
  panel's compact rendering.
*/
export function SponsorSignal({
  status,
  note,
}: {
  status?: string | null
  note?: string | null
}) {
  const finding = note ?? "Verified visa sponsor"
  let line: string
  if (status === "verified") {
    line = `Sponsorship: verified · ${finding}`
  } else if (status === "not_found") {
    line =
      "Sponsorship: no record found · checked against the sponsor registers"
  } else {
    line = "Sponsorship: unknown · no register data available"
  }
  return (
    <p className="text-xs leading-[17px] text-muted-foreground">
      <PlainText as="span" className="text-xs leading-[17px]">
        {line}
      </PlainText>
    </p>
  )
}
