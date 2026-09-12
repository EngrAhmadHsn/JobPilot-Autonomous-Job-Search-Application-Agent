---
name: job-matching
description: Implements hybrid job matching with configurable weights and score explanations. Use when scoring jobs, ranking listings, building match engines, or adding embeddings alongside skill and constraint checks.
---

# Job Matching

Development-time Cursor guidance. Not a runtime agent.

## Do not rely on embeddings alone

```text
Final Score =
    semantic similarity
    + skill overlap
    + experience compatibility
    + seniority compatibility
    + location compatibility
    + work-mode compatibility
    + salary compatibility
    + candidate preferences
    + domain relevance
```

Weights must be configurable and evaluated empirically.

## Every score must explain why

Return component scores plus missing vs strong matches, for example:

```text
Job Match: 87/100
Skills: 92% | Experience: 88% | Seniority: 95% | Semantic: 84%
Missing: Kubernetes, AWS
Strong: Python, REST APIs, PostgreSQL
```

## Implementation order

1. Deterministic scoring from structured `CandidateProfile` + `JobListing`.
2. Then LLM reasoning only where it improves explanation or ambiguous cases.
3. Never claim a skill match just because the job description lists it.
4. Keep matching logic in code; prompts must not invent profile facts.
