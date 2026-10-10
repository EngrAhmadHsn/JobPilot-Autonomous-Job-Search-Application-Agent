# WS-03 · Matching Engine v2 (real semantic + real scorers)

Status: **Not started** · Milestone: **M1** · Depends on: [01](01-data-foundation.md), [02](02-job-discovery.md), [10](10-llm-client-hardening.md) · Blocks: [04](04-pipeline-and-api.md), [05](05-tailoring-and-research.md), [09](09-evaluation.md)

## Goal

Replace the placeholder hybrid matcher with real scoring: embedding-based semantic similarity
via **Chroma + `gemini-embedding-2`**, and genuine experience / seniority / location /
preference scorers computed from the candidate profile — keeping the existing explanation
contract. Delivers plan §18 (vector search) and §19 (hybrid engine).

## Current state

- `src/matching/engine.py` — `calculate_match(job, candidate_skills, weights)` exists with the right output shape (`JobMatchResult` + explanation), but semantic=50, experience=60, seniority=70, preference=50 are **hardcoded constants** and location is a 100/50 stub (`src/matching/engine.py:44-57`).
- `src/matching/contracts.py` — `JobMatchResult` fields are correct; keep unchanged.
- `src/rag/chroma_store.py` — empty placeholder class; `chromadb` is not installed.
- `src/llm/client.py` — generation only; no embedding support.
- `CandidateProfile` has no work-preference fields to drive location/preference scoring.

## Verified `gemini-embedding-2` API facts (sources: aistudio.google.com/docs/embeddings, ai.google.dev/gemini-api/docs/embeddings, checked 2026-10-11)

- **Returns vector embeddings**: `result = client.models.embed_content(model=..., contents=..., config=...)`; vectors at `result.embeddings[i].values` (list of floats).
- **Dimensionality**: default 3072; configurable via `output_dimensionality` (128–3072; recommended 768 / 1536 / 3072). MRL-trained — `gemini-embedding-2` **auto-renormalizes truncated** vectors (no manual L2 needed).
- **No `task_type` on embedding-2** (that is an embedding-001-only parameter). Use asymmetric **prompt prefixes** instead:
  - documents: `title: {title} | text: {content}`
  - queries: `task: search result | query: {content}`
  - Use the same format consistently for queries and documents.
- **Aggregation gotcha**: multiple parts passed in a single `contents` call yield **one aggregated embedding**. To embed N documents, pass each as its own entry (N `Content` objects / N strings) and expect N results — assert this in tests.
- **Input cap**: 8,192 tokens total per request; over-limit input is silently truncated → truncate proactively (~6,000 chars of description) and log.
- **Distance metric**: cosine similarity recommended by the docs.
- **Model spaces are incompatible** across embedding model versions → migrating models requires full re-embedding; persist model name + dimension in collection metadata.
- Batch API exists (50% price) — future optimization, not v1.

## Concrete tasks

### 1. Dependency: `chromadb` (pinned `>=1.0`)

### 2. Embedding function — `src/llm/embeddings.py`

```python
class EmbeddingFn(Protocol):
    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...
    def embed_query(self, text: str) -> list[float]: ...

class GeminiEmbedding:          # default impl, wraps existing genai client
    MODEL_PREFIX_DOC  = "title: {title} | text: {body}"
    MODEL_PREFIX_QUERY = "task: search result | query: {text}"
```

- Uses `client.models.embed_content` with `config=types.EmbedContentConfig(output_dimensionality=settings.embedding_dimensionality)` (768). **No `task_type`.**
- One `contents` entry per text (aggregation gotcha); assert `len(result.embeddings) == len(texts)`.
- Proactive truncation at 6,000 chars with a warning log.
- **Content-hash cache**: `data/embedding_cache.sqlite` keyed by `sha256(model|dim|prefix|text)` → vector. Keeps free-tier quota sane across re-runs; cache lookups happen before any API call.
- API errors → `LLMError` subclasses from WS-10 (`LLMRateLimited`, `LLMUnavailable`) so callers can degrade to non-semantic scoring.

### 3. Real vector store — rewrite `src/rag/chroma_store.py`

- `chromadb.PersistentClient(path=settings.chroma_dir)`; collection `job_listings` with metadata `{"embedding_model": settings.embedding_model, "dimension": settings.embedding_dimensionality}` and `configuration={"hnsw": {"space": "cosine"}}`.
- `upsert_jobs(listings)`: document per job = title + required/preferred skills + truncated description with the `title: … | text: …` prefix; chroma ids = the `JobListing.id` (stable upsert); metadata: `{company, location, remote_policy, seniority, source}`.
- `query_similar(query_text, n) -> list[tuple[str, float]]`: query with the `task: search result | query:` prefix; map cosine **distance** to similarity `sim = (1 - distance) * 100`, clamp 0–100.
- **Model-drift guard**: on open, if collection metadata model/dimension ≠ settings → raise `VectorStoreMismatch` with re-embed instructions (delete `data/chroma`, re-run upsert).
- Wrap the GeminiEmbedding in a Chroma custom `EmbeddingFunction` so store writes go through the same cache.

### 4. Profile extensions — `src/resume/profile.py` + `src/resume/parser.py`

Add a `WorkPreferences` model to `CandidateProfile`:

```python
class WorkPreferences(BaseModel):
    remote_preference: str | None = None   # "remote" | "hybrid" | "onsite"
    preferred_locations: list[str] = []
    min_salary: str | None = None          # verbatim string, parsed on demand
    work_authorization: str | None = None  # verbatim, e.g. "requires sponsorship"
```

Parser extracts these **only when the resume states them** (summary/objective/known heading patterns); absent fields stay `None`/empty and `validate_candidate_profile` warns when both experience-seniority inference and preferences are missing. No invention, per the project rule.

### 5. Real scorers — rewrite `src/matching/engine.py`

Signature change: `calculate_match(job: JobListing, profile: CandidateProfile, *, semantic_score: float | None, weights: dict | None) -> JobMatchResult`.

- **skill** (existing logic, upgraded): weighted overlap — required hits count 1.0, preferred hits 0.5; normalize by `len(required) + 0.5*len(preferred)`.
- **semantic**: passed in from the Chroma query (engine stays vector-store-agnostic); when `None` (embedding unavailable) fall back to skill-only weighting with `semantic` weight redistributed and a `degraded=True` note in the explanation.
- **experience**: `years_of_experience(profile)` (new util in `src/matching/experience.py`) parses `ExperienceEntry.dates` ranges (regex already exists in parser: `_YEAR_RANGE_RE`, incl. "present") → total span years. Requirement years via `\d+\+? years` regex over `job.experience_requirements` + description first line. Score: `100 - 25 * max(0, required - actual)`, clamped 0–100; no requirement stated → neutral 70.
- **seniority**: rank map `{intern:0, junior:1, mid:2, senior:3, lead/staff:4, principal:5}`; infer candidate rank from most recent experience title keywords; compare with `job.seniority` (and title keywords fallback): `100 - 30 * |gap|`; unknown on either side → 70.
- **location**: `job.remote_policy == "remote"` or job location matches a preferred location → 100; no preferences captured → 70 (neutral); conflicting (onsite-only job in non-preferred city) → 25.
- **preference**: employment_type match (`job.employment_type` vs profile-stated preferences when present) + salary floor sanity when both stated; else neutral 70.
- Weights: defaults stay `{semantic:0.2, skill:0.3, experience:0.2, seniority:0.1, location:0.1, preference:0.1}`; overridable via `MATCH_WEIGHTS` JSON env (validated to sum ≈ 1.0 at settings load).
- Explanation format preserved (readable string with component percentages + matched/missing lists) — plan §19's example is the template.

## Acceptance criteria

- [ ] `calculate_match` computes **all six components from data**; grep for the old hardcoded constants returns nothing.
- [ ] Chroma store upserts fixture listings and returns sensible similarities (related job > unrelated job) using **cached** embeddings; a second run makes zero API calls.
- [ ] `len(embed_documents(5 texts)) == 5` (aggregation gotcha locked by test).
- [ ] Model/dimension mismatch raises `VectorStoreMismatch` with clear remediation.
- [ ] Deterministic test path: with a `FakeEmbeddingFn` (fixed vectors), full pipeline produces identical scores across runs — no LLM/network in tests.
- [ ] Profile preferences are extracted only from resume text that states them (fabrication test: resume without preferences → empty `WorkPreferences`, no warnings about missing data beyond the documented ones).

## Tests

- `tests/test_embeddings.py` — prefix formatting, truncation, one-vector-per-input (mock transport), cache hit/miss accounting, error mapping to `LLMRateLimited`.
- `tests/test_chroma_store.py` — tmp-dir PersistentClient, upsert/query with FakeEmbeddingFn, distance→similarity mapping, drift guard.
- `tests/test_matching.py` (extend heavily) — each scorer's boundary cases (meets/exceeds/falls-short requirement years; seniority gaps; remote vs onsite conflicts), weight override validation, degraded mode explanation, full `JobMatchResult` invariants.
- `tests/test_profile_preferences.py` — parser preference extraction happy/absent paths.

## New dependencies

- `chromadb` (plan-sanctioned vector store; user-selected in Phase 7).
