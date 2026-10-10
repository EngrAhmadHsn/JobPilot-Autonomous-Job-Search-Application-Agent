# WS-05 · Tailoring Completion + Research

Status: **Not started** · Milestone: **M2** · Depends on: [03](03-matching-engine.md), [04](04-pipeline-and-api.md) · Blocks: [09](09-evaluation.md), M5 pilot

## Goal

Complete plan Phase 7–8: the tailoring pipeline gains its missing **ATS analysis** stage and a
real **deliverable** (rendered DOCX), and the research engine becomes real — grounded strictly
in the listing text. Output is persisted and exposed over the API.

Pipeline target (plan §25): *Job → requirement extraction → relevant evidence → tailored
resume → factuality validation → ATS analysis → final resume.*

## Current state

- `src/resume/tailor.py` — works end-to-end (live-verified with Gemini): LLM tailoring with structured output + deterministic factuality validator (unknown skills/companies/projects stripped, inflated years removed). Keep the `generate` injection point and the factuality design **unchanged**.
- `src/jobs/requirements.py` — deterministic `extract_requirements` already feeds the prompt; unchanged.
- `src/research/engine.py` — `research_company()` / `research_job_description()` return `{"research": "placeholder"}`.
- **No ATS analysis exists** (plan §26) — no keyword coverage, no format-risk checks.
- **No rendering**: the tailored result is data only; there is no DOCX a user could actually send.
- Nothing is persisted (`TailoredResumeDB` doesn't exist); no tailor endpoint.

## Concrete tasks

### 1. ATS analyzer — `src/resume/ats.py` (new, fully deterministic)

```python
class AtsReport(BaseModel):
    keyword_coverage: KeywordCoverage     # required: hit/missing, preferred: hit/missing
    section_completeness: dict[str, bool] # contact, summary, skills, experience, education
    format_risks: list[str]               # from DOCX introspection
    title_alignment: float                # 0-100
    score: float                          # weighted 0-100
    notes: list[str]
```

- **Keyword coverage**: use `extract_requirements(job)` — required terms must appear in tailored skills/experience text (normalized containment, same `_norm` conventions as the tailoring validator); preferred terms weighted 0.5. Missing required keywords go into `notes` as *suggestions only* — the analyzer never inserts words the profile doesn't support (no keyword stuffing, plan §26).
- **Format risks** (via `python-docx` introspection of the rendered file): tables used for layout, text boxes, images containing text (count only), missing standard headings, unusual fonts/sizes (>2 body sizes), empty sections.
- **Title alignment**: exact/alias match between tailored headline/title and `job.title` tokens.
- Weighted score; the weights and neutral values are constants in one place, documented.

### 2. DOCX renderer — `src/resume/render.py` (new)

- `render_tailored_docx(tailored: TailoredResume, profile: CandidateProfile, out_path: Path) -> Path`
- python-docx build: name + contact line from `profile.personal_information` (verbatim fields only), headline, summary, `highlighted_skills` grouped by `skill_categories`, experience (company/title/bullets), projects, certifications/achievements if non-empty.
- Output to `settings.data_dir / "tailored" / f"{profile_id}_{job_id}.docx"`.
- **Roundtrip guarantee**: the rendered file must re-parse through the existing `parse_resume()` and preserve names/companies/bullets — locked by test. This is the strongest possible anti-fabrication check on the renderer.

### 3. Research engine — rewrite `src/research/engine.py`

- `research_job(job: JobListing, *, generate=None) -> JobInsights` — LLM structured output (existing `get_client().generate_structured`):

```python
class JobInsights(BaseModel):
    responsibilities: list[str]   # extracted, near-verbatim from the description
    tech_stack: list[str]         # only technologies named in the listing
    seniority_signals: list[str]
    culture_flags: list[str]      # explicit statements only
    summary: str
```

- System prompt: "extract only what the listing states; never add external knowledge about the company or market" — research is **grounded retrieval of listing facts**, not generation (plan §7: ground claims in retrieved evidence).
- `research_company(company_name)` v1: derive from the listing + matched-jobs context only; real web research is explicitly deferred (out of scope note in [00](00-OVERVIEW.md) — SSRF-controlled fetching comes with a future workstream).
- Insights feed the tailoring prompt (`_build_prompt` gains an `insights` section) so the LLM tailors against structured job facts instead of raw description text.

### 4. Persistence + API

- `TailoredResumeDB` (Alembic revision per WS-01 policy): `id`, `profile_id` FK, `job_id`, `tailored` JSON, `factuality` JSON, `ats_report` JSON, `docx_path`, `created_at`.
- `POST /api/tailor` `{profile_id, job_id}` → loads both, runs `tailor_resume` → `analyze_ats` (on rendered file) → `render_tailored_docx` → persist → returns `{tailoring_id, factuality, ats_report, docx_path}`. `factuality.passed == False` is a **200 with the report**, not an error — the stripped-safe content plus violations is the product (per the module contract).
- `GET /api/tailored/{id}` → stored report + file path.

## Acceptance criteria

- [ ] `POST /api/tailor` returns a rendered DOCX that opens, re-parses through `parse_resume()`, and whose `AtsReport.score` reflects real coverage of the job's requirements.
- [ ] Analyzer is deterministic: same inputs → identical `AtsReport` (no LLM anywhere in `ats.py`).
- [ ] Missing-keyword notes never propose skills absent from the profile (fabrication test).
- [ ] `JobInsights` from a poisoned listing (injection text) contains only listing-derived content (covered jointly with WS-06's policy test).
- [ ] Tailoring results, ATS reports, and file paths survive restart.

## Tests

- `tests/test_ats.py` — coverage math (all/none/partial), weighted score, title alignment aliases, format-risk detection on deliberately bad DOCX fixtures, determinism.
- `tests/test_render.py` — render → `parse_resume()` roundtrip on two tailored fixtures; empty-sections edge case; file naming/collision.
- `tests/test_research.py` — fake LLM returns structured insights; grounding prompt asserted in captured prompt; poisoned-description case.
- `tests/test_tailor.py` (extend) — end-to-end with fake `generate`: insights present in prompt, report persisted, API 200-with-violations behavior.

## New dependencies

None (python-docx already present; LLM via existing client).
