import { readFileSync } from "node:fs"
import { resolve } from "node:path"

import { render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"

import { AtsPanel } from "./report-panels"
import { tailorResponse } from "@/test/factories"

/*
  WS-37: the weights the UI prints must be the analyzer's own constants.

  The audit (JOBPILOT-UX-01-AUDIT.md §3, row 8) verified that the master
  prompt's 45/20/20/15 matches `src/resume/ats.py:36-39`. This test keeps it
  true in both directions: it reads the Python source for the values, and it
  renders the ATS panel to check the copy that reaches a person. If either
  side drifts, this fails — the numbers never print without a pin.
*/

// The suite runs with cwd = frontend/, so the Python source is one level up.
const ATS_PY = readFileSync(
  resolve(process.cwd(), "..", "src", "resume", "ats.py"),
  "utf8"
)

describe("the ATS weights the console prints", () => {
  it("matches src/resume/ats.py ATS_WEIGHTS exactly", () => {
    expect(ATS_PY).toContain("ATS_WEIGHTS")
    expect(ATS_PY).toContain('"keywords": 0.45')
    expect(ATS_PY).toContain('"sections": 0.20')
    expect(ATS_PY).toContain('"title_alignment": 0.20')
    expect(ATS_PY).toContain('"format_safety": 0.15')
  })

  it("prints those weights in the ATS panel copy", () => {
    render(<AtsPanel ats={tailorResponse().ats_report} />)

    expect(screen.getByText("ATS report")).toBeInTheDocument()
    expect(screen.getByText(/keywords 45%/)).toBeInTheDocument()
    expect(screen.getByText(/sections 20%/)).toBeInTheDocument()
    expect(screen.getByText(/title alignment 20%/)).toBeInTheDocument()
    expect(screen.getByText(/format safety 15%/)).toBeInTheDocument()
  })

  it("never claims coverage guarantees acceptance or an interview", () => {
    render(<AtsPanel ats={tailorResponse().ats_report} />)
    expect(screen.getByText(/A measurement, not a promise/)).toBeInTheDocument()
  })
})
