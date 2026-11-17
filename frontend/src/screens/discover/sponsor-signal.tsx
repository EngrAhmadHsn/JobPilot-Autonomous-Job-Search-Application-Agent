import { PlainText } from "@/components/common/plain-text"

/*
  The sponsorship signal, rendered honestly in all three of its states (WS-36).

  WS-22 attaches a verdict from the imported sponsor registers to every match:
  `verified` (the register shows the employer sponsors visas), `not_found`
  (a register was checked and holds no record for this employer), and
  `no_data` (no register covers this listing at all). The shared
  `SponsorBadge` renders the first two and renders **nothing** for the third —
  which is silent where the workstream's rule says unknown: sponsorship is
  shown only from verified registers, *and honestly as unknown otherwise*.

  So this screen-local component spells out all three:
  - verified → the forest chip, with the register's own note;
  - not_found → the checked-and-negative state, worded as a record lookup;
  - no_data / unknown → "Sponsorship unknown", never a guess in either
    direction.

  Folding this back into `SponsorBadge` is a report proposal to the lead; until
  it lands, this component is the only place Discover draws a sponsorship chip.
*/
export function SponsorSignal({
  status,
  note,
}: {
  status?: string | null
  note?: string | null
}) {
  const title = note ?? undefined
  if (status === "verified") {
    return (
      <div>
        <p className="text-xs font-medium text-muted-foreground">Sponsorship</p>
        <ul className="mt-1.5 flex flex-wrap gap-1.5">
          <li
            title={title}
            className="inline-flex max-w-full items-center rounded-full border border-forest/30 bg-forest-soft px-2.5 py-0.5 text-xs text-forest"
          >
            <PlainText as="span" className="text-xs">
              {note ?? "Verified visa sponsor"}
            </PlainText>
          </li>
        </ul>
      </div>
    )
  }
  if (status === "not_found") {
    return (
      <div>
        <p className="text-xs font-medium text-muted-foreground">Sponsorship</p>
        <ul className="mt-1.5 flex flex-wrap gap-1.5">
          <li
            title={title}
            className="inline-flex max-w-full items-center rounded-full border border-border bg-muted px-2.5 py-0.5 text-xs text-muted-foreground"
          >
            <PlainText as="span" className="text-xs">
              No sponsorship record found
            </PlainText>
          </li>
        </ul>
      </div>
    )
  }
  return (
    <div>
      <p className="text-xs font-medium text-muted-foreground">Sponsorship</p>
      <ul className="mt-1.5 flex flex-wrap gap-1.5">
        <li
          title={title}
          className="inline-flex max-w-full items-center rounded-full border border-border bg-muted px-2.5 py-0.5 text-xs text-muted-foreground"
        >
          <PlainText as="span" className="text-xs">
            Sponsorship unknown — no register data for this listing
          </PlainText>
        </li>
      </ul>
    </div>
  )
}
