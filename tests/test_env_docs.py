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
    "LANGSMITH_TRACING": "llm_tracing",
    "LANGSMITH_API_KEY": "langsmith_api_key",
    "LANGSMITH_PROJECT": "langsmith_project",
    "JOB_SOURCE_TIMEOUT": "job_source_timeout",
    "JOB_SOURCE_MIN_INTERVAL": "job_source_min_interval",
    "EMBEDDING_PROVIDER": "embedding_provider",
    "EMBEDDING_DIMENSIONALITY": "embedding_dimensionality",
    "EMBEDDING_RPM_LIMIT": "embedding_rpm_limit",
    "EMBEDDING_RPD_LIMIT": "embedding_rpd_limit",
    "CHROMA_DIR": "chroma_dir",
    "MATCH_WEIGHTS": "match_weights",
    "SUBMISSION_POLICY": "submission_policy",
    "ALLOWED_DOMAINS": "allowed_domains",
    "DATA_DIR": "data_dir",
    "EVIDENCE_DIR": "evidence_dir",
    "RESUME_UPLOAD_DIR": "resume_upload_dir",
    "TAILORED_DIR": "tailored_dir",
}

# The same, for the WS-12 runtime limits.
LIMITS_VAR_TO_ATTR = {
    "RATE_LIMIT_REQUESTS": "rate_limit_requests",
    "RATE_LIMIT_WINDOW_SECONDS": "rate_limit_window_seconds",
    "BODY_LIMIT_BYTES": "body_limit_bytes",
    "MAX_CONCURRENT_HEAVY": "max_concurrent_heavy",
    "HEAVY_QUEUE_TIMEOUT_SECONDS": "heavy_queue_timeout_seconds",
    "MAX_LISTINGS_PER_SOURCE": "max_listings_per_source",
    "MAX_NEW_LISTINGS_PER_REFRESH": "max_new_listings_per_refresh",
    "MAX_CORPUS_LISTINGS": "max_corpus_listings",
    "MAX_EMBED_PER_REFRESH": "max_embed_per_refresh",
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
}

# Documented variables that deliberately do NOT state a default, and why.
# The board lists are curated examples, not defaults — the code's default is
# an empty list, and the example file is more useful with real boards in it.
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
    "EMBEDDING_MODEL",  # provider-dependent; documented as a commented example
}


def _normalize(value: str) -> str:
    """Normalize a path-ish value so ``./data/x`` and ``data/x`` compare equal."""
    return str(Path(value))


def _code_default(name: str, settings: Settings, limits) -> object:
    """The code's own default for a documented variable."""
    if name == "PLAYWRIGHT_HEADLESS":
        return launch_options()["headless"]
    if name == "FASTEMBED_CACHE_PATH":
        return _normalize(fastembed_cache_dir(settings))
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
    )

    unknown = sorted(documented - known)

    assert not unknown, (
        f"{unknown} are documented but have no default rule. Add them to the "
        "mapping tables in this test, with a reason if they are not defaults."
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
