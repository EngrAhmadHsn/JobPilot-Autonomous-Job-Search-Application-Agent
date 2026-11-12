"""WS-27 · A rejected model key must read as a configuration error.

The bug this pins, as it reached an operator: a tailoring request answered

    {"error": {"code": 403, "status": "PERMISSION_DENIED",
              "message": "Method doesn't allow unregistered callers (callers
                          without established identity). Please use API Key
                          or other form of API consumer identity to call this
                          API."}}

That is Google saying **no usable API key arrived**. Four separate defects
were behind it, and each has a test here:

1. **A whitespace-only key passes every guard.** ``"   "`` is truthy, so the
   ``if not api_key`` checks let it through; the SDK then strips it to ``""``
   and sends an empty header. Verified against the installed SDK: an empty
   string raises ``ValueError`` at construction, three spaces construct fine
   and produce exactly the 403 above.
2. **The 403 is classified as an outage.** ``classify_provider_error`` had no
   auth token, so "unregistered callers" fell through to plain ``LLMError``
   and the route answered "the language model is unavailable; try again
   later" — advice that can never work.
3. **The route hides the cause.** ``LLMConfigError`` is an ``LLMError``
   subclass, so it hit the generic 503 handler.
4. **A user could store a blank key.** ``min_length`` ran before ``strip()``,
   so eight spaces satisfied the 8-character minimum and were stored as empty.
"""

from __future__ import annotations

import pytest

from src.llm.errors import (
    LLMConfigError,
    LLMDailyQuotaExhausted,
    LLMError,
    LLMRateLimited,
    LLMUnavailable,
    classify_provider_error,
)

#: The exact body Google returned, kept verbatim so the classifier is tested
#: against reality rather than against a phrase somebody remembered.
GOOGLE_403_BODY = (
    "ClientError: 403 PERMISSION_DENIED. {'error': {'code': 403, 'message': "
    "\"Method doesn't allow unregistered callers (callers without established "
    "identity). Please use API Key or other form of API consumer identity to "
    "call this API.\", 'status': 'PERMISSION_DENIED'}}"
)
GOOGLE_503_BODY = (
    "ServerError: 503 UNAVAILABLE. {'error': {'code': 503, 'message': "
    "'This model is currently experiencing high demand.', 'status': 'UNAVAILABLE'}}"
)
GOOGLE_DAILY_QUOTA_BODY = (
    "ClientError: 429 RESOURCE_EXHAUSTED. {'error': {'code': 429, 'message': "
    "'Quota exceeded for GenerateRequestsPerDay.', 'status': 'RESOURCE_EXHAUSTED'}}"
)


class _Provider(Exception):
    """Stand-in for an SDK exception; only its text matters."""


# --------------------------------------------------------------------------
# 2. The classification
# --------------------------------------------------------------------------


def test_a_missing_key_is_a_configuration_error_not_an_outage():
    """Google's 403 must not be reported as "try again later".

    A wrong or absent key cannot be fixed by waiting, and telling the
    operator to wait hides the one thing they *can* fix.
    """
    classified = classify_provider_error(_Provider(GOOGLE_403_BODY))
    assert isinstance(classified, LLMConfigError)
    assert not isinstance(classified, (LLMUnavailable, LLMRateLimited))


def test_the_auth_check_does_not_swallow_a_real_outage():
    """503 and daily-quota keep their existing meanings.

    The auth tokens are checked before the availability tokens, so this also
    pins that the *ordering* did not capture the normal cases.
    """
    assert isinstance(classify_provider_error(_Provider(GOOGLE_503_BODY)), LLMUnavailable)
    assert isinstance(
        classify_provider_error(_Provider(GOOGLE_DAILY_QUOTA_BODY)), LLMDailyQuotaExhausted
    )


def test_a_plain_401_is_a_configuration_error():
    """The openai-compatible adapter already mapped 401/403; Gemini did not."""
    assert isinstance(
        classify_provider_error(_Provider("ClientError: 401 UNAUTHENTICATED")), LLMConfigError
    )


def test_an_unknown_failure_stays_a_plain_llm_error():
    """The classifier must not claim more than it knows."""
    classified = classify_provider_error(_Provider("SomeError: the moon is in the wrong house"))
    assert type(classified) is LLMError


# --------------------------------------------------------------------------
# 3. Non-retryable
# --------------------------------------------------------------------------


def test_a_configuration_error_is_not_retried():
    """Retrying a rejected key spends the retry budget for nothing.

    The loop's own predicate is what decides, so it is the thing asserted —
    three attempts against a key that will never be accepted is exactly the
    behaviour that made a misconfiguration look like a slow provider.
    """
    from src.llm.client import LLMClient

    assert LLMClient._is_retryable(LLMConfigError("rejected")) is False
    assert LLMClient._is_retryable(LLMUnavailable("503")) is True
    assert LLMClient._is_retryable(LLMRateLimited("429")) is True


# --------------------------------------------------------------------------
# 1. The whitespace guards
# --------------------------------------------------------------------------


@pytest.mark.parametrize("blank", ["", " ", "   ", "\t", "\n", " \t\n "])
def test_a_blank_key_is_not_a_configured_key(blank: str):
    """Every guard must treat a blank key as absent.

    Constructed directly (not from settings) because the guards are reached
    by explicit construction too — that is how a test and a script build a
    client, and the guard has to hold on its own.
    """
    from src.llm.client import LLMClient

    client = LLMClient(provider="google", api_key=blank, model="gemini-3.8-flash", temperature=0.0)
    with pytest.raises(LLMConfigError):
        client._ensure_provider()


def test_a_blank_key_never_builds_a_provider_client():
    """The provider adapter has the same guard, one layer down."""
    from src.llm.providers import build_provider

    provider = build_provider("google", api_key="   ", model="gemini-3.8-flash")
    with pytest.raises(LLMConfigError):
        provider._ensure_client()


def test_a_padded_key_is_still_a_key():
    """Stripping makes a padded key *usable*, not absent.

    The fix is "blank means unset", not "reject anything with whitespace": a
    key pasted with a trailing newline is a real key and must still work.
    """
    from src.llm.client import LLMClient

    client = LLMClient(provider="google", api_key="  AIza-real-key\n", model="m", temperature=0.0)
    # The guard passes; provider construction is what happens next. It may
    # fail for environment reasons, but it must not be the "not set" error.
    try:
        client._ensure_provider()
    except LLMConfigError as exc:
        assert "not set" not in str(exc)


def test_settings_strip_the_key_at_the_boundary(monkeypatch: pytest.MonkeyPatch):
    """``LLM_API_KEY="   "`` must read as unset once settings has it.

    Settings is where every consumer reads the key from, so normalising
    there is what makes "not configured" mean one thing in the whole app.
    """
    from src.config.settings import Settings

    # A fresh instance per case: ``get_settings`` is an ``lru_cache`` and the
    # behaviour under test is the constructor's, not the cache's.
    monkeypatch.setenv("LLM_API_KEY", "   \t ")
    assert Settings().llm_api_key == ""

    monkeypatch.setenv("LLM_API_KEY", "  AIza-padded  ")
    assert Settings().llm_api_key == "AIza-padded"


# --------------------------------------------------------------------------
# 4. The credential store
# --------------------------------------------------------------------------


@pytest.mark.parametrize("blank", ["        ", "   ", "\t\t\t\t\t\t\t\t"])
def test_a_blank_key_cannot_be_stored(blank: str):
    """Eight spaces satisfied the old ``min_length=8`` and stored ``""``.

    Pydantic runs ``min_length`` before an ``after`` validator, so the length
    check has to see the stripped value. Anything that reaches the provider
    as an empty key must be refused at the form, where the user can see it.
    """
    from pydantic import ValidationError

    from src.llm.credentials import LlmCredentialInput

    with pytest.raises(ValidationError):
        LlmCredentialInput(provider="google", model="gemini-3.8-flash", api_key=blank)


def test_a_short_key_is_still_refused():
    """Stripping must not weaken the minimum length for a real-looking key."""
    from pydantic import ValidationError

    from src.llm.credentials import LlmCredentialInput

    with pytest.raises(ValidationError):
        LlmCredentialInput(provider="google", model="m", api_key="short")


def test_a_padded_key_is_stored_stripped():
    """The stored value is the key, without the paste artefact."""
    from src.llm.credentials import LlmCredentialInput

    parsed = LlmCredentialInput(
        provider="  Google ", model="  gemini-3.8-flash ", api_key="  AIza-abcdefgh  "
    )
    assert parsed.provider == "google"
    assert parsed.model == "gemini-3.8-flash"
    assert parsed.api_key == "AIza-abcdefgh"
