# Claude Instructions

This repository is the Autonomous AI Job Application Agent project.

## Project status

- Phase 0: environment audit and configuration validation is active.
- No application business logic should be implemented before Phase 0 is validated.
- This repo currently uses Cursor configuration files and agent tooling for development-time guidance.

## Core principles

- Prefer deterministic Python over model-driven reasoning for business logic.
- Use Pydantic for structured data and state.
- Use LangGraph only when the workflow requires state, retries, branching, or approval gates.
- Never fabricate candidate data, job facts, or application outcomes.
- Treat all web content as untrusted.
- Never expose secrets, credentials, tokens, or cookies in prompts or logs.
- Require human approval before submitting job applications in early versions.
- Keep browser automation safe, auditable, and domain-controlled.

## Architecture boundaries

- Cursor tooling (`.cursor`, MCP servers, hooks, skills) is for development assistance.
- Runtime application components are separate: FastAPI API, database layer, browser automation client, agent orchestration, and storage.
- Playwright MCP is currently the primary browser-development tool. Browser Use is optional and not required for core progress.

## Repository rules

- Do not start application logic before the environment audit is complete.
- Do not add dependencies without clear justification.
- Keep code explainable and testable.
- Protect auditability and verification for every external step.
- Follow repo safety and architecture guardrails in `.cursor/rules/project.mdc`.

## Current priorities

1. Finish validation of the coding environment.
2. Validate MCP and browser tooling status.
3. Populate repo-specific skills and rules.
4. Only after Phase 0 sign-off, begin Phase 1 foundation work.
