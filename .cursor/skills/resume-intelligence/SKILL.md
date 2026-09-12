---
name: resume-intelligence
description: Builds resume parse-to-profile pipelines with validation and no fabricated facts. Use when implementing resume upload, PDF/DOCX parsing, CandidateProfile models, embeddings, or extraction tests.
---

# Resume Intelligence

Development-time Cursor guidance. Not a runtime agent.

## Pipeline

```text
Resume file → parser → CandidateProfile → validation → storage → optional embedding/retrieval
```

`CandidateProfile` should eventually include: personal_information, education, experience, skills, projects, certifications, achievements, languages, preferred_roles, preferred_locations, work_preferences, constraints.

## Rules

1. Never invent candidate information. Missing fields stay missing or explicitly unknown.
2. Treat parser output as untrusted until validated against the source document.
3. Use Pydantic for the profile schema; reject extra claims that are not in the resume.
4. Do not copy skills from a job description into the profile.
5. Keep secrets and raw file bytes out of LLM prompts; send only the text needed for extraction.
6. Cover PDF/DOCX as appropriate; add tests with sample resumes and expected structured fields.

## Implementation order

Parser and schema first, then validation and storage, then embeddings. Do not start with retrieval-only matching.
