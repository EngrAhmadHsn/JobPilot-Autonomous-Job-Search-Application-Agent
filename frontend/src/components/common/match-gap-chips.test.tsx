import { render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"

import {
  MatchGapChips,
  SponsorBadge,
} from "@/components/common/match-gap-chips"

/**
 * WS-22: the gap diagnosis chips.
 *
 * The lists were already in the response but rendered as comma-joined prose.
 * These tests pin the two things a chip row must get right: it shows what is
 * matched and what is missing as separate, readable groups — and it renders
 * **nothing** when there is nothing to say, because an empty "no data" row
 * is noise.
 */

describe("the match gap chips", () => {
  it("groups matched and missing requirements", () => {
    render(
      <MatchGapChips
        matched={["Python", "SQL"]}
        missing={["Kubernetes"]}
      />
    )
    expect(screen.getByText("Matched requirements")).toBeInTheDocument()
    expect(screen.getByText("Missing requirements")).toBeInTheDocument()
    expect(screen.getByText("Python")).toBeInTheDocument()
    expect(screen.getByText("SQL")).toBeInTheDocument()
    expect(screen.getByText("Kubernetes")).toBeInTheDocument()
  })

  it("renders only the group that has items", () => {
    render(<MatchGapChips matched={["Python"]} missing={[]} />)
    expect(screen.getByText("Matched requirements")).toBeInTheDocument()
    expect(screen.queryByText("Missing requirements")).not.toBeInTheDocument()
  })

  it("renders nothing when both lists are empty", () => {
    const { container } = render(<MatchGapChips matched={[]} missing={[]} />)
    expect(container).toBeEmptyDOMElement()
  })
})

describe("the sponsor badge", () => {
  it("shows the register note for a verified employer", () => {
    render(
      <SponsorBadge
        status="verified"
        note="Listed in the USCIS H-1B Employer Data Hub (FY2024, 75 approvals)."
      />
    )
    expect(screen.getByText(/USCIS H-1B Employer Data Hub/)).toBeInTheDocument()
  })

  it("says 'no record' — not 'not a sponsor' — for a miss", () => {
    render(
      <SponsorBadge
        status="not_found"
        note="No entry found in the imported sponsorship registers."
      />
    )
    expect(screen.getByText("No sponsorship record found")).toBeInTheDocument()
    expect(screen.queryByText(/does not sponsor/i)).not.toBeInTheDocument()
  })

  it("renders nothing when no register is imported", () => {
    const { container } = render(<SponsorBadge status="no_data" note={null} />)
    expect(container).toBeEmptyDOMElement()
  })

  it("renders nothing before the lookup has run", () => {
    const { container } = render(<SponsorBadge status={null} note={null} />)
    expect(container).toBeEmptyDOMElement()
  })
})