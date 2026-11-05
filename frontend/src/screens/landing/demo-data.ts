/**
 * Sample data for the landing page's interactive demonstration.
 *
 * **This module is a fixture, and nothing else.** Every value here is
 * invented for the demonstration; none of it is fetched, and no part of the
 * demo touches the API. The demo is labelled as a demo on screen, and the
 * data is shaped to match the **real** system — the real job sources
 * (Greenhouse, Lever, Remotive), the real tailoring vocabulary (factuality
 * verdicts, keyword coverage), the real approval and evidence concepts — so
 * that what a visitor learns from it is true of the product.
 *
 * The person is fictional. The jobs are fictional. No outcome shown here is
 * a claim about a real submission.
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
      adapter: string
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
  /** The loop phase: perceive → reason → act → observe → evaluate. */
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
    label: "Resume analysis",
    summary:
      "The agent reads an uploaded résumé into a structured candidate profile — skills, experience, education — without inventing a single fact.",
    agent: [
      "Parsing the uploaded document",
      "Extracting skills, roles and dates",
      "Building the candidate profile",
    ],
    panel: {
      kind: "resume",
      name: "Sam Rivera",
      headline: "Backend engineer · 6 years",
      skills: ["Python", "FastAPI", "PostgreSQL", "AWS", "Docker"],
      experience: 3,
      note: "Every field is extracted from the document. The parser never adds a skill the résumé does not contain.",
    },
  },
  {
    id: "discovery",
    phase: "Perceive",
    label: "Job discovery",
    summary:
      "It searches the job boards it is allowed to search, normalizes what it finds, drops duplicates and screens out the obvious mismatches.",
    agent: [
      "Searching Greenhouse listings",
      "Searching Lever and Remotive",
      "Normalizing and de-duplicating 42 listings",
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
      note: "Four of the forty-two listings, shown for the demonstration. Only listings from configured sources appear here.",
    },
  },
  {
    id: "matching",
    phase: "Reason",
    label: "Matching & relevance",
    summary:
      "It scores each listing against the profile and explains the score: what the candidate has, and what is genuinely missing.",
    agent: [
      "Evaluating 42 job descriptions",
      "Comparing technical requirements against your profile",
      "Ranking the strongest matches",
    ],
    panel: {
      kind: "matching",
      title: "Senior Backend Engineer",
      company: "Northwind",
      score: 86.4,
      reasons: [
        { text: "Python and FastAPI are central to the role", have: true },
        { text: "PostgreSQL experience matches the stack", have: true },
        { text: "The role asks for Kubernetes, which is not on the profile", have: false },
        { text: "Six years of backend work meets the seniority bar", have: true },
      ],
      note: "The score is a hybrid of lexical and semantic similarity. The explanation is generated from the same signals, not written afterwards.",
    },
  },
  {
    id: "tailoring",
    phase: "Act",
    label: "Resume tailoring",
    summary:
      "For a chosen job it rewrites the résumé toward the role — and a validator checks every line against the original. Nothing may be claimed that is not already true.",
    agent: [
      "Tailoring the résumé for Northwind",
      "Validating every claim against the profile",
      "Resume tailoring completed",
    ],
    panel: {
      kind: "tailoring",
      title: "Senior Backend Engineer",
      company: "Northwind",
      bullets: [
        {
          before: "Worked on backend services.",
          after: "Built and operated Python/FastAPI backend services handling production traffic.",
          verdict: "grounded",
        },
        {
          before: "Helped with the database.",
          after: "Designed PostgreSQL schemas and queries for the services the team ran.",
          verdict: "grounded",
        },
        {
          before: "Used cloud infrastructure.",
          after: "Deployed services on AWS with Docker.",
          verdict: "tightened",
        },
      ],
      note: "“Tightened” means the wording was sharpened but the underlying fact already existed. A claim with no support in the profile is dropped, not written.",
    },
  },
  {
    id: "preparation",
    phase: "Act",
    label: "Application preparation",
    summary:
      "It fills the application form's fields from the profile and the tailored résumé, and records exactly where every value came from.",
    agent: [
      "Mapping the form's fields to the profile",
      "Attaching the tailored résumé",
      "Preparing the application for review",
    ],
    panel: {
      kind: "preparation",
      fields: [
        { field: "Full name", source: "Candidate profile · personal information" },
        { field: "Email", source: "Candidate profile · personal information" },
        { field: "Phone", source: "Candidate profile · personal information" },
        { field: "Résumé", source: "Tailored résumé for Northwind" },
        { field: "Cover note", source: "Prepared paragraphs, checked for factual support" },
      ],
      note: "A field the profile cannot answer is left for a human. The agent never guesses a value.",
    },
  },
  {
    id: "approval",
    phase: "Evaluate",
    label: "Human review & approval",
    summary:
      "Nothing is submitted until a person approves it. The prepared application waits for an explicit decision, and the agent stops.",
    agent: [
      "Prepared application is ready",
      "Waiting for your approval",
      "No submission has happened",
    ],
    panel: {
      kind: "approval",
      jobTitle: "Senior Backend Engineer",
      company: "Northwind",
      adapter: "Controlled test target",
      note: "Approving runs the prepared payload against the configured adapter. Rejecting submits nothing. Either way, the decision is recorded against the account.",
    },
  },
  {
    id: "verification",
    phase: "Observe",
    label: "Submission & verification",
    summary:
      "After an approved submission, the agent records the evidence: what the page said, the URL it landed on, and a screenshot — and reports only what the evidence shows.",
    agent: [
      "Submitting the approved payload",
      "Reading the confirmation page",
      "Recording the evidence",
    ],
    panel: {
      kind: "verification",
      jobTitle: "Senior Backend Engineer",
      company: "Northwind",
      confirmation: "Thank you — your application has been received.",
      jobUrl: "https://boards.example.test/northwind/jobs/4821",
      note: "“Verified” is claimed only when the confirmation is found. A submission with no readable confirmation is recorded as submitted-but-unverified, never as success.",
    },
  },
]

/** The label the demo wears everywhere, so it is never mistaken for live data. */
export const DEMO_NOTICE =
  "Demo · sample data · this never contacts a real job board or your account"
