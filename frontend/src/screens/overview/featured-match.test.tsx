import { screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"

import { NextStepPanel } from "@/screens/overview/home-panels"
import { FeaturedMatch } from "@/screens/overview/featured-match"
import { matchPair } from "@/test/factories"
import { renderScreen } from "@/test/render"

/*
  The Home screen's colour contract (WS-43).

  The featured card is a **coloured surface** (`bg-primary`: forest in the
  light theme, lime in the dark one), and the text inside it is untrusted
  job data rendered by `PlainText`, which paints its own `text-foreground`
  — right on the paper surfaces, and the exact defect this file pins here:
  dark ink silently replacing the card's foreground on the forest ground.
  So the colour lives **inside** the spans, and these assertions hold the
  resolved classes, not just the wrapper's intent.

  The next-step panel is the same story the other way round: its ground is
  the constant terracotta wash, so its statements must carry the constant
  dark forest — `--primary` flips to lime at night and would vanish on it.
*/
describe("the featured match card", () => {
  it("carries the card's own foreground inside the text spans", () => {
    const { job, match } = matchPair()
    renderScreen(<FeaturedMatch job={job} match={match} />)

    // The title span is what the reader's eye sees: paper-white on the
    // forest card by day, dark on the lime card by night — never ink.
    const title = screen.getByRole("heading", { name: "AI Engineer" })
    const titleSpan = title.querySelector("span")
    expect(titleSpan).not.toBeNull()
    expect(titleSpan).toHaveClass("text-primary-foreground")
    expect(titleSpan).not.toHaveClass("text-foreground")

    // The meta line and the rationale read at the /80 wash, also inside
    // their spans.
    const meta = screen.getByText(/Acme · London, UK · full-time/)
    expect(meta).toHaveClass("text-primary-foreground/80")
    expect(meta).not.toHaveClass("text-foreground")

    const explanation = screen.getByText(/The profile states Python/)
    expect(explanation).toHaveClass("text-primary-foreground/80")
    expect(explanation).not.toHaveClass("text-foreground")

    // The card keeps the design's tokens: forest/lime ground, soft-lime
    // score chip, light CTA — none of that moved with the colour fix.
    expect(title.closest("[class*='bg-primary']")).not.toBeNull()
    expect(screen.getByText(/83 \/ 100 match/i).className).toContain(
      "bg-lime-soft"
    )
  })
})

describe("the next-step panel", () => {
  it("renders its statements in the constant dark forest, both themes", () => {
    renderScreen(
      <NextStepPanel
        statement="Your next application is nearly ready."
        subject="Backend Engineer · Northstar Labs"
        consequence="Review the tailored résumé and 6 employer answers."
        action={null}
      />
    )

    // `type-statement` / `type-card-title` set `color: var(--primary)`,
    // which is lime at night; the `text-forest` utility must ride on the
    // same element so the wash's text stays dark forest.
    expect(screen.getByText(/nearly ready/)).toHaveClass("text-forest")
    expect(screen.getByText(/Northstar Labs/)).toHaveClass("text-forest")
    // The one deliberate exception, per the render: the consequence line
    // reads at the muted tone.
    expect(screen.getByText(/6 employer answers/)).toHaveClass(
      "text-muted-foreground"
    )
  })
})
