/**
 * Sample data for the landing page's interactive demonstration.
 *
 * **This module is a fixture, and nothing else.** Every value here is
 * invented for the demonstration; none of it is fetched, and no part of the
 * demo touches the API. The demo is labelled as a demo on screen, and the
 * data is shaped to match the **real** system (the real job sources:
 * Greenhouse, Lever and Remotive; the real tailoring verdicts and keyword
 * coverage; the real approval and evidence concepts), so that what a visitor
 * learns from it is true of the product.
 *
 * The person is fictional. The jobs are fictional. No outcome shown here is
 * a claim about a real submission.
 *
 * Copy rules: state what happens and what the reader gets. No sentence may
 * only restate the one before it, and no claim may exceed what the code does.
 */

export interface DiscoveryRow {
  title: string
  company: string
  source: string
  location: string
}

export interface MatchReason {
  text: string
  /** Whether the reason is something the candidate has, or lacks. */
  have: boolean
}

export interface TailorBullet {
  before: string
  after: string
  /** The factuality verdict the tailoring validator would attach. */
  verdict: "grounded" | "tightened"
}

export interface PreparedField {
  field: string
  source: string
}

/** The seven stages of the agent loop, mirrored one-to-one by the demo. */
export type DemoPanel =
  | {
      kind: "resume"
      name: string
      headline: string
      skills: string[]
      experience: number
      note: string
    }
  | { kind: "discovery"; rows: DiscoveryRow[]; note: string }
  | {
      kind: "matching"
      title: string
      company: string
      score: number
      reasons: MatchReason[]
      note: string
    }
  | {
      kind: "tailoring"
      title: string
      company: string
      bullets: TailorBullet[]
      note: string
    }
  | { kind: "preparation"; fields: PreparedField[]; note: string }
  | {
      kind: "approval"
      jobTitle: string
      company: string
      note: string
    }
  | {
      kind: "verification"
      jobTitle: string
      company: string
      confirmation: string
      jobUrl: string
      note: string
    }

export interface DemoStage {
  id: string
  /** The loop phase: perceive, reason, act, observe, evaluate. */
  phase: string
  label: string
  summary: string
  /** Status lines the agent reports, in the product's own plain language. */
  agent: string[]
  panel: DemoPanel
}

export const DEMO_STAGES: DemoStage[] = [
  {
    id: "resume",
    phase: "Perceive",
    label: "Résumé analysis",
    summary: "Your résumé, read into a profile.",
    agent: [
      "Reading the document",
      "Extracting skills, roles and dates",
      "Building your profile",
    ],
    panel: {
      kind: "resume",
      name: "Sam Rivera",
      headline: "Backend engineer, 6 years",
      skills: ["Python", "FastAPI", "PostgreSQL", "AWS", "Docker"],
      experience: 3,
      note: "Nothing is added that the résumé does not say.",
    },
  },
  {
    id: "discovery",
    phase: "Perceive",
    label: "Job discovery",
    summary: "It searches the boards you pick and removes duplicates.",
    agent: [
      "Searching your boards",
      "Collecting 42 listings",
      "Removing duplicates",
    ],
    panel: {
      kind: "discovery",
      rows: [
        {
          title: "Senior Backend Engineer",
          company: "Northwind",
          source: "greenhouse",
          location: "Remote (EU)",
        },
        {
          title: "Platform Engineer",
          company: "Halcyon Labs",
          source: "lever",
          location: "Berlin",
        },
        {
          title: "Python Engineer, Payments",
          company: "Ledgerly",
          source: "greenhouse",
          location: "Remote",
        },
        {
          title: "Backend Developer",
          company: "Brightfold",
          source: "remotive",
          location: "Remote (worldwide)",
        },
      ],
      note: "Four of the forty-two found.",
    },
  },
  {
    id: "matching",
    phase: "Reason",
    label: "Matching and relevance",
    summary: "Every opening scored against you, with the reasons.",
    agent: [
      "Reading 42 job descriptions",
      "Comparing against your profile",
      "Ranking the best matches",
    ],
    panel: {
      kind: "matching",
      title: "Senior Backend Engineer",
      company: "Northwind",
      score: 86.4,
      reasons: [
        { text: "Python and FastAPI are central to the role", have: true },
        { text: "PostgreSQL experience matches the stack", have: true },
        {
          text: "The role asks for Kubernetes, which is not on your profile",
          have: false,
        },
        {
          text: "Six years of backend work meets the seniority bar",
          have: true,
        },
      ],
      note: "The reasons come from the same signals as the score.",
    },
  },
  {
    id: "tailoring",
    phase: "Act",
    label: "Résumé tailoring",
    summary: "Your résumé, rewritten for one job.",
    agent: [
      "Tailoring the résumé for Northwind",
      "Checking every line against your profile",
      "Tailoring complete",
    ],
    panel: {
      kind: "tailoring",
      title: "Senior Backend Engineer",
      company: "Northwind",
      bullets: [
        {
          before: "Worked on backend services.",
          after:
            "Built and operated Python/FastAPI backend services handling production traffic.",
          verdict: "grounded",
        },
        {
          before: "Helped with the database.",
          after:
            "Designed PostgreSQL schemas and queries for the services the team ran.",
          verdict: "grounded",
        },
        {
          before: "Used cloud infrastructure.",
          after: "Deployed services on AWS with Docker.",
          verdict: "tightened",
        },
      ],
      note: "A claim your résumé cannot support is dropped.",
    },
  },
  {
    id: "preparation",
    phase: "Act",
    label: "Application preparation",
    summary: "The application form, filled in for you.",
    agent: [
      "Filling the form from your profile",
      "Attaching the tailored résumé",
      "Ready for your review",
    ],
    panel: {
      kind: "preparation",
      fields: [
        {
          field: "Full name",
          source: "Your profile",
        },
        { field: "Email", source: "Your profile" },
        { field: "Phone", source: "Your profile" },
        { field: "Résumé", source: "Tailored for Northwind" },
        {
          field: "Cover note",
          source: "Written from your experience",
        },
      ],
      note: "A field it cannot answer is left for you. Nothing is guessed.",
    },
  },
  {
    id: "approval",
    phase: "Evaluate",
    label: "Human review and approval",
    summary: "It waits here for you.",
    agent: ["Application ready", "Waiting for you", "Nothing sent yet"],
    panel: {
      kind: "approval",
      jobTitle: "Senior Backend Engineer",
      company: "Northwind",
      note: "Approve sends it. Reject sends nothing. Either way, it is on your record.",
    },
  },
  {
    id: "verification",
    phase: "Observe",
    label: "Submission and verification",
    summary: "After you approve, it records what came back.",
    agent: ["Submitting", "Reading the confirmation", "Recording the evidence"],
    panel: {
      kind: "verification",
      jobTitle: "Senior Backend Engineer",
      company: "Northwind",
      confirmation: "Thank you. Your application has been received.",
      jobUrl: "https://boards.example.test/northwind/jobs/4821",
      note: "Verified only if the confirmation was found. Otherwise it says unverified.",
    },
  },
]

/** The label the demo wears everywhere, so it is never mistaken for live data. */
export const DEMO_NOTICE =
  "Sample data. This never contacts a real job board or your account."
