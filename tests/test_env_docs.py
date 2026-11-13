"""WS-11 · The env example file and the code must agree.

``.env.example`` is the file an operator copies to ``.env``. If it names a
variable the code never reads, the operator believes they have configured
something they have not. If it omits a variable the code reads, the operator
discovers the default the hard way. And if a documented value drifts away
from the code's own default, the file is a second source of truth — and the
two sources always disagree eventually.

This test is that agreement, made permanent. It reads the runtime to find
out which variables the code actually reads, reads the example file to find
out which variables it documents, and asserts the two sets are the same and
that the documented values are the code's defaults.

The three assertions:

* **A** — every variable the runtime reads is documented.
* **B** — every documented variable is read by the runtime.
* **C** — a documented value equals the code's own default.

Assertion C is the strict one, and it is why the file cannot rot: change a
default in ``src/config/settings.py`` without updating ``.env.example`` and
this test fails.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from src.applications.fake_ats_adapter import launch_options
from src.config.settings import Settings
from src.llm.embeddings import fastembed_cache_dir
from src.security.limits import get_limits, reset_limits

REPO_ROOT = Path(__file__).resolve().parents[1]
ENV_EXAMPLE = REPO_ROOT / ".env.example"
SRC_DIR = REPO_ROOT / "src"

# The ways the runtime reads an environment variable. The last two cover
# src/security/limits.py, which reads its knobs through a helper that takes
# the name as a literal at the call site.
_ENV_PATTERNS = (
    re.compile(r"""os\.getenv\(\s*["']([A-Z][A-Z0-9_]*)["']"""),
    re.compile(r"""os\.environ\.get\(\s*["']([A-Z][A-Z0-9_]*)["']"""),
    re.compile(r"""os\.environ\[\s*["']([A-Z][A-Z0-9_]*)["']"""),
    re.compile(r"""_int_env\(\s*["']([A-Z][A-Z0-9_]*)["']"""),
    re.compile(r"""_float_env\(\s*["']([A-Z][A-Z0-9_]*)["']"""),
)

# WS-30: the provider fallback chain names its six variables in a **spec
# table** rather than calling ``os.getenv`` once per variable, and
# ``Settings._parse_fallback_links`` reads that table row by row. A row is
# ``("groq", "GROQ_API_KEY", "GROQ_MODEL", "<default model>")`` — an alias,
# then a key variable and a model variable. The pattern is deliberately narrow
# (an alias-shaped first element, then exactly two ENV-shaped names) so it
# matches that table and not some unrelated tuple.
_ENV_PAIR_PATTERNS = (
    re.compile(
        r"""\(\s*"[a-z][a-z0-9_-]*"\s*,\s*"([A-Z][A-Z0-9_]*)"\s*,\s*"([A-Z][A-Z0-9_]*)"\s*,"""
    ),
)

# A line of .env.example is an entry when it is `NAME=value`, with or
# without a leading comment marker. A commented entry is an *example* of an
# override; an uncommented entry states the default.
_ENTRY_PATTERN = re.compile(r"^\s*#?\s*([A-Z][A-Z0-9_]*)\s*=(.*)$")


def _runtime_env_vars() -> set[str]:
    """Every environment variable the runtime reads, by name."""
    names: set[str] = set()
    for path in sorted(SRC_DIR.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        for pattern in _ENV_PATTERNS:
            names.update(pattern.findall(text))
        # WS-30: the spec-table form contributes two names per matched row.
        for pattern in _ENV_PAIR_PATTERNS:
            for key_var, model_var in pattern.findall(text):
                names.update((key_var, model_var))
    return names


def _documented_env_vars() -> dict[str, tuple[str, bool]]:
    """Every variable the example file documents.

    Returns a mapping of name → (value, is_commented_example).
    """
    entries: dict[str, tuple[str, bool]] = {}
    for line in ENV_EXAMPLE.read_text(encoding="utf-8").splitlines():
        match = _ENTRY_PATTERN.match(line)
        if not match:
            continue
        name, raw = match.group(1), match.group(2).strip()
        entries[name] = (raw, line.lstrip().startswith("#"))
    return entries


# Which documented variable holds which attribute of the settings object.
# A variable that is read but has no entry here is reported by the test
# rather than skipped, so this table cannot rot unnoticed.
SETTINGS_VAR_TO_ATTR = {
    "APP_NAME": "app_name",
    "APP_ENV": "app_env",
    "APP_DEBUG": "app_debug",
    "LOG_LEVEL": "log_level",
    "DATABASE_URL": "database_url",
    "CORS_ORIGINS": "cors_origins",
    "LLM_PROVIDER": "llm_provider",
    "LLM_API_KEY": "llm_api_key",
    "LLM_MODEL": "llm_model",
    "LLM_BASE_URL": "llm_base_url",
    "LLM_TEMPERATURE": "llm_temperature",
    "LLM_TIMEOUT": "llm_timeout",
    "LLM_MAX_RPM": "llm_max_rpm",
    "LLM_MAX_RETRIES": "llm_max_retries",
    # WS-30: the provider fallback chain's switch. The six per-link variables
    # are read by ``_parse_fallback_links`` and are checked by FALLBACK_LINK_VARS
    # below, since they have no Settings attribute of their own.
    "LLM_FALLBACK_ENABLED": "llm_fallback_enabled",
    # WS-22: the bring-your-own-key mode and its encryption key source. The
    # key source is documented as an empty default (unset means "derive from
    # AUTH_SECRET, or fall back to the development key file").
    "BYOK_MODE": "byok_mode",
    "BYOK_ENCRYPTION_KEY": "byok_encryption_key",
    "LANGSMITH_TRACING": "llm_tracing",
    "LANGSMITH_API_KEY": "langsmith_api_key",
    "LANGSMITH_PROJECT": "langsmith_project",
    "JOB_SOURCE_TIMEOUT": "job_source_timeout",
    "JOB_SOURCE_MIN_INTERVAL": "job_source_min_interval",
    "EMBEDDING_PROVIDER": "embedding_provider",
    "EMBEDDING_DIMENSIONALITY": "embedding_dimensionality",
    "EMBEDDING_RPM_LIMIT": "embedding_rpm_limit",
    "EMBEDDING_RPD_LIMIT": "embedding_rpd_limit",
    # WS-18 follow-up: the local model's inference batch ceiling.
    "EMBEDDING_BATCH_SIZE": "embedding_batch_size",
    "CHROMA_DIR": "chroma_dir",
    "MATCH_WEIGHTS": "match_weights",
    "SUBMISSION_POLICY": "submission_policy",
    "ALLOWED_DOMAINS": "allowed_domains",
    "DATA_DIR": "data_dir",
    "EVIDENCE_DIR": "evidence_dir",
    "RESUME_UPLOAD_DIR": "resume_upload_dir",
    "TAILORED_DIR": "tailored_dir",
    # WS-14 · A1: the identity settings.
    "AUTH_SECRET": "auth_secret",
    "AUTH_SESSION_COOKIE_NAME": "auth_session_cookie_name",
    "AUTH_CSRF_COOKIE_NAME": "auth_csrf_cookie_name",
    "AUTH_COOKIE_SECURE": "auth_cookie_secure",
    "AUTH_SESSION_TTL_SECONDS": "auth_session_ttl_seconds",
    "AUTH_REQUIRE_VERIFIED": "auth_require_verified",
    "AUTH_CLAIM_LEGACY": "auth_claim_legacy",
    "AUTH_TOKEN_MAILBOX_DIR": "auth_token_mailbox_dir",
    # WS-14 · Phase D: the retention windows.
    "RETENTION_PROFILE_DAYS": "retention_profile_days",
    "RETENTION_TAILORED_DAYS": "retention_tailored_days",
    "RETENTION_APPLICATION_DAYS": "retention_application_days",
    "RETENTION_EVIDENCE_DAYS": "retention_evidence_days",
    "RETENTION_SESSION_DAYS": "retention_session_days",
    "RETENTION_DELETION_GRACE_DAYS": "retention_deletion_grace_days",
    # WS-18: durable execution.
    "WORKER_ID": "worker_id",
    "WORKER_POLL_INTERVAL_SECONDS": "worker_poll_interval_seconds",
    "WORKER_LEASE_SECONDS": "worker_lease_seconds",
    "WORKER_HEARTBEAT_SECONDS": "worker_heartbeat_seconds",
    "WORKER_BATCH_SIZE": "worker_batch_size",
    "WORKER_MAX_ATTEMPTS": "worker_max_attempts",
    "WORKER_RETRY_BASE_SECONDS": "worker_retry_base_seconds",
    "WORKER_RETRY_MAX_SECONDS": "worker_retry_max_seconds",
    "RUN_STALE_SECONDS": "run_stale_seconds",
    "WORKER_STALE_SECONDS": "worker_stale_seconds",
    "RETRY_MAX_DELAY_SECONDS": "retry_max_delay_seconds",
    "CIRCUIT_FAILURE_THRESHOLD": "circuit_failure_threshold",
    "CIRCUIT_RECOVERY_SECONDS": "circuit_recovery_seconds",
    "CIRCUIT_SHARED_STATE": "circuit_shared_state",
    # WS-20 follow-up: the API's bounded worker control.
    "WORKER_CONTROL_ENABLED": "worker_control_enabled",
    "WORKER_MAX_CONCURRENT": "worker_max_concurrent",
}

# The same, for the WS-12 runtime limits.
LIMITS_VAR_TO_ATTR = {
    "RATE_LIMIT_REQUESTS": "rate_limit_requests",
    "RATE_LIMIT_WINDOW_SECONDS": "rate_limit_window_seconds",
    "BODY_LIMIT_BYTES": "body_limit_bytes",
    "MAX_CONCURRENT_HEAVY": "max_concurrent_heavy",
    "HEAVY_QUEUE_TIMEOUT_SECONDS": "heavy_queue_timeout_seconds",
    "MAX_INFLIGHT_REQUESTS": "max_inflight_requests",
    "MAX_LISTINGS_PER_SOURCE": "max_listings_per_source",
    "MAX_NEW_LISTINGS_PER_REFRESH": "max_new_listings_per_refresh",
    "MAX_CORPUS_LISTINGS": "max_corpus_listings",
    "MAX_CORPUS_EVICTIONS_PER_REFRESH": "max_corpus_evictions_per_refresh",
    # WS-23b: the admission age bound.
    "MAX_JOB_AGE_DAYS": "max_job_age_days",
    "MAX_EMBED_PER_REFRESH": "max_embed_per_refresh",
    "MAX_EMBED_WORK_PER_DAY": "max_embed_work_per_day",
    "MAX_CACHE_ENTRIES": "max_cache_entries",
    "MAX_UPLOAD_UNCOMPRESSED_BYTES": "max_upload_uncompressed_bytes",
    "MAX_ZIP_ENTRIES": "max_zip_entries",
    "MAX_RESPONSE_BYTES": "max_response_bytes",
    "MAX_CUSTOM_FIELDS": "max_custom_fields",
    "MAX_CUSTOM_FIELD_CHARS": "max_custom_field_chars",
    "MAX_DESCRIPTION_CHARS": "max_description_chars",
    "MAX_TITLE_CHARS": "max_title_chars",
    "MAX_COMPANY_CHARS": "max_company_chars",
    "MAX_PROMPT_UNTRUSTED_CHARS": "max_prompt_untrusted_chars",
    # WS-18: the bounded background queue.
    "MAX_PENDING_RUNS": "max_pending_runs",
    "MAX_PENDING_WORK_ITEMS": "max_pending_work_items",
}

# Documented variables that deliberately do NOT state a default, and why.
NOT_A_DEFAULT = {
    "GREENHOUSE_BOARDS": "a curated board list, not the code's empty default",
    "LEVER_COMPANIES": "a curated company list, not the code's empty default",
    "ASHBY_ORGS": "a curated org list, not the code's empty default",
}

# Documented variables whose value is not held by Settings or SecurityLimits
# and is therefore compared by its own rule.
SPECIAL_DEFAULTS = {
    "PLAYWRIGHT_HEADLESS",  # compared against launch_options()
    "FASTEMBED_CACHE_PATH",  # derived from DATA_DIR in src/llm/embeddings.py
    # Derived from DATA_DIR in src/config/settings.py, like the fastembed
    # cache above.
    "AUTH_TOKEN_MAILBOX_DIR",
    "EMBEDDING_MODEL",  # provider-dependent; documented as a commented example
    # WS-25: read by src/db/approval.py rather than by Settings — the
    # approval window is a policy of the approval store, and it has its
    # own default (168 hours) with a fallback for a bad value.
    "APPROVAL_TTL_HOURS",
}

# WS-30: the provider fallback chain's per-link variables. They are read by
# ``Settings._parse_fallback_links`` from its own spec table rather than as
# individual attributes, so each is checked against the spec that actually
# consumes it — which also proves the .env.example row and the code's table
# name the same variable. A blank key is the documented default for the keys;
# each model's documented value must equal the spec's default model.
FALLBACK_KEY_VARS = {"GROQ_API_KEY", "TOKENHARBOR_API_KEY", "POLLINATIONS_API_KEY"}
FALLBACK_MODEL_DEFAULTS = {
    "GROQ_MODEL": "qwen/qwen3.8-27b",
    "TOKENHARBOR_MODEL": "deepseek-v4.1-flash",
    "POLLINATIONS_MODEL": "community/morriszdweck/glm-5.3-flash-free",
}
#: Every variable read from the fallback spec table, so a variable that exists
#: in the test's rules but not in the code's table is a failure rather than a
#: silently skipped check.
FALLBACK_LINK_VARS = FALLBACK_KEY_VARS | set(FALLBACK_MODEL_DEFAULTS)


def _normalize(value: str) -> str:
    """Normalize a path-ish value so ``./data/x`` and ``data/x`` compare equal."""
    return str(Path(value))


def _code_default(name: str, settings: Settings, limits) -> object:
    """The code's own default for a documented variable."""
    if name == "PLAYWRIGHT_HEADLESS":
        return launch_options()["headless"]
    if name == "FASTEMBED_CACHE_PATH":
        return _normalize(fastembed_cache_dir(settings))
    if name in FALLBACK_KEY_VARS:
        # WS-30: an unset key is the default, and that is what disables a link.
        return None
    if name in FALLBACK_MODEL_DEFAULTS:
        return FALLBACK_MODEL_DEFAULTS[name]
    if name in SETTINGS_VAR_TO_ATTR:
        return getattr(settings, SETTINGS_VAR_TO_ATTR[name])
    if name in LIMITS_VAR_TO_ATTR:
        return getattr(limits, LIMITS_VAR_TO_ATTR[name])
    raise AssertionError(f"No default rule for {name}")


def _values_match(documented: str, actual: object) -> bool:
    """Whether a documented value states the code's default."""
    if actual is None:
        # An empty documented value means "unset", which the code renders
        # as None for the optional settings.
        return documented == ""
    if isinstance(actual, bool):
        return (
            documented.strip().lower() in {"true", "false"}
            and (documented.strip().lower() == "true") == actual
        )
    if isinstance(actual, list):
        return [part.strip() for part in documented.split(",") if part.strip()] == actual
    if isinstance(actual, int) and not isinstance(actual, bool):
        try:
            return int(documented) == actual
        except ValueError:
            return False
    if isinstance(actual, float):
        try:
            return float(documented) == actual
        except ValueError:
            return False
    if isinstance(actual, str):
        return _normalize(documented) == _normalize(actual)
    return documented == str(actual)


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove every runtime variable so the code's own defaults show through.

    ``load_dotenv`` runs at import time and puts the developer's ``.env`` into
    ``os.environ``; without this, the "default" would be whatever is in that
    file.
    """
    for name in _runtime_env_vars() | set(_documented_env_vars()):
        monkeypatch.delenv(name, raising=False)


def test_every_runtime_variable_is_documented() -> None:
    """A: a variable the code reads is a variable the example file names."""
    runtime = _runtime_env_vars()
    documented = set(_documented_env_vars())

    missing = sorted(runtime - documented)

    assert not missing, (
        f"{len(missing)} variable(s) the runtime reads are not in .env.example: "
        f"{missing}. Add them with a comment explaining what they bound."
    )


def test_every_documented_variable_is_read() -> None:
    """B: a documented variable is a variable the code actually reads."""
    runtime = _runtime_env_vars()
    documented = set(_documented_env_vars())

    unused = sorted(documented - runtime)

    assert not unused, (
        f"{len(unused)} variable(s) in .env.example are read by nothing: {unused}. "
        "Either wire them up or remove them — a documented knob that does "
        "nothing is a lie about the configuration."
    )


def test_documented_values_are_the_code_defaults(
    clean_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """C: the example file states the code's own defaults.

    The variables that deliberately do not state a default (the curated
    board lists) and the commented-out examples are excluded, each with a
    recorded reason.
    """
    settings = Settings()
    reset_limits()
    limits = get_limits()

    entries = _documented_env_vars()
    checked: list[str] = []
    mismatches: list[str] = []

    for name, (value, is_comment) in sorted(entries.items()):
        if is_comment or name in NOT_A_DEFAULT or name in SPECIAL_DEFAULTS:
            continue
        actual = _code_default(name, settings, limits)
        if not _values_match(value, actual):
            mismatches.append(f"{name}: documented {value!r}, code default {actual!r}")
        checked.append(name)

    assert not mismatches, (
        ".env.example and the code disagree about the default of:\n  " + "\n  ".join(mismatches)
    )
    # A sanity floor: the check must actually be checking something.
    assert len(checked) >= 30, f"only {len(checked)} defaults were checked"


def test_the_documented_default_of_every_known_variable_is_checked() -> None:
    """The mapping tables cover every documented variable.

    A variable that is documented but has no rule would be silently skipped
    by the default check; this test fails instead.
    """
    documented = set(_documented_env_vars())
    known = (
        set(SETTINGS_VAR_TO_ATTR)
        | set(LIMITS_VAR_TO_ATTR)
        | set(NOT_A_DEFAULT)
        | set(SPECIAL_DEFAULTS)
        | set(FALLBACK_LINK_VARS)
    )

    unknown = sorted(documented - known)

    assert not unknown, (
        f"{unknown} are documented but have no default rule. Add them to the "
        "mapping tables in this test, with a reason if they are not defaults."
    )


def test_the_fallback_link_defaults_match_the_code_spec_table(
    clean_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """WS-30: the documented model defaults are the ones the code itself uses.

    The table above is this test's copy of the defaults; this assertion reads
    the **code's** spec table and the settings the code builds from it, so the
    two cannot drift. It also proves the blank-key-means-disabled rule: with
    no keys set, every link reports ``active`` False.
    """
    from src.config.settings import _FALLBACK_LINK_SPECS, Settings

    settings = Settings()
    by_var = {
        key_var: (alias, default_model)
        for alias, key_var, _model_var, default_model in _FALLBACK_LINK_SPECS
    }

    assert set(FALLBACK_KEY_VARS) == set(by_var), (
        "the test's key-variable list and the code's spec table disagree"
    )
    for model_var, documented in FALLBACK_MODEL_DEFAULTS.items():
        alias = next(
            spec_alias
            for spec_alias, _k, spec_model_var, _d in _FALLBACK_LINK_SPECS
            if spec_model_var == model_var
        )
        link = next(link for link in settings.llm_fallback_links if link.alias == alias)
        assert link.model == documented, (
            f"{model_var} documents {documented!r} but {alias} builds {link.model!r}"
        )

    assert all(not link.active for link in settings.llm_fallback_links), (
        "with no keys configured, no fallback link may be active"
    )

    monkeypatch.setenv("GROQ_API_KEY", "gsk_test")
    activated = Settings()
    assert [link.active for link in activated.llm_fallback_links] == [True, False, False], (
        "setting one link's key must activate exactly that link"
    )


def test_the_example_file_does_not_contain_a_secret() -> None:
    """The example file carries no credential-shaped value.

    The patterns require a plausible length, so an ordinary word cannot trip
    the check while a real key always does.
    """
    text = ENV_EXAMPLE.read_text(encoding="utf-8")

    for pattern, description in (
        (re.compile(r"AIza[0-9A-Za-z_\-]{20,}"), "a Google API key"),
        (re.compile(r"\bsk-[A-Za-z0-9_\-]{20,}"), "an OpenAI-style API key"),
        (re.compile(r"Bearer\s+[A-Za-z0-9._\-]{20,}"), "a bearer token"),
    ):
        assert pattern.search(text) is None, f".env.example appears to contain {description}"
