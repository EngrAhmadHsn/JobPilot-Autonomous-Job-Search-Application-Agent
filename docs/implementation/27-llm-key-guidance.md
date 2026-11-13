# WS-27 · A Rejected Model Key Must Read as a Configuration Error

Status: **Done (2026-11-12)** · Milestone: **M5** · Depends on: WS-10 (LLM client hardening), WS-14 (identity), WS-22 (bring-your-own model key, the credential store and its console card) · Live-verified: against a running server with an absent, a blank and an invalid key (see §4) · **Extracted from [22-byok-and-reference-adoptions.md](22-byok-and-reference-adoptions.md) §13 on 2026-11-13, where it was first recorded**

> Found in operation: a tailoring request returned

```json
[{"error": {"code": 403, "status": "PERMISSION_DENIED",
  "message": "Method doesn't allow unregistered callers (callers without
              established identity). Please use API Key or other form of API
              consumer identity to call this API."}}]
```

That is Google saying **no usable API key arrived**. Four separate defects
combined to produce it, and each one alone would have been enough to make the
failure unreadable.

---

## 1. What was actually wrong

1. **A whitespace-only key passed every guard.** Both
   `LLMClient._ensure_provider` and `GeminiProvider._ensure_client` tested
   `if not self._api_key`. `"   "` is truthy, so the key sailed through; the
   SDK then stripped it to `""` and sent an empty `x-goog-api-key`. Verified
   against the installed SDK: an empty string raises `ValueError` at
   construction, three spaces construct fine and produce exactly the 403 above.
2. **The 403 was classified as an outage.** `classify_provider_error` keyed on
   retryable tokens and had no auth token, so "unregistered callers" fell
   through to plain `LLMError`. The route's generic handler then answered
   *"The language model is unavailable; try again later."* — advice that cannot
   work, about a setting the operator can fix in a minute.
3. **The route hid the cause.** `LLMConfigError` is an `LLMError` subclass, so
   it hit the generic 503 handler rather than a specific one.
4. **A user could store a blank key.** `LlmCredentialInput` declared
   `min_length=8` and stripped in an `after` validator — Pydantic runs the
   length check first, so **eight spaces satisfied it** and were stored as
   `""`. (Demonstrated directly: the old validator returns `api_key == ""`.)

## 2. The fixes

| Where | Change |
|---|---|
| `src/config/settings.py` | `llm_api_key` is stripped at the boundary, so "not configured" means one thing everywhere |
| `src/llm/client.py`, `src/llm/providers.py` | both guards strip before testing — defence in depth for clients built with an explicit key |
| `src/llm/errors.py` | `_AUTH_TOKENS` (`401`, `403`, `unauthenticated`, `permission_denied`, `unregistered caller`, invalid-key phrases) classify as `LLMConfigError`; the check runs **before** the availability tokens so Google's retryable-looking 403 body cannot win the race. 429/quota/503 semantics are untouched and pinned by test. |
| `src/llm/credentials.py` | the strip runs `mode="before"`, plus a `_not_blank` validator — a blank key fails at the form, where the user can see it |
| `src/api/routes/tailoring.py` | a specific `LLMConfigError` handler that separates **"no key is set"** from **"the provider rejected the key"**, because they are different repairs. The provider's own 403 body stays in the debug log and never reaches the caller. |

No retry behaviour was changed: `_is_retryable` already excluded configuration
errors (it retries only `LLMRateLimited` / `LLMUnavailable`), which is now
pinned rather than assumed.

## 3. The console: where the credential card sits

The card was appended to the bottom of the Profile screen as a bare `<Card>`
after the résumé block — the only orphan card in the console, last on a page
about profile answers, and outside the heading outline (`CardTitle` is a
`div`). Its own docstring calls it an account setting.

Two changes, in `frontend/src/screens/profile-screen.tsx`:

- **Position and structure.** It is wrapped in a `Section` titled **"Your
  model"** (named for the concern, not the widget, following the "What you
  want next" / Work preferences precedent) and moved **above** "From your
  résumé", with the `max-w-3xl` cap the other settings card uses. Order is now
  answers → your model → résumé.
- **Reachability.** The screen's empty state returned before the card rendered,
  so a fresh account with no résumé could not register the key that
  `BYOK_MODE=required` refuses to run without — the comment claiming otherwise
  was false. The screen is now keyed on `profileId` rather than `isPending`:
  a disabled React Query reports `isPending: true` forever, which is why the
  old code showed "Loading…" indefinitely for a profile-less account. Three
  states are distinguished (resolving / no profile / profile), and the card
  renders in all three.

Verified in Chromium against the production build: the `h2` order is
`["Your model", "From your résumé"]` and the card is present with and without
a profile.

## 4. Acceptance

| Check | Test |
|---|---|
| Google's real 403 body classifies as `LLMConfigError` | `tests/test_ws27_llm_key_guidance.py` |
| 503, daily-quota 429 and a plain 401 keep their meanings | `tests/test_ws27_llm_key_guidance.py` |
| A blank key is never a configured key, at both guards | `tests/test_ws27_llm_key_guidance.py` |
| A padded key is still usable (the fix is not "reject whitespace") | `tests/test_ws27_llm_key_guidance.py` |
| Settings strip the key at the boundary | `tests/test_ws27_llm_key_guidance.py` |
| A configuration error is not retried | `tests/test_ws27_llm_key_guidance.py` |
| A blank key cannot be stored; a padded one is stored stripped | `tests/test_ws27_llm_key_guidance.py` |
| The credential card sits above the résumé | `frontend/src/screens/profile-screen.test.tsx` |
| The card renders with no profile at all | `frontend/src/screens/profile-screen.test.tsx` |
| The answer cards survive the reorder | `frontend/src/screens/profile-screen.test.tsx` |

Both new gates were verified to **fail** when the fix is reverted: 9 of the
19 backend cases go red with the guards and the classifier restored to their
previous form, and the placement case goes red when the card is moved back
below the résumé.

End-to-end, against a running server:

| Configuration | Before | After |
|---|---|---|
| `LLM_API_KEY` absent/blank | 503 "…unavailable; try again later" (after retrying) | 503 "not configured: no API key is set… Retrying will not help." |
| `LLM_API_KEY` invalid | 503 "…unavailable; try again later" (after 3 attempts) | 503 "the provider rejected the deployment's API key… Retrying will not help." |

## 5. What this workstream does not cover

- **It does not make a *valid* key succeed.** The platform's own key and quota
  are a separate concern; a 429 from a real quota is still a 429, and the
  classifier keeps that meaning deliberately (§2).
- **It does not add model selection.** BYOK resolves one credential per user
  per provider (WS-22 §2.4); choosing among models is not part of this fix.
- **It does not touch the browser automation path.** The application flow makes
  no model call, so no guard there was affected or audited.
