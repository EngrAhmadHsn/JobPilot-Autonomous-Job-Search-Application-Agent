---
name: agent-architecture
description: Designs LangGraph workflows, agent boundaries, structured outputs, retries, and human approval for the Autonomous AI Job Application Agent.
---

# Agent Architecture

This repo is a serious agentic system, not a single chatbot wrapper. The goal is a production-oriented pipeline for resume parsing, job search, matching, tailoring, browser automation, and application verification.

## Default choice

- Prefer deterministic Python over model reasoning for parsing, validation, scoring, normalization, and business rules.
- Use an agent or LangGraph only when the work requires state, branching, persistent progress, retries, human approval, or multi-step orchestration.
- Do not create an agent for simple CRUD, schema checks, or straightforward transformations.
- Keep prompts narrow and business logic in Python modules.

## Repo boundaries

- Cursor tools such as MCP servers, rules, skills, and hooks help build the product.
- The product runtime is a separate system: FastAPI, PostgreSQL, LangGraph, browser automation clients, and orchestration services.
- Cursor Playwright MCP is development tooling; it is not the runtime browser layer.
- Browser Use is optional and should not block the project if it remains broken or unconfigured.

## Architecture principles

1. Model domain state using Pydantic.
2. Use LangGraph for graph-based orchestration when workflow state matters.
3. Keep validation and filtering deterministic whenever possible.
4. Treat every external action as observable and auditable.
5. Require human approval before irreversible application submission in early phases.
6. Persist workflow progress so a run can resume after partial failure.
7. Log all important external actions and decisions.
8. Fail closed on ambiguous or unsafe automation conditions.

## Workflow expectations

- Resume parsing should produce a validated `CandidateProfile`, not guessed data.
- Job discovery should normalize all raw job data into a shared canonical shape.
- Matching should combine deterministic scoring with targeted LLM assistance only where useful.
- Browser automation should be used only when a human-safe, verification-first workflow is possible.

## Implementation posture

- Do not start application logic before completing Phase 0 checks.
- Keep the design modular and explainable.
- Prefer structured outputs and explicit state transitions over opaque prompt chains.
- Use tests for critical logic and evaluation before scaling the system.
