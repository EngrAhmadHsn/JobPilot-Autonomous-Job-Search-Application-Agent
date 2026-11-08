/**
 * Payload factories.
 *
 * The shapes here are the backend's shapes — taken from the generated
 * OpenAPI schema — so that a test which passes against a factory is testing
 * the console against the real contract, not against a convenient fiction.
 */
import type {
  AdminOverview,
  ApplicationDetail,
  ApplicationList,
  ApprovalDecisionResponse,
  AuditEvent,
  AuditPage,
  CandidateProfile,
  JobListing,
  JobMatchPair,
  JobSearchResponse,
  ResumeUploadResponse,
  RunAccepted,
  RunDetail,
  RunSummary,
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
    application_profile: {
      professional: {
        total_experience_years: null,
        seniority_level: null,
        current_title: null,
        skill_experience_years: {},
        portfolio_url: null,
        linkedin_url: null,
      },
      preferences: {
        preferred_locations: [],
        remote_preference: null,
        employment_types: [],
        willing_to_relocate: null,
        target_roles: [],
      },
      answers: {
        work_authorization: {
          legally_authorized: null,
          requires_sponsorship: null,
          authorized_countries: [],
          citizenship_status: null,
          status_category: null,
        },
        compensation: {
          expected_salary: null,
          expected_currency: null,
          expected_period: null,
          current_salary: null,
          current_currency: null,
          current_period: null,
        },
        notice: { notice_days: null, available_from: null, immediate: null },
      },
      confirmed_fields: [],
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

/** The user-confirmed application profile, shaped like the WS-20 routes. */
export function applicationProfileResponse(
  applicationProfile = candidateProfile().application_profile
) {
  return { profile_id: "profile-1", application_profile: applicationProfile }
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
      lexical_score: 70,
      skill_score: 90,
      experience_score: 75,
      seniority_score: 80,
      location_score: 100,
      preference_score: 70,
      // WS-21: the occupational-role comparison.
      role_score: 90,
      role_family: "data_science_ml",
      role_family_confidence: 0.9,
      role_targets: ["AI Engineer"],
      role_target_source: "user",
      role_capped: false,
      evidence_coverage: 100,
      component_states: {
        semantic: "MATCHED",
        lexical: "MATCHED",
        skill: "MATCHED",
        experience: "MATCHED",
        seniority: "MATCHED",
        location: "MATCHED",
        preference: "MATCHED",
        role: "MATCHED",
      },
      notes: [],
      missing_requirements: ["Kubernetes"],
      matched_requirements: ["Python", "SQL"],
      missing_keywords: [],
      matched_keywords: ["python", "sql"],
      sponsor_status: null,
      sponsor_note: null,
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
    stats: {
      found: 12,
      dropped: 1,
      deduped: 11,
      persisted: 11,
      stored: 11,
      semantic_covered: 11,
    },
    degraded: false,
    semantic_coverage: 100,
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
    style: {
      findings: [],
      bullet_count: 1,
      quantified_count: 0,
      quantified_ratio: 0,
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

/**
 * The authenticated principal (WS-14).
 *
 * The console is signed in by default in the mocked API, so the screens
 * render without a sign-in step. A test that needs the signed-out state
 * overrides `GET /api/auth/me` with a 401.
 */
export function identityResponse() {
  return {
    id: "user-1",
    email: "operator@example.com",
    full_name: "Operator",
    is_active: true,
    is_superuser: false,
    is_verified: true,
  }
}

/** One audit row, shaped exactly like `GET /api/audit` sends. */
export function auditEvent(overrides: Partial<AuditEvent> = {}): AuditEvent {
  return {
    id: 1,
    recorded_at: "2026-10-21T10:00:00Z",
    action: "job.search",
    actor: "agent",
    actor_kind: "agent",
    actor_id: "greenhouse",
    resource: "profile-1",
    outcome: "success",
    workflow_id: null,
    metadata: {},
    ...overrides,
  }
}

/**
 * A page of audit rows with a little of everything: agent steps, a human
 * decision, a workflow, and one blocked action (so the "needs attention"
 * path is exercised without a test having to build its own).
 */
export function auditResponse(): AuditPage {
  const events: AuditEvent[] = [
    auditEvent({
      id: 5,
      action: "application.verify",
      actor: "agent",
      actor_kind: "agent",
      outcome: "success",
      workflow_id: "workflow-1",
      recorded_at: "2026-10-21T10:06:00Z",
    }),
    auditEvent({
      id: 4,
      action: "application.submit",
      actor: "agent",
      actor_kind: "agent",
      outcome: "success",
      workflow_id: "workflow-1",
      recorded_at: "2026-10-21T10:05:00Z",
    }),
    auditEvent({
      id: 3,
      action: "application.approve",
      actor: "human:operator",
      actor_kind: "user",
      outcome: "success",
      workflow_id: "workflow-1",
      recorded_at: "2026-10-21T10:02:00Z",
    }),
    auditEvent({
      id: 2,
      action: "application.blocked_challenge",
      actor: "agent",
      actor_kind: "agent",
      outcome: "blocked",
      workflow_id: "workflow-2",
      recorded_at: "2026-10-21T09:40:00Z",
    }),
    auditEvent({
      id: 1,
      action: "resume.upload",
      actor: "human:operator",
      actor_kind: "user",
      outcome: "success",
      recorded_at: "2026-10-21T09:00:00Z",
    }),
  ]
  return { events, count: events.length }
}

/** The platform overview, shaped like `GET /api/admin/overview`. */
export function adminOverviewResponse(): AdminOverview {
  return {
    accounts: { total: 3, active: 3, superusers: 1 },
    applications: {
      total: 4,
      by_status: { verified: 2, awaiting_approval: 1, rejected: 1 },
    },
    workflows: { total: 3 },
    audit: {
      total: 12,
      by_outcome: { success: 10, blocked: 1, error: 1 },
      by_actor_kind: { agent: 8, user: 4 },
    },
    corpus: { jobs: 5854 },
    generated_at: "2026-10-21T10:10:00Z",
  }
}

/** A refresh the API accepted as durable work (WS-18). */
export function runAccepted(overrides: Partial<RunAccepted> = {}): RunAccepted {
  return {
    run_id: "run-1",
    status: "QUEUED",
    job_type: "refresh",
    correlation_id: "corr-1",
    created_at: "2026-11-05T10:00:00Z",
    existing: false,
    ...overrides,
  }
}

/** One run, as `src.runs.service.run_to_dict` serialises it. */
export function runSummary(overrides: Partial<RunSummary> = {}): RunSummary {
  return {
    id: "run-1",
    job_type: "refresh",
    status: "COMPLETED",
    priority: 30,
    owner_id: "user-1",
    correlation_id: "corr-1",
    parent_run_id: null,
    embedding_model: null,
    embedding_dimension: null,
    created_at: "2026-11-05T10:00:00Z",
    started_at: "2026-11-05T10:00:01Z",
    completed_at: "2026-11-05T10:02:00Z",
    heartbeat_at: "2026-11-05T10:02:00Z",
    lease: { owner: null, expires_at: null },
    attempt_count: 1,
    total_items: 37,
    completed_items: 37,
    failed_items: 0,
    skipped_items: 0,
    remaining_items: 0,
    progress_percent: 100,
    last_error: null,
    last_error_kind: null,
    metadata: {
      refresh: {
        found: 40,
        deduped: 37,
        persisted: 37,
        screened_out: 0,
        admission_capped: 0,
        source_errors: {},
        embedding_run_id: "run-embed-1",
        degraded: false,
      },
    },
    resumable: false,
    cancellable: false,
    ...overrides,
  }
}

/** One run with its checkpoint, item summary and events. */
export function runDetail(overrides: Partial<RunDetail> = {}): RunDetail {
  const base = runSummary(overrides)
  return {
    ...base,
    items: {
      queued: 0,
      running: 0,
      retry_wait: 0,
      completed: base.completed_items,
      failed: base.failed_items,
      cancelled: base.skipped_items,
    },
    events: [
      {
        id: 1,
        event: "run.created",
        at: "2026-11-05T10:00:00Z",
        actor: "system",
        actor_kind: "system",
        message: "refresh run accepted with 1 item(s)",
        metadata: {},
      },
      {
        id: 2,
        event: "run.completed",
        at: "2026-11-05T10:02:00Z",
        actor: "system",
        actor_kind: "system",
        message: "refresh run completed",
        metadata: {},
      },
    ],
    failed_work_items: [],
    checkpoint: {
      last_event: null,
      heartbeat_at: base.heartbeat_at,
    },
    ...overrides,
  }
}

export function runsResponse(runs: RunSummary[] = [runSummary()]) {
  return { runs, count: runs.length }
}
