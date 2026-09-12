---
name: agent-architecture
description: Designs LangGraph workflows, agent boundaries, structured outputs, retries, and human approval. Use when adding agents, graphs, tools, orchestration, or deciding whether an LLM or deterministic Python is appropriate.
---

# Agent Architecture

Development-time Cursor guidance for this repo. Not a runtime agent.

## Default choice

Prefer deterministic Python over LLM reasoning. Do not wrap a single LLM call in an agent. Do not create an agent merely because an LLM is involved.

Use an agent or LangGraph when the work needs state, branching, persistence, retries, human approval, long-running execution, recovery, or multi-step orchestration.

Do not use an agent for simple CRUD, schema validation, database inserts, deterministic calculations, or basic transforms.

## When implementing

1. Put business logic in Python modules, not prompts.
2. Represent workflow state with Pydantic models.
3. Use LangGraph for stateful graphs, not ad-hoc prompt chains.
4. Give tools narrow contracts and structured outputs.
5. Set retries, timeouts, and explicit failure states.
6. Stop for human approval before irreversible actions (especially application submission).
7. Persist graph state so runs can resume.
8. Log every external action for observability and evaluation.

## Boundaries

- Cursor skills/rules/hooks/MCPs help **build** the product.
- The product runtime (FastAPI, LangGraph, Playwright client, DB) is separate.
- Cursor Playwright MCP is not the runtime browser layer.
