# Autonomous AI Job Application Agent - Architecture Document

## 1. System Overview
The Autonomous AI Job Application Agent is a production-oriented system that:
- Accepts candidate resumes
- Parses and extracts structured candidate information
- Searches and normalizes job listings from multiple sources
- Matches jobs against candidate profile using hybrid scoring
- Ranks jobs and explains match scores
- Tailors resumes and generates cover letters
- Navigates application websites using browser automation when necessary
- Submits applications with human approval in initial versions

## 2. System Architecture
The system follows a modular, service-oriented architecture with clear separation between development-time components (Cursor-based) and runtime components.

### 2.1 Planned Components
- FastAPI backend service
- LangGraph orchestration engine
- Pydantic data models
- PostgreSQL database
- Playwright browser automation client
- Job source adapters (LinkedIn, Indeed, etc.)
- Resume parsing pipeline
- Matching engine with hybrid scoring
- Application submission workflow

### 2.2 Implemented Components
- Cursor MCP configuration (.cursor/mcp.json)
- Cursor skills documentation (5 SKILL.md files)
- Cursor hooks configuration (.cursor/hooks.json)
- Project rules (.cursor/rules/project.mdc)
- Audit logging hooks (format_python.py, audit_mcp.py)

### 2.2 Experimental Components
- Browser Use MCP (not configured, planned for future evaluation)

## 2. Component Architecture
### 2.1 Core Services
- **API Gateway**: FastAPI application handling REST endpoints
- **Orchestration Layer**: LangGraph managing stateful workflows
- **Data Layer**: PostgreSQL storing all application data
- **Parsing Layer**: Resume parsing service using document parsers
- **Matching Layer**: Job matching service with hybrid scoring
- **Automation Layer**: Playwright browser automation client

### 2.2 Development-time Components
- **Cursor Skills**: Documentation and procedures for building components
- **Cursor Hooks**: Development-time automation and validation hooks
- **Cursor Rules**: Project-wide constraints and best practices
- **Cursor MCPs**: Development-time capability interfaces

## 3. Runtime Architecture
The runtime consists of the following components:

- **FastAPI Application**: Hosts REST APIs for resume upload, job search, matching, and application submission
- **LangGraph Runtime**: Manages stateful agent workflows with persistence
- **Playwright Client**: Handles browser automation for application submission workflows
- **PostgreSQL Database**: Stores candidate profiles, job listings, application history
- **Job Adapters**: Connect to various job boards via HTTP APIs or adapters
- **Security Layer**: Enforces prompt injection defense, secret isolation, domain allowlists

## 4. Agent Architecture
The agent follows deterministic Python code with structured outputs, using LangGraph for stateful workflows:

- **State Representation**: Pydantic models representing CandidateProfile, JobListing, etc.
- **Workflow States**: Defined in LangGraph nodes with clear entry/exit conditions
- **Tool Integration**: Narrow contracts with structured outputs for each tool
- **Retry Logic**: Explicit retry mechanisms with timeout handling
- **Human Approval**: Manual intervention points for critical actions (application submission)
- **Observability**: Logging and metrics collection for all external actions

## 5. LangGraph Workflow
The core workflow follows this pattern:

1. **Resume Intake**: Upload → Parsing → CandidateProfile creation
2. **Job Search**: Query job sources → Normalization → JobListing collection
3. **Matching**: CandidateProfile + JobListing → Hybrid scoring
4. **Ranking**: Score-based ranking with explanations
5. **Tailoring**: Resume and cover letter generation
6. **Application**: Form filling → Submission → Verification

Each stage uses deterministic code where possible, with LLM assistance only where explanation or ambiguous parsing is needed.

## 5. MCP Architecture
- **Cursor MCP**: Configured in .cursor/mcp.json, provides development-time access to Playwright capabilities
- **Application MCP**: Not yet implemented; would provide runtime access to application capabilities via standardized interfaces
- **Skill MCPs**: Each skill defines its own MCP interface for development-time use

## 6. Browser Automation Architecture
- **Primary**: Playwright MCP (development-time) for testing and inspection
- **Runtime**: Playwright Python client (to be implemented) for actual browser automation
- **Policy**: Prefer semantic/accessibility locators, avoid coordinate-based clicking, verify actions, use isolated contexts

## 7. Data Architecture
Primary data store: PostgreSQL with the following tables:
- Candidate
- Resume
- CandidateProfile (structured fields: personal_information, education, experience, skills, projects, certifications, achievements, languages, preferred_roles, preferred_locations, work_preferences, constraints)
- Experience
- Education
- Skill
- Job
- Company
- JobMatch
- TailoredResume
- CoverLetter
- Application
- ApplicationEvent

## 8. Security Boundaries
- **Web Content**: Treated as untrusted data; never as instructions
- **Prompt Injection**: Defense via tool policy (code) rather than model whim
- **Secrets**: Isolated in environment variables/config; never in prompts or logs
- **Domain Allowlists**: Restrict fetch and browser navigation to approved domains
- **Least Privilege**: Tools have minimal required permissions
- **Audit Logs**: Record all external actions without exposing secrets
- **Human Approval**: Required for irreversible actions (application submission)

## 9. Development-time vs Runtime Components
| Category | Development-time | Runtime |
|----------|------------------|---------|
| Configuration | .cursor/ files, skills, rules | pyproject.toml, Dockerfile |
| Orchestration | LangGraph definitions in Cursor | LangGraph runtime |
| Browser Automation | Cursor Playwright MCP | Playwright Python client |
| Security | Rules and hooks in Cursor | Security middleware in FastAPI |
| Data Storage | Not applicable | PostgreSQL database |

## 11. Directory Structure (Planned)
```
project-root/
├── docs/                  # Documentation
│   ├── ARCHITECTURE.md
│   └── PROJECT_PLAN.md
├── src/                   # Application source code (to be implemented)
│   ├── api/               # FastAPI endpoints
│   ├── models/            # Pydantic models
│   ├── services/          # Business logic
│   ├── utils/             # Utility functions
│   └── agent/             # LangGraph orchestration
├── tests/                 # Test suite
├── .cursor/               # Cursor configuration (IMPLEMENTED)
│   ├── mcp.json           # Playwright MCP (IMPLEMENTED)
│   ├── hooks.json         # Hooks configuration (IMPLEMENTED)
│   ├── rules/             # Project rules (IMPLEMENTED)
│   └── skills/            # Skill documentation (IMPLEMENTED)
├── docs/ARCHITECTURE.md   # Architecture document (created)
└── pyproject.toml         # Dependencies and configuration
```

## 12. Data Flow
1. **Resume Upload**: User uploads resume file → FastAPI receives request
2. **Parsing**: Resume parsing service extracts text → CandidateProfile creation
3. **Validation**: CandidateProfile validated against source document
4. **Storage**: Profile stored in PostgreSQL
5. **Job Search**: Query job sources → Normalization → JobListing objects
6. **Matching**: Hybrid scoring between CandidateProfile and JobListing
7. **Ranking**: Jobs ranked with explanations
8. **Tailoring**: Resume and cover letter customized for specific job
9. **Application**: Browser automation fills forms → Submission verification
10. **Verification**: System checks submission status and records outcome

## 13. Major Interfaces
- **FastAPI REST API**: /resumes, /jobs/search, /jobs/{id}, /applications
- **Playwright Client**: Programmatic browser control for application workflows
- **MCP Tool Calls**: Development-time commands for testing and inspection
- **CLI Tools**: Python scripts for parsing, validation, and testing

## 14. Status Legend
- **PLANNED**: Components that need to be implemented
- **IMPLEMENTED**: Components that exist and are functional
- **EXPERIMENTAL**: Components under evaluation or not yet configured

**Current Status**:
- **PLANNED**: FastAPI service, LangGraph orchestration, database schema, job adapters, matching engine, resume tailoring, application submission workflow
- **IMPLEMENTED**: Cursor configuration (MCP, hooks, rules, skills), audit logging hooks, project rules
- **EXPERIMENTAL**: Browser Use MCP (not configured)

This document reflects the current state of the project as of 9/13/2026.

## Autonomous Submission: confirmation and runtime capabilities

This project plan is explicitly intended to evolve from discovery and matching into a system that can autonomously submit job applications under controlled conditions. The documented Phase 2 work (see `docs/PROJECT_PLAN.md`) outlines the expected runtime capabilities required to reach that goal.

Runtime components required for autonomous submission

- `ApplicationAdapter` implementations: API-backed adapters (Greenhouse, Lever, Ashby) and a Playwright-backed `GenericBrowserAdapter` for sites without APIs.
- `LangGraph` graphs that orchestrate prepare → present → approve → submit → verify with persisted evidence.
- Playwright Python client as the runtime browser automation layer; Cursor Playwright MCP remains development-only.
- A permission registry that maps which adapters/tools can `read`, `prepare`, `submit`, and `verify`.
- Evidence capture: screenshots, navigation traces, and confirmation parsing for non-repudiation.

Does the current project plan match the goal?

Yes — `docs/PROJECT_PLAN.md` and the architecture notes already target an autonomous end-to-end flow. The added Phase 2 section explicitly prioritizes vendor APIs first, deterministic HTTP where possible, and Playwright-based automation as a last resort; it also enforces human-approval-by-default, evidence-based verification, and a staged adapter-first implementation approach.

Next steps to implement runtime submission (high-level):

1. Implement `ApplicationAdapter` contract and the first API adapters (Greenhouse, Lever).
2. Implement `GenericBrowserAdapter` with Playwright client and fake-ATS tests.
3. Build LangGraph workflows with approval/verification nodes and evidence persistence.
4. Implement the MCP/permission registry and domain allowlist enforcement in runtime code.
5. Harden security controls per `docs/SECURITY.md` before enabling live autonomous submissions.
