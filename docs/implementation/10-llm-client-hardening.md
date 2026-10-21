# WS-10 · LLM Client Hardening

Status: **Done (2026-10-21)** · Milestone: **M1 (embedding-relevant parts) → M3 (rest)** · Depends on: nothing (standalone) · Blocks: [03](03-matching-engine.md) (wants error taxonomy + rate limit), [05](05-tailoring-and-research.md)

> **Part 1 is the original brief. Parts 2–3 are the specification and the
> execution plan written on 2026-10-21, after an audit of the code as it
> actually stands.** Three findings from that audit change the brief (see
> **S1**): the error taxonomy the brief asks for *already exists*, the brief's
> Gemini parameter name is wrong for the installed SDK, and the brief's
> "embedding + generation share one limiter" would halve both provider
> quotas. Part 4 records what was built, measured and verified.

## Execution plan (added 2026-10-21 — implementation of WS-10)

Phases, in dependency order (each phase: implement → its own tests → the full
offline suite → `ruff`):

1. **Phase A — Settings (`src/config/settings.py`, `.env.example`).** Three new
   settings — `llm_timeout` (60 s), `llm_max_rpm` (10), `llm_max_retries` (2) —
   read from the environment and validated at startup the way every other
   setting in that module is (a typo in a knob that decides how long a call
   may hang must fail loudly, not silently). `.env.example` documents them and
   its stale provider list is corrected.
2. **Phase B — Resilience primitives (`src/llm/resilience.py`, new).** A
   sliding-window rate limiter (injectable clock and sleep, so the pacing test
   costs no wall-clock time) and the exponential-backoff helper. Hand-rolled —
   no `tenacity`, per the no-unjustified-dependencies rule.
3. **Phase C — Provider abstraction (`src/llm/providers.py`, new).** A `Provider`
   protocol, the Gemini adapter (Interactions API, `store=False` preserved) and
   the `openai-compatible` adapter (chat-completions over `httpx`, JSON mode).
   Both map their failures onto the shared taxonomy.
4. **Phase D — Usage capture (`src/llm/usage.py`, new).** A `GenerationUsage`
   model and the audit writer that records **counts only** — never a prompt,
   never a key.
5. **Phase E — The client facade (`src/llm/client.py`, rewritten).** The
   public surface (`LLMClient`, `get_client()`, `strict_json_schema()`) is
   preserved; behind it the temperature finally reaches the provider, a
   timeout bounds every call, retryable failures are retried with jittered
   backoff, an invalid structured output is repaired locally once, and the
   usage of the last call is readable through `last_usage`.
6. **Phase F — Tests.** Four modules: the client facade, the providers, the
   resilience primitives, the usage record. No network in any of them.
7. **Phase G — Verification and reconciliation.** A live-verification script
   (`scripts/verify_ws10.py`) that makes a **real** Gemini call, proves the
   temperature is on the wire (a local capture server in front of the real
   SDK), and checks the audit row; then the doc status, `00-OVERVIEW.md` and
   `.env.example` are reconciled, and the work is committed as discrete
   per-file commits.

**Why this workstream now:** the LLM client is the one runtime component with
no timeout, no retry and no usage accounting — a single transient 429 in the
tailoring or research node fails a whole application run, and the token spend
of the free tier is invisible. WS-09's live mode found the evaluation harness
was serving canned data while calling itself "live"; the same class of defect
(a client that claims resilience it does not have) is what this workstream
closes.

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

- [x] Temperature reaches the provider on every call (asserted on captured payload).
- [x] A 429 then a 5xx then success → one logical call, three attempts, jittered backoff — no test sleeps (fake clock/injected sleep).
- [x] `LLMConfigError` (no key / unknown provider) fails immediately with an actionable message; key never appears in any exception string (existing behavior, regression-tested).
- [x] Usage rows appear in the audit log with token counts and zero prompt content.
- [x] Sustained 30 rapid calls at `llm_max_rpm=10` complete without provider 429s (limiter pacing test).
- [x] `openai-compatible` provider passes the same fake-transport test battery (flagged experimental in README).

## Tests

- `tests/test_llm_client.py` (extend heavily) — retry matrix, error mapping, temperature assertion, usage capture, rate-limiter pacing, invalid-JSON repair path, structured-output schema failure → `LLMInvalidOutput`.
- Fake transport objects for both providers (no network in tests, consistent with the suite).

## New dependencies

None.

---

# Part 2 — Detailed specification (added 2026-10-21)

## S0. Scope, invariants, non-goals

### Scope

The LLM "brain" client: its provider adapters, its resilience behaviour, and
its usage accounting. Nothing else in the repository changes behaviour — the
research node, the tailoring node and the API keep working exactly as they do.

### Invariants (binding)

1. **The privacy stance is untouched.** Gemini calls still carry `store=False`
   (the provider must not retain candidate data). The API key is never logged,
   never in an exception message, never in the audit trail, and never in a
   request body — it is an `Authorization` header and nothing else.
2. **No prompt content is ever persisted.** The usage record holds counts,
   the model name, the provider, the duration and the attempt count. The
   prompt and the completion are passed through in memory and nowhere else.
3. **Deterministic Python over model-driven reasoning.** The resilience policy
   (what is retried, how long we wait, what is repaired) is code, not a prompt.
4. **No new dependencies.** `httpx` is already an explicit dependency and
   covers the second provider; the limiter, the backoff and the JSON repair
   are hand-rolled.
5. **The public surface is preserved.** `LLMClient`, `get_client()`,
   `strict_json_schema()`, the exception hierarchy and the two generation
   methods keep their signatures. The two production call sites
   (`src/resume/tailor.py:169`, `src/research/engine.py:212`) are unchanged.
6. **No test sleeps and no test network.** Every timing dependency is
   injectable (clock, sleep, jitter); every provider is injectable.

### Non-goals

- Streaming responses.
- Token counting for the *local* embedding provider (it makes no API calls).
- A prompt cache, a batch API, or a provider router.
- Changing the embedding path's FU-4 daily-budget logic (it stays as it is;
  only its pacing is moved onto the shared limiter, see **D4**).
- Making `AUTO_SUBMIT` reachable. Unrelated.

## S1. What the brief gets wrong (and what replaces it)

An audit of the code on 2026-10-21 (840 tests green) found three places where
the Part 1 brief no longer matches the repository.

### S1.1 The error taxonomy already exists — what is missing is that it is *not used*

`src/llm/client.py` already defines `LLMError`, `LLMConfigError`,
`LLMRateLimited`, `LLMDailyQuotaExhausted`, `LLMUnavailable`,
`LLMInvalidOutput` and a `classify_provider_error()` helper (added with the
FU-4 embedding budget work). The taxonomy is real — but `LLMClient._create()`
catches every provider exception and re-raises it as a **generic** `LLMError`:

```python
except Exception as exc:  # provider SDK raises many types; convert to LLMError
    raise LLMError(f"LLM call failed: {type(exc).__name__}: {exc}") from exc
```

So a caller cannot tell a 429 from a bad key, and a retry policy written
against the taxonomy would never fire. **The fix is not "add the taxonomy" but
"route every provider failure through the classifier the repository already
has"**, plus one addition: `LLMTimeout(LLMUnavailable)` so a timeout is
retryable *and* distinguishable from a 5xx.

### S1.2 The Gemini parameter name in the brief is wrong for the installed SDK

The brief says `config=types.GenerationConfig(...)`. The installed SDK is
`google-genai 2.29.0`, and its **Interactions** API does not take a `config`
argument. `interactions.create()` takes:

```
model, input, store, response_format, generation_config, timeout, ...
```

`generation_config` is a `TypedDict` (`GenerationConfigParam`) with a
`temperature` key, and `timeout` is a per-call argument. So the request the
client must build is:

```python
client.interactions.create(
    model=..., input=..., store=False,
    generation_config={"temperature": 0.2},
    timeout=60.0,
    response_format={"type": "text", "mime_type": "application/json", "schema": ...},
)
```

This is verified against the installed SDK, not assumed — and re-verified on
the wire in Phase G (a local capture server in front of the real SDK shows
the serialized body).

### S1.3 "Embedding + generation share one limiter" would halve both quotas

Gemini meters the embedding model and the generation model **separately**
(FU-4 documents the embedding model's own RPM 5 / RPD 20 free-tier limits).
One shared bucket of `llm_max_rpm` tokens would make a burst of embeddings
consume the generation budget and vice versa — each path would run at half
its own rate.

**Decision D4:** the limiter is the **generation path's alone**. Gemini meters
the embedding model and the generation model **separately** (FU-4 documents
the embedding model's own RPM 5 / RPD 20 free-tier limits), so one shared
budget would make a burst of embeddings consume the generation allowance and
vice versa — each path would run at half its own rate. The embedding path
keeps the FU-4 throttle it was live-verified with. See **D4a** for the
primitive and **D4b** for the registry in **S4**.

## S2. Module layout

| File | New? | Contents |
|---|---|---|
| `src/llm/client.py` | rewritten | The public facade: `LLMClient`, the exception hierarchy, `classify_provider_error`, `strict_json_schema`, `get_client` |
| `src/llm/providers.py` | **new** | `Provider` protocol, `ProviderRequest`, `ProviderResponse`, `GeminiProvider`, `OpenAICompatibleProvider`, `build_provider` |
| `src/llm/resilience.py` | **new** | `TokenBucket`, `backoff_delay`, the process-wide bucket registry |
| `src/llm/usage.py` | **new** | `GenerationUsage`, `record_usage` (the audit writer) |
| `src/config/settings.py` | edited | `llm_timeout`, `llm_max_rpm`, `llm_max_retries` + validation |
| `src/security/audit.py` | edited | One new constant: `ACTION_LLM_USAGE = "llm.usage"` |
| `src/llm/embeddings.py` | edited | The embedding path's pacing moves onto the shared bucket |
| `src/llm/__init__.py` | edited | The new public names |

Why four modules and not one: the client facade is the thing the rest of the
repository imports; the provider adapters, the resilience primitives and the
usage record have their own lifetimes and their own tests, and the repo's
existing style is small, single-purpose modules (`src/jobs/http_client.py`,
`src/security/audit.py`).

## S3. Phase A — Settings

```python
self.llm_timeout    = float(os.getenv("LLM_TIMEOUT", "60"))     # seconds per call
self.llm_max_rpm    = int(os.getenv("LLM_MAX_RPM", "10"))        # calls per minute
self.llm_max_retries = int(os.getenv("LLM_MAX_RETRIES", "2"))     # retries after the first attempt
```

Validation, in the same fail-fast style as `EMBEDDING_PROVIDER` and
`SUBMISSION_POLICY` in that module: a timeout ≤ 0, an RPM below 1 or a
negative retry count raises `RuntimeError` at construction ("Refusing to
start"). A knob that decides how long a call may hang must not accept zero.

`LLM_MAX_RETRIES=2` means **three attempts in total** (the brief's "up to 3
attempts total").

`.env.example`: the three new variables are documented, and the stale
provider comment is corrected — `google` is the default and the only
fully-supported path; `openai-compatible` (aliases `openai`, `zai`) is
experimental.

## S4. Phase B — Resilience primitives

### S4.1 The rate limiter

```python
class SlidingWindowLimiter:
    def __init__(self, max_calls: int, window_seconds: float = 60.0, *,
                 clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep) -> None
    def acquire(self) -> float:   # returns the seconds it waited
```

The limiter keeps the timestamps of the recent calls; a call that would make
the window hold more than `max_calls` entries waits until the oldest one
falls out. The guarantee is therefore exactly **"no more than `max_calls`
calls in any 60-second window"** — the shape a provider's per-minute limit
has. `acquire()` **sleeps** — it never raises and never fails a call, because
a rate limit is a pacing problem, not an error. The clock and the sleep are
constructor arguments so a test can drive the whole thing with a fake clock
and assert on virtual time.

**Decision D4a — a sliding window, not a token bucket.** The brief asks for a
"tiny token-bucket rate limiter". A token bucket of capacity `R` refilling at
`R / 60` tokens per second admits up to **`R + R/60` calls in a 60-second
window** — 19 calls at `R = 10`. That is enough to trip the very limit the
limiter exists to respect, so the brief's primitive does not deliver the
brief's guarantee ("no provider 429s"). The sliding window admits exactly
`R`. The implementation is the same size; only the arithmetic differs.

The limiter holds no lock, and the LLM client is single-threaded per call.
(The job-source HTTP client has its own async limiter,
`src/jobs/http_client.py:HostRateLimiter`, for the async adapters; the two
never share a budget because they meter different hosts.)

### S4.2 The process-wide registry

```python
def get_limiter(name: str, max_calls: int, window_seconds: float = 60.0) -> SlidingWindowLimiter
def reset_limiters() -> None
```

Named limiters, created once per process. `get_limiter("llm", ...)` is what
the client uses. `reset_limiters()` exists for tests.

**Decision D4b — the embedding path keeps its own pacing.** The Gemini
embedding path already has a live-verified FU-4 throttle that spaces its
batch requests. Migrating it onto the new limiter is not worth the risk to a
path that was verified against the live API, and the two meter *different*
provider quotas anyway (Gemini bills the embedding model and the generation
model separately). The limiter is therefore the generation path's, and the
WS-10 limiter is available to the embedding path later if that is ever
wanted. The embedding path is **not** migrated in this workstream.

### S4.3 The backoff

```python
def backoff_delay(attempt: int, base: float,
                   jitter: Callable[[float, float], float] = random.uniform) -> float
```

`base * 4 ** (attempt - 1) + jitter(0, base / 2)`.

With `base = 1.0` the delays are **1.0–1.5 s** and **4.0–4.5 s** for the
two retries of a three-attempt call — the brief's "1 s, 4 s + jitter". The
jitter source is injected, so a test can pin the delays to exactly 1.0 and
4.0 and assert the *shape* of the schedule without sleeping.

## S5. Phase C — The provider abstraction

### S5.1 The protocol

```python
@dataclass(frozen=True)
class ProviderRequest:
    prompt: str
    model: str
    temperature: float
    timeout: float
    response_schema: dict | None = None      # strict JSON schema, None for plain text
    max_output_tokens: int | None = None

@dataclass(frozen=True)
class ProviderResponse:
    text: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None

class Provider(Protocol):
    name: str
    def complete(self, request: ProviderRequest) -> ProviderResponse: ...
```

The client owns the policy (pace, retry, record); the provider owns the
wire. A provider never retries and never sleeps.

### S5.2 `GeminiProvider`

Builds exactly the request in **S1.2**, calls
`client.interactions.create(**kwargs)`, and reads the usage off the response
(`interaction.usage.total_tokens` / `.total_input_tokens` /
`.total_output_tokens`). The SDK's `Usage` object exposes those three
attributes; the reader tolerates a mapping too, because the response may be
replayed from a recorded fixture.

`store=False` is hard-coded in the provider — it is a privacy control, not a
tunable, so it is not a constructor argument.

The real `google.genai` client is created lazily (so constructing the
provider without a key is safe) and can be **injected** for tests.

### S5.3 `OpenAICompatibleProvider`

A chat-completions call:

```
POST {LLM_BASE_URL}/chat/completions
Authorization: Bearer {LLM_API_KEY}
{"model": ..., "messages": [{"role": "user", "content": ...}],
 "temperature": 0.2, "response_format": {"type": "json_object"}}
```

For a structured call the schema goes into the prompt (there is no schema
field in the chat-completions API) and JSON mode is requested. The prompt
always contains the word "JSON", which is what the OpenAI-compatible JSON
mode requires to be present.

HTTP status → taxonomy:

| Status | Exception | Retried? |
|---|---|---|
| 429 | `LLMRateLimited` | yes |
| 5xx | `LLMUnavailable` | yes |
| 401 / 403 | `LLMConfigError` | no — the key is wrong or rejected |
| other 4xx | `LLMError` | no — the request itself is wrong |

The `httpx` client is injectable, so the tests drive it through
`httpx.MockTransport` — the same fake-transport pattern the job-source
adapters use (`tests/test_jobs.py`).

### S5.4 The provider factory

```python
def build_provider(provider: str, *, api_key: str, model: str,
                   base_url: str | None, timeout: float) -> Provider
```

| `LLM_PROVIDER` | Adapter | Base URL |
|---|---|---|
| `google` | `GeminiProvider` | the SDK's own |
| `openai-compatible` | `OpenAICompatibleProvider` | `LLM_BASE_URL` (required) |
| `openai` | `OpenAICompatibleProvider` | `https://api.openai.com/v1` (default) |
| `zai` | `OpenAICompatibleProvider` | `https://api.z.ai/api/paas/v4` (default) |
| anything else | — | `LLMConfigError` |

**Decision D6:** `openai` and `zai` are accepted as aliases of
`openai-compatible` because both are already documented in `.env.example`
with an `LLM_BASE_URL`, and both speak the chat-completions dialect. The
brief's "only `google` is implemented" becomes "only `google` is *fully
supported*". `anthropic` stays **unsupported** — its native API is not
chat-completions shaped, and half-implementing it would be worse than
refusing it clearly. The existing test that used `openai` as its example of
an unsupported provider is updated to `anthropic`; the supported set
genuinely widened, so the test's example was stale.

## S6. Phase D — Usage capture

```python
class GenerationUsage(BaseModel):
    provider: str
    model: str
    kind: str                 # "text" | "structured"
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    duration_ms: int
    attempts: int = 1
```

`record_usage(usage, outcome="success")` writes one audit row through
`record_audit(action="llm.usage", actor="system", resource="llm:<provider>:<model>", …)`.

**Decision D5 — the metadata key names.** The counts are recorded as
`usage_input`, `usage_output` and `usage_total`, **not** `input_tokens` /
`output_tokens` / `total_tokens`. The WS-06 redaction filter
(`src/security/redaction.py:26`) drops any metadata key whose name *contains*
the substring `token` — a blunt rule, but a deliberate one (a masked secret is
still a hint about its shape, so the whole pair is removed). A count is not a
credential, but the redaction rule is a security control and this workstream
does not loosen it for convenience. The names are neutral enough to read
(`{"usage_total": 812}`) and a test asserts that the counts really do reach
the audit row — which is the regression that matters.

`record_usage` never raises: `record_audit` already swallows a failing store,
and a failing audit store must not break an LLM call.

## S7. Phase E — The client facade

### S7.1 The constructor

```python
class LLMClient:
    def __init__(self, provider: str, api_key: str, model: str, temperature: float, *,
                 base_url: str | None = None,
                 timeout: float | None = None,
                 max_retries: int | None = None,
                 max_rpm: int | None = None,
                 provider_instance: Provider | None = None,
                 limiter: TokenBucket | None = None,
                 sleep: Callable[[float], None] = time.sleep,
                 clock: Callable[[], float] = time.monotonic,
                 jitter: Callable[[float, float], float] = random.uniform) -> None
```

The four positional parameters keep their meaning and order, so the existing
call sites and tests keep working. Everything new is keyword-only and
optional. `provider_instance` and `limiter` are the injection seams; `sleep`,
`clock` and `jitter` are the timing seams.

Defaults come from `get_settings()` when the argument is omitted.

### S7.2 The retry policy

| Failure | Retried? | Why |
|---|---|---|
| `LLMRateLimited` | **yes** | the free tier throttles; the wait is short |
| `LLMDailyQuotaExhausted` | **no** | it subclasses `LLMRateLimited`, but a *daily* budget does not reset in 1 s — retrying would hammer the provider until the backoff gave up |
| `LLMUnavailable` / `LLMTimeout` | **yes** | a 5xx or a transport blip is worth another attempt |
| `LLMConfigError` | no | a missing key or an unknown provider will not fix itself |
| `LLMInvalidOutput` | no | repaired locally, once (S7.4) |
| plain `LLMError` | no | unclassified — do not guess |

The retry loop wraps **the provider call only**. The limiter is consulted
before every attempt, so a retried call is paced like any other.

### S7.3 The two generation methods

```python
def generate_text(self, prompt: str) -> str
def generate_structured(self, prompt: str, schema: type[T]) -> T
```

Both signatures are unchanged. Both now: consult the limiter, call the
provider with the temperature and the timeout, retry per **S7.2**, and record
the usage. `generate_structured` additionally sends the strict JSON schema
(`strict_json_schema()`) and parses the answer.

### S7.4 The local repair of an invalid structured output

The brief calls the repair "deterministic", and it is: **no second model
call** is made. The repair is a text-level fix-up, tried exactly once:

1. strip a ```` ```json ```` / ```` ``` ```` fence if the answer is wrapped in one;
2. if that does not parse, extract the outermost balanced `{…}` object
   (brace counting that ignores braces inside strings);
3. validate against the schema.

If the repaired text still does not validate, `LLMInvalidOutput` is raised —
with the validation error, never the model's raw answer (the raw answer is
the model's rendering of candidate data and must not leak into a log line or
an exception message).

### S7.5 `last_usage`

```python
@property
def last_usage(self) -> GenerationUsage | None
```

The usage of the most recent call, successful or failed. `None` before the
first call. It is what the tests assert on, and it is what a metrics exporter
would read.

## S8. Phase F — The test matrix

| # | Test | Asserts |
|---|---|---|
| T1 | temperature reaches the provider | the captured Gemini request carries `generation_config={"temperature": 0.2}` — on **both** `generate_text` and `generate_structured` |
| T2 | temperature reaches the openai-compatible provider | the captured chat-completions body carries `"temperature": 0.2` |
| T3 | the timeout reaches the provider | the captured request carries the configured timeout |
| T4 | 429 → 5xx → success | **one** logical call, **three** attempts, delays 1.0 s and 4.0 s, no wall-clock sleep |
| T5 | a config error is not retried | one attempt, `LLMConfigError` |
| T6 | a daily-quota error is not retried | one attempt, `LLMDailyQuotaExhausted` (the subclass must not be swallowed by the `LLMRateLimited` rule) |
| T7 | an invalid output is not retried | one provider call, the local repair runs, `LLMInvalidOutput` |
| T8 | the local repair | a fenced answer and a "prose + JSON" answer both validate after the repair |
| T9 | the key never leaks | no exception message, log line or audit row contains the key |
| T10 | the usage row | the audit row carries the counts and **no** prompt substring |
| T11 | the limiter paces 30 calls | 30 calls at `llm_max_rpm=10` complete with no provider 429, the virtual elapsed time matches the 10-per-minute budget, and no 60-second window ever holds more than 10 calls |
| T12 | the limiter does not fail a call | a window with room lets a call through immediately (no sleep) |
| T13 | both providers, one battery | the same assertions run against the Gemini fake and the `httpx.MockTransport` fake |
| T14 | the `openai-compatible` error mapping | 429/500/401/400 → the four expected exceptions |
| T15 | the settings | the three new settings are read, defaulted and validated |

Files: `tests/test_llm_client.py` (extended), `tests/test_llm_providers.py`
(new), `tests/test_llm_resilience.py` (new), `tests/test_llm_usage.py` (new).

## S9. Phase G — Verification

`scripts/verify_ws10.py` — the live verification, in the style of
`scripts/verify_ws08.py` / `verify_ws09.py`:

1. **The wire carries the temperature.** A local HTTP capture server is put in
   front of the **real** `google-genai` SDK (via `http_options.base_url`), the
   client makes a call, and the recorded request body is checked for
   `"temperature": 0.2`. This is the one check a fake cannot make: it proves
   the SDK accepts the parameter and serializes it.
2. **A real call succeeds** against the configured Gemini model, and
   `last_usage` reports a non-zero token count.
3. **The audit row exists** with the counts and without the prompt.
4. **A structured call** returns a validated Pydantic object.
5. **A config error** fails immediately, with an actionable message and
   without the key in the text.
6. **A retry, live.** A locally-served 429 followed by a 200 proves the
   retry path against a real HTTP stack (no wall-clock wait: the backoff is
   injected to zero for this check).

## S10. Risks

| Risk | Mitigation |
|---|---|
| The Gemini Interactions API rejects `generation_config` | Phase G check 1 verifies it against the installed SDK and the real wire; a fallback to `types.GenerationConfig` is a one-line change if the shape differs |
| A retry storm against a rate-limited provider | the limiter paces *before* every attempt, and the daily-quota error is never retried |
| The usage row leaks candidate data | the row holds counts only; the redaction filter masks the rest; a test greps the row for the prompt |
| The second provider silently becomes a second source of truth | it is documented as experimental, it is behind the same taxonomy, and it is not the default |
| The redaction filter swallows the token counts | the metadata keys are named `usage_*` (D5), and a test asserts the counts reach the row |
| Doubling the client's surface area | the public surface is unchanged; everything new is behind the facade and covered by the same battery (T13) |

---

# Part 3 — Execution plan (added 2026-10-21 — implementation of WS-10)

Each phase ends with its own test run; the full suite runs after every phase
that touches shared code, and `ruff check` runs at the end of each phase.

| Phase | Deliverable | Verification | Gate |
|---|---|---|---|
| **A** | `src/config/settings.py`, `.env.example` | `tests/test_llm_settings.py` — the three settings are read, defaulted and validated (a zero timeout, an RPM of 0 and a negative retry count each raise) | new tests green |
| **B** | `src/llm/resilience.py` | `tests/test_llm_resilience.py` — the limiter's virtual-time pacing, the per-window guarantee, the backoff schedule, the registry | new tests green |
| **C** | `src/llm/providers.py` | `tests/test_llm_providers.py` — the Gemini request payload, the openai-compatible request payload, the usage mapping, the status→exception mapping, the key never in an exception | new tests green |
| **D** | `src/llm/usage.py`, `src/security/audit.py` | `tests/test_llm_usage.py` — the row's content, the absence of prompt content, the failure of the store never breaking the call | new tests green |
| **E** | `src/llm/client.py`, `src/llm/embeddings.py`, `src/llm/__init__.py` | `tests/test_llm_client.py` — T1, T3–T10, T12, T15 | new + existing tests green, **full suite green** |
| **F** | the four test modules, complete | the whole suite green; `ruff check` clean | **840 + N passing** |
| **G** | `scripts/verify_ws10.py`, this doc, `00-OVERVIEW.md` | the live script exits 0 and prints its checks | live run green |

**Sequencing note.** Phase E is the only phase that can break a caller, so it
lands after its dependencies (A–D) are proven, and the full suite is run
immediately after it.

**Commit policy** (per the workspace workflow): discrete per-file commits, no
push. The push stays a separate, explicit step.

---

# Part 4 — Implementation notes (added 2026-10-21 — WS-10 executed)

Suite: **934 passing** (was 840), ruff clean on every file WS-10 owns.
Live verification: `scripts/verify_ws10.py` — **14/14 checks passed**, 1 honest
skip (the free tier's daily quota was spent; see below).

## What was built

| File | Change |
|---|---|
| `src/llm/errors.py` | **new** — the taxonomy (`LLMError`, `LLMConfigError`, `LLMRateLimited`, `LLMDailyQuotaExhausted`, `LLMUnavailable`, `LLMTimeout`, `LLMInvalidOutput`), `classify_provider_error()` and `scrub_secret()`. Moved out of `client.py` so the provider adapters can use it without a cycle; the facade re-exports every name, so `from src.llm.client import LLMRateLimited` still works for the rest of the repository |
| `src/llm/providers.py` | **new** — the `Provider` protocol, `GeminiProvider` and `OpenAICompatibleProvider`, the factory |
| `src/llm/resilience.py` | **new** — `SlidingWindowLimiter`, `backoff_delay`, the process-wide limiter registry |
| `src/llm/usage.py` | **new** — `GenerationUsage` and the audit writer |
| `src/llm/client.py` | rewritten as a facade: the temperature reaches the provider, a timeout bounds every call, retryable failures are retried, an invalid structured output is repaired once locally, `last_usage` is readable |
| `src/llm/__init__.py` | the new public names |
| `src/config/settings.py` | `llm_timeout`, `llm_max_rpm`, `llm_max_retries`, each validated at startup |
| `src/security/audit.py` | one new constant: `ACTION_LLM_USAGE = "llm.usage"` |
| `.env.example` | the three new settings, and the provider list corrected |
| `tests/conftest.py` | every model is now imported explicitly (see the conftest defect below) |
| `scripts/verify_ws10.py` | **new** — the live verification |

**The public surface did not change.** `LLMClient`, `get_client()`,
`strict_json_schema()`, the exception hierarchy and the two generation
methods keep their signatures; the two production call sites
(`src/resume/tailor.py`, `src/research/engine.py`) are untouched.

## The three defects the live run found

### 1. The SDK's own retry layers ran behind the client's back — and one of them slept for fourteen hours

The first live call did not come back. The google-genai SDK retries **twice**
over, and the two layers disagree about what an attempt is:

- the api client wraps every request in a tenacity loop — five attempts,
  exponential waits up to a minute, on 408/429/5xx;
- the **Interactions** resource has its own layer — up to four retries on
  408/409/429/5xx — and it **honours a `Retry-After` header verbatim**.

A daily-quota 429 from Gemini carries `Retry-After: 50951`. Fourteen hours.
The SDK slept for fourteen hours *inside* a call whose timeout was sixty
seconds, so the timeout did not fire, the client's own backoff never ran, and
the retry policy this workstream exists to add was dead code in practice.

Both layers are now reduced to a single attempt
(`_build_genai_client()` in `src/llm/providers.py`), and the client's policy
is the only one in effect. The same call now fails in **4.9 s** with
`LLMDailyQuotaExhausted` — the right classification, because a daily budget
does not reset in seconds and must not be retried.

This is the kind of defect a fake can never find: the fake provider has no
retry layer of its own.

### 2. A Pydantic validation error quotes the model's answer

The old `generate_structured` put the raw validation error into the
`LLMInvalidOutput` message:

```python
raise LLMInvalidOutput(f"LLM returned invalid JSON for {schema.__name__}: {exc}")
```

A Pydantic `ValidationError` message includes `input_value=...` — the
model's rendering of the candidate's data. That text reached the exception,
and from there any log line or error report. The message is now built from
the error **locations and types only** (`_safe_validation_summary()`), and a
test asserts the answer never appears in it.

### 3. The suite database was missing tables when a test file ran alone

`tests/conftest.py` created the throwaway database from the metadata and
relied on *"every test module is imported during collection"* to have
registered every model. That is true for the full suite and false for a
single file: running `pytest tests/test_llm_client.py` alone failed with
`no such table: audit_events`, because nothing in that one module imported
the model. The conftest now imports every model module explicitly.

## The acceptance criteria, as delivered

- [x] Temperature reaches the provider on every call — asserted on the captured payload, for both `generate_text` and `generate_structured`, on **both** providers, and on the **wire** in the live verification (`"generation_config": {"temperature": 0.2}`).
- [x] A 429 then a 5xx then success → one logical call, three attempts, delays 1.0 s and 4.0 s — no test sleeps (a fake clock and an injected sleep).
- [x] `LLMConfigError` (no key / unknown provider) fails immediately with an actionable message; the key never appears in any exception string, in any log line, or in any audit row.
- [x] Usage rows appear in the audit log with the token counts and zero prompt content.
- [x] Sustained 30 rapid calls at `llm_max_rpm=10` complete without provider 429s — 30 calls span two minutes of virtual time and **no 60-second window holds more than 10 of them**.
- [x] `openai-compatible` provider passes the same fake-transport test battery.

## Deviations from the Part 1 brief, and why

| The brief said | What was built | Why |
|---|---|---|
| "a tiny token-bucket rate limiter" | a **sliding-window** limiter | a bucket of capacity `R` refilling at `R/60` admits `R + R/60` calls per minute — 19 at `R = 10`, enough to trip the very limit the limiter is there to respect (D4a) |
| "embedding + generation share it" | the limiter is the **generation path's alone** | Gemini meters the embedding model and the generation model separately; one shared budget would halve each. The embedding path keeps its live-verified FU-4 throttle (D4b) |
| "`config=types.GenerationConfig(...)`" | `generation_config={"temperature": ...}` | the installed SDK's Interactions API has no `config` argument (S1.2) — verified against the SDK and on the wire |
| "the usage row with `total_tokens`" | `usage_total`, `usage_input`, `usage_output` | the WS-06 redaction filter drops **any** metadata key containing "token". A count is not a credential, but that filter is a security control and is not loosened for a prettier name (D5) |
| "a second provider, `openai-compatible`" | `openai-compatible` **plus** the aliases `openai` and `zai` | both are already documented in `.env.example` with an `LLM_BASE_URL` and both speak the chat-completions dialect. `anthropic` stays unsupported (D6) |
| "one deterministic repair attempt" | the repair is local and spends **no** model call | "deterministic" and "one attempt" are cheaper when the second attempt is a text fix-up rather than a billed call (S7.4) |

## What is still not covered

- The free tier's **daily** quota is spent (20 requests/day on
  `gemini-3.8-flash`), so the live run could not make a *successful* real
  generation call. The verification reports that check as **SKIP** with the
  reason rather than passing it silently. The classification of the real
  quota error — the defect the live run was looking for — **was** verified
  against the real API.
- The `openai-compatible` path has never been exercised against a real
  OpenAI-compatible endpoint; it is verified against `httpx.MockTransport`
  only, and is documented as experimental.
- The client is **synchronous**. The research and tailoring nodes call it
  from synchronous code, so nothing is gained by making it async today.
- The limiter covers the generation path only. A batch API would want the
  embedding path on the same registry (D4b).
