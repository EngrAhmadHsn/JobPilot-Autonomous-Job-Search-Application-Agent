# WS-10 · LLM Client Hardening

Status: **Not started** · Milestone: **M1 (embedding-relevant parts) → M3 (rest)** · Depends on: nothing (standalone) · Blocks: [03](03-matching-engine.md) (wants error taxonomy + rate limit), [05](05-tailoring-and-research.md)

## Goal

Make `src/llm/client.py` production-shaped: fix the dead temperature config, add
timeouts/retries/rate limiting, capture token usage, and open a second provider path —
without touching its privacy stance (`store=False`, key never logged; both preserved).

## Current state

- `src/llm/client.py` — Gemini-only via `google-genai` Interactions API; `generate_text` + `generate_structured`; `store=False`; key guarded. Known gaps:
  - `settings.llm_temperature` is **dead config** — stored on the client, never passed to any call (`client.py:57-76`);
  - no timeout, no retry — a transient 429/5xx fails the whole workflow;
  - token usage ignored;
  - `.env.example` documents zai/openai/anthropic providers; only `google` is implemented (`client.py:41-42` rejects the rest);
  - a single generic `LLMError` — callers can't distinguish "retryable" from "misconfigured".

## Concrete tasks

### 1. Error taxonomy (module bottom)

```python
class LLMError(RuntimeError): ...            # base (exists)
class LLMConfigError(LLMError): ...          # unconfigured/unsupported provider — do not retry
class LLMRateLimited(LLMError): ...          # 429 / quota — retry with backoff
class LLMUnavailable(LLMError): ...          # 5xx / transport — retry with backoff
class LLMInvalidOutput(LLMError): ...        # JSON/schema violation — one repair attempt, then raise
```

`_create()` maps provider exceptions onto these (HTTP status sniff where the SDK exposes it; fallback: string-match on `quota|rate|429` vs `5xx|unavailable`).

### 2. Temperature + parameters actually applied

`_create()` gains `config=types.GenerationConfig(...)`-equivalent interaction parameters: `temperature=self.temperature` on both `generate_text` and `generate_structured`. Locked by a test asserting the request payload contains it.

### 3. Timeouts + retry with backoff (hand-rolled, no tenacity)

- Per-call timeout 60 s (`settings.llm_timeout`, new).
- Up to 3 attempts total for `LLMRateLimited` / `LLMUnavailable` only: exponential backoff `1s, 4s` + jitter; `LLMConfigError`/`LLMInvalidOutput` never retried (invalid-output gets one deterministic repair attempt: re-validate/strip code fences before failing).
- A tiny token-bucket rate limiter (`settings.llm_max_rpm`, default 10) guards the free tier; `acquire()` sleeps rather than errors (embedding + generation share it).

### 4. Usage capture

- `interaction.usage.total_tokens` (and prompt/output split when present) returned from calls as part of a `GenerationUsage` result or logged via `record_audit(action="llm.usage", metadata={"model":..., "total_tokens":..., "duration_ms":...})` — **counts only, never prompt content** (privacy rule).
- Structured calls return the model alongside: `generate_structured` keeps its signature (schema instance) but records usage internally; a `last_usage` property is available for tests/metrics.

### 5. Second provider: `openai-compatible` (second priority, feature-flagged)

- `LLM_PROVIDER=openai-compatible` + `LLM_BASE_URL` (already in `.env.example` for Z.ai/OpenAI): implement minimal chat-completions call with JSON mode for `generate_structured` (`response_format={"type": "json_object"}` + schema-in-prompt), same taxonomy/retries/usage mapping.
- Gemini remains the default and the only fully-supported path in v1; the abstraction is a `Provider` protocol so this stays a thin adapter, not a framework.

### 6. Settings additions

`llm_timeout`, `llm_max_rpm`, `llm_max_retries` (WS-01 owns the settings pattern; values here).

## Acceptance criteria

- [ ] Temperature reaches the provider on every call (asserted on captured payload).
- [ ] A 429 then a 5xx then success → one logical call, three attempts, jittered backoff — no test sleeps (fake clock/injected sleep).
- [ ] `LLMConfigError` (no key / unknown provider) fails immediately with an actionable message; key never appears in any exception string (existing behavior, regression-tested).
- [ ] Usage rows appear in the audit log with token counts and zero prompt content.
- [ ] Sustained 30 rapid calls at `llm_max_rpm=10` complete without provider 429s (limiter pacing test).
- [ ] `openai-compatible` provider passes the same fake-transport test battery (flagged experimental in README).

## Tests

- `tests/test_llm_client.py` (extend heavily) — retry matrix, error mapping, temperature assertion, usage capture, rate-limiter pacing, invalid-JSON repair path, structured-output schema failure → `LLMInvalidOutput`.
- Fake transport objects for both providers (no network in tests, consistent with the suite).

## New dependencies

None.
