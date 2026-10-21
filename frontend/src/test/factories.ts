/**
 * Payload factories.
 *
 * The shapes here are the backend's shapes — taken from the generated
 * OpenAPI schema — so that a test which passes against a factory is testing
 * the console against the real contract, not against a convenient fiction.
 */
import type {
  ApplicationDetail,
  ApplicationList,
  ApprovalDecisionResponse,
  CandidateProfile,
  JobListing,
  JobMatchPair,
  JobRefreshResponse,
  JobSearchResponse,
  ResumeUploadResponse,
  StoredTailoring,
  TailorResponse,
} from "@/lib/api/types"

export function healthResponse() {
  return { status: "ok", service: "agentic-job-applier", environment: "test" }
}

export function candidateProfile(
  overrides: Partial<CandidateProfile> = {}
): CandidateProfile {
  return {
    personal_information: {
      name: "Ada Lovelace",
      title: "AI Engineer",
      email: "ada@example.com",
      phone: "+44 20 7946 0000",
      location: "London, UK",
      website: "",
    },
    summary:
      "Engineer working on analytical engines and applied machine learning.",
    skills: ["Python", "SQL", "Machine Learning"],
    skill_categories: { languages: ["Python"], data: ["SQL"] },
    education: [
      {
        degree: "BSc Mathematics",
        institution: "University of London",
        dates: "1840-1843",
        gpa: "",
        details: [],
      },
    ],
    experience: [
      {
        title: "Analyst",
        company: "Analytical Engine Project",
        dates: "1842-1843",
        bullets: ["Designed the first published algorithm."],
        years: 1,
      },
    ],
    projects: [
      {
        name: "Bernoulli Numbers",
        subtitle: "Notes",
        tech: "Mathematics",
        bullets: ["Computed them."],
      },
    ],
    certifications: [],
    achievements: [],
    work_preferences: {
      remote_preference: "hybrid",
      preferred_locations: ["London"],
      min_salary: null,
      work_authorization: null,
      employment_types: ["full-time"],
    },
    ...overrides,
  }
}

export function resumeUploadResponse(): ResumeUploadResponse {
  return {
    profile_id: "profile-1",
    warnings: ["Profile has no parseable email"],
    profile: candidateProfile(),
  }
}

export function profileResponse() {
  return { profile_id: "profile-1", profile: candidateProfile() }
}

export function jobListing(overrides: Partial<JobListing> = {}): JobListing {
  return {
    id: "greenhouse:1",
    source: "greenhouse",
    source_job_id: "1",
    title: "AI Engineer",
    company: "Acme",
    description: "Build machine learning systems for a payments platform.",
    location: "London, UK",
    remote_policy: "hybrid",
    employment_type: "full-time",
    salary: "£90,000",
    currency: "GBP",
    seniority: "senior",
    required_skills: ["Python", "SQL"],
    preferred_skills: ["Kubernetes"],
    experience_requirements: "5+ years",
    education_requirements: "BSc or above",
    application_url: "http://127.0.0.1:8901/basic",
    company_url: null,
    posted_at: "2026-10-20",
    metadata: {},
    ...overrides,
  }
}

export function matchPair(overrides: Partial<JobMatchPair> = {}): JobMatchPair {
  return {
    job: jobListing(),
    match: {
      overall_score: 82.5,
      semantic_score: 80,
      skill_score: 90,
      experience_score: 75,
      seniority_score: 80,
      location_score: 100,
      preference_score: 70,
      missing_requirements: ["Kubernetes"],
      matched_requirements: ["Python", "SQL"],
      explanation:
        "The profile states Python and SQL, which the listing asks for.",
    },
    ...overrides,
  }
}

export function jobSearchResponse(
  overrides: Partial<JobSearchResponse> = {}
): JobSearchResponse {
  return {
    profile_id: "profile-1",
    results: [matchPair()],
    source_errors: {},
    stats: { found: 12, dropped: 1, deduped: 11, persisted: 11, stored: 11 },
    degraded: false,
    ...overrides,
  }
}

export function jobDetail() {
  return { job: jobListing() }
}

export function matchesHistory() {
  return {
    profile_id: "profile-1",
    matches: [
      {
        profile_id: "profile-1",
        job_id: "greenhouse:1",
        scores: {
          overall_score: 82.5,
          semantic_score: 80,
          skill_score: 90,
          experience_score: 75,
          seniority_score: 80,
          location_score: 100,
          preference_score: 70,
          missing_requirements: ["Kubernetes"],
          matched_requirements: ["Python", "SQL"],
        },
        explanation:
          "The profile states Python and SQL, which the listing asks for.",
        created_at: "2026-10-21T10:00:00Z",
      },
    ],
  }
}

export function tailorResponse(
  overrides: Partial<TailorResponse> = {}
): TailorResponse {
  return {
    tailoring_id: "tailoring-1",
    profile_id: "profile-1",
    job_id: "greenhouse:1",
    tailored: {
      summary: "AI Engineer with analytical and machine learning experience.",
      highlighted_skills: ["Python", "SQL"],
      experience: [
        {
          title: "Analyst",
          company: "Analytical Engine Project",
          bullets: ["Designed the first published algorithm."],
        },
      ],
      projects: [],
      cover_letter: "Dear hiring team, I build analytical systems.",
    },
    factuality: {
      passed: true,
      removed_skills: [],
      removed_experience: [],
      removed_projects: [],
      violations: [],
    },
    ats_report: {
      keyword_coverage: {
        required_coverage: 0.5,
        required_hit: ["python"],
        required_missing: ["kubernetes"],
        preferred_coverage: 0,
        preferred_hit: [],
        preferred_missing: ["kubernetes"],
      },
      section_completeness: { summary: true, experience: true, skills: true },
      format_risks: [],
      title_alignment: 90,
      score: 85,
      notes: [],
    },
    insights: {
      responsibilities: ["Build machine learning systems"],
      tech_stack: ["Python", "SQL"],
      seniority_signals: ["5+ years"],
      culture_flags: [],
      summary: "An AI Engineer role in London building ML systems.",
    },
    docx_path: "./data/tailored/profile-1-greenhouse-1.docx",
    ...overrides,
  }
}

export function tailoredResponse(): StoredTailoring {
  return { ...tailorResponse(), created_at: "2026-10-21T10:00:00Z" }
}

export function approvalDecision(
  overrides: Partial<ApprovalDecisionResponse> = {}
): ApprovalDecisionResponse {
  return {
    approval_id: "approval-1",
    workflow_id: "workflow-1",
    adapter_name: "fake-ats",
    status: "verified",
    success: true,
    message: "The application was submitted and verified.",
    evidence: {
      url: "http://127.0.0.1:8901/submitted",
      confirmation_text: "Application submitted",
      status: "submitted",
      screenshot_path: "./data/evidence/workflow-1.png",
      trace_path: "workflow-1.trace.json",
    },
    metadata: { job_url: "http://127.0.0.1:8901/basic" },
    ...overrides,
  }
}

export function applicationSummary(): ApplicationList["items"][number] {
  return {
    id: "application-1",
    profile_id: "profile-1",
    job_id: "greenhouse:1",
    workflow_id: "workflow-1",
    approval_id: "approval-1",
    adapter_name: "fake-ats",
    job_url: "http://127.0.0.1:8901/basic",
    job_title: "AI Engineer",
    company_name: "Acme",
    status: "verified",
    tailored_resume_id: null,
    submitted_at: "2026-10-21T10:05:00Z",
    verified_at: "2026-10-21T10:06:00Z",
    application_url: null,
    notes: null,
    created_at: "2026-10-21T10:00:00Z",
    updated_at: "2026-10-21T10:06:00Z",
  }
}

export function applicationList(): ApplicationList {
  return {
    items: [applicationSummary()],
    total: 1,
    limit: 50,
    offset: 0,
  }
}

export function applicationDetail(): ApplicationDetail {
  return {
    ...applicationSummary(),
    events: [
      {
        id: 1,
        event_type: "application_created",
        actor: "agent",
        from_status: null,
        to_status: "prepared",
        metadata: {},
        recorded_at: "2026-10-21T10:00:00Z",
      },
      {
        id: 2,
        event_type: "approval_granted",
        actor: "human:ada",
        from_status: "prepared",
        to_status: "awaiting_approval",
        metadata: { reason: "Looks right" },
        recorded_at: "2026-10-21T10:02:00Z",
      },
    ],
  }
}

export function applicationEvidence() {
  return {
    evidence: [
      {
        confirmation_text: "Application submitted",
        status: "submitted",
        screenshot_path: "./data/evidence/workflow-1.png",
        trace_path: "workflow-1.trace.json",
        job_url: "http://127.0.0.1:8901/basic",
        recorded_at: "2026-10-21T10:05:00Z",
      },
    ],
  }
}

export function refreshResponse(): JobRefreshResponse {
  return {
    stats: {
      found: 40,
      dropped: 3,
      deduped: 37,
      persisted: 37,
      embedded: 35,
      screened_out: 1,
      admission_capped: 0,
    },
    source_errors: {},
    embedding_requests_planned: 35,
    embedding_requests_used: 35,
    quota_exhausted: false,
    degraded_embedding: false,
  }
}
