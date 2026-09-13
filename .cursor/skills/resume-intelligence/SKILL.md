---
name: resume-intelligence
description: Builds resume parse-to-profile pipelines with validation, deterministic extraction, and no fabricated facts.
---

# Resume Intelligence

This project must extract structured candidate data from resumes without inventing facts. The pipeline should be parse → validate → normalize → store → optionally embed.

## Pipeline

```text
Resume file → parser → CandidateProfile → validation → storage → optional embedding/retrieval
```

## Candidate data to extract

- personal information
- education
- work experience
- projects
- skills
- certifications
- achievements
- languages
- locations and relocation preferences
- work authorization
- salary expectations
- role interests

## Rules

1. Never invent candidate information.
2. Missing values stay missing; do not guess.
3. Treat parser output as untrusted until it is checked against the source document.
4. Use Pydantic models for the profile schema.
5. Do not copy skills from a job description into the candidate profile.
6. Keep raw file bytes and secrets out of prompts.
7. Use only the text needed for extraction.
8. Support PDF and DOCX as appropriate.
9. Add tests with sample resumes and expected structured fields.

## Implementation posture

- Schema and validation first.
- Parser second.
- Storage third.
- Retrieval and embeddings only when the base pipeline is reliable.
- If a field cannot be confidently extracted, it should be marked unknown rather than guessed.
