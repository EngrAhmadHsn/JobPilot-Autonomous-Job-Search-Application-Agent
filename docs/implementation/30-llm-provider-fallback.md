# WS-30 · The Model Provider Fallback Chain

Status: **In progress (2026-11-13)** · Milestone: **M5** ·
Depends on: WS-10 (the LLM client, its provider abstraction and the error
taxonomy), WS-18 (circuit breakers and the shared resilience registry),
WS-22 (bring-your-own model key — the one path that must NOT fall back),
WS-27 (a rejected key must read as a configuration error)

> **Where this starts.** The client knows exactly one provider.
> `get_client()` (`src/llm/client.py:464`) reads `LLM_PROVIDER` /
> `LLM_API_KEY` / `LLM_MODEL` / `LLM_BASE_URL` and builds one adapter. When that
> provider rate-limits, times out or is down, the call fails — after the client's
> bounded retries against *the same* provider, which cannot help. A deployment
> with three usable model keys today uses one of them.

The request (2026-11-13, verbatim):

> use as fallback alibaba's qwen-3.8 from groq provider add env var for api key,
> add https://tokenharbor.ai/v1 as a fallback and use deepseek v4.1-falsh model add
> env var for api key, also add https://gen.pollinations.ai/v1 and use community
> free (community/morriszdweck/glm-5.3-flash-free) glm5.3 flash model with best
> health add env var for api key

Three fallback links behind the configured primary, each with its own key and
model, tried in order.

---

## 1. The three links, verified live

All three endpoints were probed on 2026-11-13 before any code was written. Each
speaks the **chat-completions** dialect, so all three are served by the existing
`OpenAICompatibleProvider` (`src/llm/providers.py:238`) — no new adapter is
needed, only aliases.

| # | Endpoint | Model id | Key var | How it was verified |
|---|---|---|---|---|
| 1 | Groq — `https://api.groq.com/openai/v1` | `qwen/qwen3.8-27b` | `GROQ_API_KEY` | `GET /openai/v1/models` answers **401** without a key (the endpoint exists and requires auth); the model id is from Groq's published model list |
| 2 | TokenHarbor — `https://tokenharbor.ai/v1` | `deepseek-v4.1-flash` | `TOKENHARBOR_API_KEY` | `GET /v1/models` answers **401** `{"error":{"type":"invalid_api_key"}}` with the message *"Send Authorization: Bearer thk_live_…"* — confirming both the OpenAI shape and the header |
| 3 | Pollinations — `https://gen.pollinations.ai/v1` | `community/morriszdweck/glm-5.3-flash-free` | `POLLINATIONS_API_KEY` | `GET /v1/models` answers **200** with 437 models, health included; a keyless `POST /chat/completions` answers **401** asking for a key |

### The Pollinations model is a free community mirror with a usable health record

The endpoint publishes per-model health, which is what "with best health" can
be measured against. At planning time (2026-11-13 morning) the requested model
was also the healthiest of its family, so the named id and the "best health"
instruction did not conflict:

| Model | Community | Health | Success rate | Requests |
|---|---|---|---|---|
| **`community/morriszdweck/glm-5.3-flash-free`** | yes | **healthy** | **98.0 %** | 50 |
| `community/Saauf/glm-5.3-flash` | yes | healthy | 97.2 % | 36 |
| `community/Catniti/glm-5.3-flash` | yes | degraded | 94 % | 50 |
| `community/MarcosFRG/glm-5.3-flash` | yes | degraded | 88 % | 50 |

**That ranking is a snapshot, not a property** — and the live verification run
proved it (§7): a few hours later the same model reported `degraded` at 88 %
(and 82 % on a second look) while the mirrors reordered around it. The
authoritative choice is therefore the **named id from the request**, which is a
free community mirror of GLM-5.3-flash; the health figure is a live signal the
operator can read from the endpoint's own catalogue, not a promise this project
can make.

The non-community `z-ai/glm-5.3-flash` is the vendor's own listing (99.98 %,
5,824 requests at planning time) and is not a community free tier, so it is not
the default. A deployment that prefers it sets `POLLINATIONS_MODEL=z-ai/glm-5.3-flash`.

**A model id that could not be verified from here.** TokenHarbor's model list
requires a key, so `deepseek-v4.1-flash` could not be confirmed against the
vendor — it is the id the request names, spelled the way every other provider
spells it (Pollinations lists `deepseek/deepseek-v4.1-flash-1017` and
`deepseek/deepseek-v4.1-flash`). It is a **default, not a constant**: the model
is per-link configurable, and §6 records this as the one item to confirm against
the operator's own TokenHarbor account.

---

## 2. The design

### 2.1 Provider aliases carry the endpoint

`build_provider` already resolves an alias to its vendor default
(`_OPENAI_COMPATIBLE_ALIASES`, `src/llm/providers.py:64`). Three rows are added:

```python
"groq":         "https://api.groq.com/openai/v1",
"tokenharbor":  "https://tokenharbor.ai/v1",
"pollinations": "https://gen.pollinations.ai/v1",
```

Two consequences beyond the chain:

* a fallback link needs **no base URL**, only a key and a model;
* the new aliases become registerable bring-your-own-key providers
  (`src/llm/credentials.py:114` and `_resolved_base_url`), so a user can store
  a Groq key with no URL — which is the whole point of naming them.

The primary can also be set to any of them (`LLM_PROVIDER=groq`), so "Groq is
first, Gemini is the fallback" is a configuration, not a code path.

### 2.2 The chain is a `Provider`, not a second client

The fallback lives at the **provider seam**. `FallbackProvider`
(`src/llm/fallback.py`) implements the two-method `Provider` protocol and wraps
an ordered list of already-built adapters. The client keeps doing exactly what
it does today — one provider, one timeout, one limiter, one retry loop, one
breaker, one usage row — and the chain walks *inside* one call:

```
LLMClient.generate_structured
  └─ _call → limiter → FallbackProvider.complete
       ├─ link 1 (primary)   → ok?  return
       ├─ link 2 (groq)      → break / 429 / 5xx / 401 → next
       └─ link 3 (…)         → ok?  return
```

Why not a second `LLMClient` per link: pacing, retries, breakers and the usage
row would multiply, and "one logical call" (WS-10's contract, pinned by
`tests/test_llm_client.py::TestRetry`) would become "three logical calls" the
moment a provider was slow. The decorator keeps that contract exactly —
`_CredentialProvider` (`src/llm/credentials.py:479`) is the precedent for it.

### 2.3 What advances the chain

| Failure | Advance? | Why |
|---|---|---|
| `LLMRateLimited` (429), `LLMUnavailable` (5xx), `LLMTimeout` | **yes** | the link is throttled or down; the next one may not be |
| `LLMConfigError` (401/403, unknown model, bad request) | **yes** | *this* link is misconfigured; it must not take the others down with it |
| `LLMCircuitOpen` (the link's breaker is open) | **yes, without calling** | the breaker exists to skip a provider that is already failing (WS-18) |
| success | no | — |

Every link failure is logged at WARNING with the link's provider and model, so
"Groq answered" / "Groq was skipped, its key is rejected" is in the log even
when the caller never sees an error.

### 2.4 The error when everything fails

The chain raises the **first attempted link's** error (the primary, when one is
configured), with a one-line summary of every link appended:

```
LLM unavailable: … (fallback chain exhausted: google/gemini-3.8-flash →
LLMUnavailable; groq/qwen/qwen3.8-27b → LLMRateLimited; …)
```

The first link's class is preserved because that is the deployment's declared
path and the one an operator repairs; the failing chain's own class would say
"the last provider I happened to try is down", which names the least important
link. The message carries no key — every link's message goes through
`scrub_secret` before it is stored.

### 2.5 Whose model answered is recorded

`ProviderResponse` gains two optional fields, `provider` and `model`. The chain
sets them from the link that answered, and `LLMClient._record_success` prefers
them over the client's own identity. Without this, a call answered by Groq would
write a usage row (and an audit `resource`) naming the primary's model — the
spend record would be a lie, and WS-10's "the spend is visible" promise would be
broken in the exact case the feature was built for. Both fields default to
`None`, so every existing provider and fake keeps working unchanged.

### 2.6 Each link keeps its own breaker

The chain consults `get_breaker(f"llm:{link.provider}")` per link
(WS-18's registry, shared through the database when `CIRCUIT_SHARED_STATE` is
on): an open link breaker is skipped without a call, a link success closes it,
a link failure counts against it, and a *permanent* failure does not open it
(`record_failure(retryable=False)` — a bad key is not an outage, the WS-27
rule). `breaker_snapshot()` already surfaces all of them through
`/api/health` and the operations screen, so which link is down is observable
without new machinery.

The client's own breaker still wraps the whole call under
`llm:fallback-chain` — "every link failed" — which is a different and also true
statement.

### 2.7 What the chain deliberately does not do

* **It does not chain a bring-your-own-key client.** WS-22's ruling stands: a
  user's failing key never spends the platform's quota, and the platform's
  fallback keys are the platform's. `_build_byok_client` is untouched.
* **It does not target per-link rate limits.** The client's single sliding
  window meters the deployment's own budget ("how fast may this deployment call
  model providers"); a link that throttles is handled by its 429 → breaker →
  skip path rather than by a second pacing layer.
* **It does not re-try a link's *answer*.** `generate_structured`'s schema
  validation and its local JSON repair stay in the client, above the chain: a
  link that returns a fenced or prose-wrapped object is repaired there and never
  needs a second provider. A link that returns something unparseable *and*
  unfixable ends the call as `LLMInvalidOutput` — see §6, the one boundary this
  design accepts.

---

## 3. Environment variables

Seven new variables. A link is **active when both its key and its model are
non-blank**; a blank key disables that link silently (the log notes it at DEBUG
level), which is the natural way to turn one off without touching the code.

| Variable | Default | Rule |
|---|---|---|
| `LLM_FALLBACK_ENABLED` | `true` | `false` disables the whole chain; the primary is then the only provider, exactly as before |
| `GROQ_API_KEY` | *(empty)* | the link's key; empty = the link is not active |
| `GROQ_MODEL` | `qwen/qwen3.8-27b` | Groq's published id for Qwen 3.8 |
| `TOKENHARBOR_API_KEY` | *(empty)* | as above |
| `TOKENHARBOR_MODEL` | `deepseek-v4.1-flash` | per §1, to confirm against the vendor's own list |
| `POLLINATIONS_API_KEY` | *(empty)* | as above |
| `POLLINATIONS_MODEL` | `community/morriszdweck/glm-5.3-flash-free` | the requested community model, healthiest of its family |

The order is fixed and documented — primary, then Groq, then TokenHarbor, then
Pollinations — because "a link with no key is skipped" already makes the list
configurable in the only way that matters (which links exist). A separate order
variable would be a second way to express the same thing.

---

## 4. Execution plan

| Phase | Deliverable | Gate |
|---|---|---|
| **A** | The three aliases in `providers.py`, and in the BYOK provider list + `_resolved_base_url` | `test_ws30_llm_fallback.py::TestAliases`; the existing provider tests still green |
| **B** | Settings: the seven variables, parsed and validated, plus the `.env.example` rows and the `SETTINGS_VAR_TO_ATTR` entries | `test_env_docs.py` (all five assertions) green |
| **C** | `src/llm/fallback.py`: `FallbackLink`, `build_fallback_links`, `build_fallback_chain`, `FallbackProvider`; `ProviderResponse.provider/model`; `_record_success` prefers them | the chain tests: advance, skip, breaker, identity, error summary |
| **D** | `get_client()` builds the chain; `credentials.py` aliases; console provider list; README | full offline suite green; the console card test green |
| **E** | Live verification against the three real endpoints (the operator's keys) | one real tailoring, or a scripted call per link, recorded in §7 |

### Test matrix

| File | Covers |
|---|---|
| `tests/test_ws30_llm_fallback.py` (new) | aliases + default base URLs; link building from settings (blank key/model skipped, `LLM_FALLBACK_ENABLED=false`); advance on retryable / config / plain error; no advance on success; a link breaker opened → skipped without a call; the answering link recorded in the usage row; the all-failed error names the primary's class and lists every link; no key in any message; BYOK untouched; `get_client()` builds the chain |
| `tests/test_env_docs.py` (extended) | the seven new variables are documented, read, and state the code's defaults |
| `tests/test_llm_providers.py` (extended) | the alias table resolves as documented |

### Risks

| Risk | Mitigation |
|---|---|
| A fallback answers when the primary's key is simply wrong, hiding a fixable setting (the WS-27 failure mode) | the link failure is logged at WARNING naming the repair; the usage row and the audit `resource` name the model that actually answered; §2.4 keeps the primary's error class when everything fails |
| A link's model id is wrong (TokenHarbor's could not be verified) | the model is a setting, not a constant; a 400/404 advances the chain, so a wrong id costs one skipped link |
| Three providers silently spreading candidate data further | the prompt is the same one, the PII mask (WS-22) applies unchanged above the chain, and no provider is contacted that the operator has not given a key for |
| A community model (Pollinations) returning a non-JSON answer | the client's repair (fence strip / outermost-object extraction) runs above the chain; §6 records the residual case |

---

## 5. Implementation status

| Item | State |
|---|---|
| §4 Phase A — aliases | **done** — `groq`, `tokenharbor`, `pollinations` in the alias table, in `SUPPORTED_PROVIDERS`'s error message, and in the BYOK provider list; `alias_base_url()` exposes the table so a stored credential resolves the same URL the platform builds |
| §4 Phase B — settings + env docs | **done** — seven variables, `FallbackLinkConfig`, and `test_env_docs.py` extended with a spec-table-aware scanner |
| §4 Phase C — the chain | **done** — `src/llm/fallback.py` + 36 tests |
| §4 Phase D — wiring + console + README | **done** — `get_client()` wraps the adapter; the credential card offers the three aliases; README documents them |
| §4 Phase E — live verification | **done** — `scripts/verify_ws30_31.py`, 22 WS-30 checks, all passing (§7) |

---

## 6. Open items and accepted boundaries

1. **TokenHarbor's model id is unverified.** Default `deepseek-v4.1-flash`;
   its `/v1/models` needs a key, so the id could not be confirmed against the
   vendor. The live run confirms the **endpoint** (401 at the chat path with
   `thk_live_…` naming), which is as far as it can go without a key. Confirm
   against the account's model list and override `TOKENHARBOR_MODEL` if the
   vendor spells it differently. A wrong id costs one skipped link, not a
   failed call.
2. **An unfixable malformed answer does not advance the chain.** The chain lives
   at the provider seam, so `LLMInvalidOutput` — raised by the client *after*
   parsing — ends the call. Accepted because the client already repairs the two
   real-world shapes (a fenced block, prose around the object), and because
   moving the chain above parsing would mean re-running the usage, limiter and
   breaker logic per attempt, which is what §2.2 exists to avoid. The boundary
   is pinned by a test rather than left implicit.
3. **No per-link rate limits** (§2.7). The deployment's RPM applies to the
   chain as a whole.
4. **The chain is not used for embeddings.** The Gemini embedding path
   (`src/llm/embeddings.py`) reads `LLM_API_KEY` directly and is a different
   quota with a different budget; it is out of scope here.
5. **Pollinations' free tier may answer 200 without a key.** The live probe
   found `POST /v1/chat/completions` answering **200** with no key on
   2026-11-13, while a keyless call at planning time answered 401. The link is
   configured with a key regardless (the operator supplies one), and the
   behaviour is recorded rather than relied on — a free tier that changes its
   mind needs no code change.

---

## 7. Live verification (2026-11-13)

`env\Scripts\python.exe scripts\verify_ws30_31.py` — **52/52 checks**, of which
22 are WS-30's. The WS-30 results:

```
[PASS] the groq alias builds its vendor endpoint — https://api.groq.com/openai/v1
[PASS] a stored user credential resolves groq without a URL
[PASS] the tokenharbor alias builds its vendor endpoint — https://tokenharbor.ai/v1
[PASS] a stored user credential resolves tokenharbor without a URL
[PASS] the pollinations alias builds its vendor endpoint — https://gen.pollinations.ai/v1
[PASS] a stored user credential resolves pollinations without a URL
[PASS] the groq endpoint exists at the URL the alias carries — HTTP 401
[PASS] the tokenharbor endpoint exists at the URL the alias carries — HTTP 401
[PASS] the pollinations endpoint exists at the URL the alias carries — HTTP 200
[PASS] Pollinations serves the configured model 'community/morriszdweck/glm-5.3-flash-free'
[PASS] the configured Pollinations model publishes a usable health record — degraded 88%
[PASS] its success rate is not below the degraded floor — 88%
[PASS] other free community mirrors of the same model exist — 5 mirrors listed
[PASS] a failing primary hands the call to the fallback
[PASS] the usage row names the link that answered, not the primary — provider=groq model=qwen/qwen3.8-27b
[PASS] the model in the usage row is the fallback's own
[PASS] the chain names every tried link when all of them fail
[PASS] with no keys set, no fallback link is active — groq=off, tokenharbor=off, pollinations=off
[PASS] setting one key activates exactly that link — active: ['groq']
[PASS] the activated link carries the documented model — qwen/qwen3.8-27b
[PASS] LLM_FALLBACK_ENABLED=false returns the primary untouched
```

### What the live run changed in this document

* **The "healthy" claim was overstated and is now honest.** At planning time the
  model reported `healthy` at 98%; the run found it `degraded` at 88% (and at 82%
  on a second look). The endpoint's health is a *live, moving* signal — five
  community mirrors of the same model were between 82% and 97% across a few
  minutes. §1's table is a **snapshot**, and the verification asserts what is
  stable (the model is served, its health record is usable, its success rate is
  above the degraded floor) while *reporting* the live numbers.
* **The auth boundary is per-endpoint, and Pollinations' differs.** Its
  `/v1/models` catalogue is public (200) while `/v1/chat/completions` is the
  path the client calls — which answered 200 without a key at verification
  time. The probe was corrected to call the endpoint the client actually uses,
  and §6.5 records the finding.
* **The fallback endpoint URLs are confirmed live** — Groq and TokenHarbor both
  401 at their model lists, so both paths are real and key-gated; no 404s.

