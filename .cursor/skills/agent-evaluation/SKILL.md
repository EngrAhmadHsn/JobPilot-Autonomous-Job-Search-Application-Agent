---
name: agent-evaluation
description: Defines measurable evaluation metrics for extraction, matching, tailoring, and browser application flows. Use when adding tests, benchmarks, eval harnesses, or claims that the system is autonomous or accurate.
---

# Agent Evaluation

Development-time Cursor guidance. Not a runtime agent.

Do not call the system autonomous without measured results.

## What to measure

Resume extraction: field extraction accuracy.

Job retrieval: precision@k, recall@k, duplicate rate.

Job matching: ranking quality, false positive rate, false negative rate.

Resume tailoring: factual consistency, keyword coverage, job relevance, hallucination rate.

Browser automation: form completion success, navigation failure rate, verification success rate.

Application system: successful vs failed applications, human intervention rate, incorrect submissions.

## How to implement

1. Prefer tests against fixtures and fake/local ATS sites, not live employer sites first.
2. Store eval datasets and expected outputs under `tests/` / `docs/evaluations/` when those exist.
3. Every LangGraph path that mutates the world needs a verifiable outcome check.
4. Report component scores, not a single opaque "quality" number.
