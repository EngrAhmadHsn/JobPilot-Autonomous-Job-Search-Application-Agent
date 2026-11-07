import { render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"

import { ScoreGrid } from "@/components/common/score-grid"
import { matchPair } from "@/test/factories"

/**
 * WS-20: a component with no evidence must read as *unknown*, never as a
 * number. A missing signal is not a low score, and showing it as one would
 * mislead the operator about why a listing ranked where it did.
 */
describe("ScoreGrid", () => {
  it("shows an unknown state in words instead of a number", () => {
    const pair = matchPair()
    pair.match.component_states = {
      ...pair.match.component_states,
      semantic: "EMBEDDING_PENDING",
      skill: "JOB_REQUIREMENT_MISSING",
    }

    render(<ScoreGrid match={pair.match} />)

    expect(screen.getByText(/pending/i)).toBeDefined()
    expect(screen.getByText(/not stated/i)).toBeDefined()
    // The evidence-coverage line accompanies the components.
    expect(screen.getByText(/based on/i)).toBeDefined()
  })

  it("shows the keyword component alongside the semantic one", () => {
    const pair = matchPair()
    render(<ScoreGrid match={pair.match} />)
    expect(screen.getByText("Keywords")).toBeDefined()
  })

  it("shows the occupational role beside the other components (WS-21)", () => {
    const pair = matchPair()
    render(<ScoreGrid match={pair.match} />)
    expect(screen.getByText("Role")).toBeDefined()
  })

  it("says when a role mismatch capped the score", () => {
    const pair = matchPair()
    pair.match.role_capped = true
    pair.match.role_score = 5
    pair.match.component_states = {
      ...pair.match.component_states,
      role: "PARTIAL_MATCH",
    }
    render(<ScoreGrid match={pair.match} />)
    expect(
      screen.getByText(/unrelated to the candidate's target roles/i)
    ).toBeDefined()
  })
})