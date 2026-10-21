"""Tests for the WS-01 settings surface (src/config/settings.py).

Every test builds a fresh ``Settings()`` from a cleaned environment so the
results do not depend on the developer's local ``.env`` file.
"""

from __future__ import annotations

import pytest

from src.config.settings import Settings, ensure_dir

# All env vars that influence Settings construction in these tests. .env values
# are loaded into os.environ at import time; deleting them makes os.getenv()
# fall back to the built-in defaults under test.
SETTINGS_ENV_VARS = [
    "APP_ENV",
    "CORS_ORIGINS",
    "DATABASE_URL",
    "GREENHOUSE_BOARDS",
    "LEVER_COMPANIES",
    "JOB_SOURCE_TIMEOUT",
    "JOB_SOURCE_MIN_INTERVAL",
    "EMBEDDING_PROVIDER",
    "EMBEDDING_MODEL",
    "EMBEDDING_DIMENSIONALITY",
    "CHROMA_DIR",
    "MATCH_WEIGHTS",
    "SUBMISSION_POLICY",
    "ALLOWED_DOMAINS",
    "DATA_DIR",
    "EVIDENCE_DIR",
    "RESUME_UPLOAD_DIR",
]


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove settings-relevant env vars so defaults are exercised."""
    for var in SETTINGS_ENV_VARS:
        monkeypatch.delenv(var, raising=False)


def test_defaults_parse_correctly(clean_env: None) -> None:
    settings = Settings()
    assert settings.database_url == "sqlite:///./data/app.db"
    # The development origins: the API, a React dev server on 3000, and the
    # Vite dev server on 5173.
    assert settings.cors_origins == [
        "http://localhost:3000",
        "http://localhost:8000",
        "http://localhost:5173",
    ]
    # Job sources (WS-02)
    assert settings.greenhouse_boards == []
    assert settings.lever_companies == []
    assert settings.job_source_timeout == 15.0
    assert settings.job_source_min_interval == 1.0
    # Matching / embeddings (WS-03); provider default is fastembed (FU-7)
    assert settings.embedding_provider == "fastembed"
    assert settings.embedding_model == "google/embeddinggemma-2@int8"
    assert settings.embedding_dimensionality == 768
    assert settings.chroma_dir == "./data/chroma"
    # Submission policy (WS-06)
    assert settings.submission_policy == "REQUIRE_APPROVAL"
    assert settings.allowed_domains == [
        "greenhouse.io",
        "lever.co",
        "workday.com",
        "ashbyhq.com",
        "smartrecruiters.com",
        "icims.com",
    ]
    # Evidence / data locations (WS-05, WS-06, WS-08)
    assert settings.data_dir == "./data"
    assert settings.evidence_dir == "./data/evidence"
    assert settings.resume_upload_dir == "./data/resumes"


def test_comma_split_lists_ignore_empty_segments(
    clean_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GREENHOUSE_BOARDS", "acme,, globex ,")
    monkeypatch.setenv("LEVER_COMPANIES", ",,")
    monkeypatch.setenv("CORS_ORIGINS", "http://a.test, , http://b.test,")
    monkeypatch.setenv("ALLOWED_DOMAINS", "")
    settings = Settings()
    assert settings.greenhouse_boards == ["acme", "globex"]
    assert settings.lever_companies == []
    assert settings.cors_origins == ["http://a.test", "http://b.test"]
    assert settings.allowed_domains == []


def test_custom_values_parse(clean_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GREENHOUSE_BOARDS", "acme-corp,globex")
    monkeypatch.setenv("LEVER_COMPANIES", "netflix")
    monkeypatch.setenv("JOB_SOURCE_TIMEOUT", "30")
    monkeypatch.setenv("JOB_SOURCE_MIN_INTERVAL", "2.5")
    monkeypatch.setenv("EMBEDDING_MODEL", "text-embedding-004")
    monkeypatch.setenv("EMBEDDING_DIMENSIONALITY", "1536")
    monkeypatch.setenv("CHROMA_DIR", "./state/chroma")
    monkeypatch.setenv("SUBMISSION_POLICY", "PREPARE_ONLY")
    monkeypatch.setenv("ALLOWED_DOMAINS", "greenhouse.io, example.com")
    monkeypatch.setenv("DATA_DIR", "./state")
    monkeypatch.setenv("EVIDENCE_DIR", "./state/evidence")
    monkeypatch.setenv("RESUME_UPLOAD_DIR", "./state/resumes")
    settings = Settings()
    assert settings.greenhouse_boards == ["acme-corp", "globex"]
    assert settings.lever_companies == ["netflix"]
    assert settings.job_source_timeout == 30.0
    assert settings.job_source_min_interval == 2.5
    assert settings.embedding_model == "text-embedding-004"
    assert settings.embedding_dimensionality == 1536
    assert settings.chroma_dir == "./state/chroma"
    assert settings.submission_policy == "PREPARE_ONLY"
    assert settings.allowed_domains == ["greenhouse.io", "example.com"]
    assert settings.data_dir == "./state"
    assert settings.evidence_dir == "./state/evidence"
    assert settings.resume_upload_dir == "./state/resumes"


def test_embedding_provider_gemini_selects_gemini_model_default(
    clean_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EMBEDDING_PROVIDER", "gemini")
    settings = Settings()
    assert settings.embedding_provider == "gemini"
    assert settings.embedding_model == "gemini-embedding-2"


def test_embedding_provider_explicit_model_overrides_provider_default(
    clean_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    for provider, model in (
        ("fastembed", "google/embeddinggemma-2@fp32"),
        ("gemini", "text-embedding-004"),
    ):
        monkeypatch.setenv("EMBEDDING_PROVIDER", provider)
        monkeypatch.setenv("EMBEDDING_MODEL", model)
        settings = Settings()
        assert settings.embedding_model == model


def test_embedding_provider_unknown_value_fails_fast(
    clean_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EMBEDDING_PROVIDER", "openai")
    with pytest.raises(RuntimeError, match="EMBEDDING_PROVIDER"):
        Settings()


def test_ensure_dir_creates_nested_dirs_and_is_idempotent(tmp_path):  # type: ignore[no-untyped-def]
    target = tmp_path / "evidence" / "screenshots"
    result = ensure_dir(target)
    assert result == target
    assert target.is_dir()
    # Calling again with an existing dir must not raise.
    assert ensure_dir(target) == target
    # str input is accepted too.
    assert ensure_dir(str(target)) == target


def test_production_fails_fast_when_cors_unset(
    clean_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    with pytest.raises(RuntimeError, match="CORS_ORIGINS"):
        Settings()


def test_production_fails_fast_when_cors_empty(
    clean_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("CORS_ORIGINS", "   ")
    with pytest.raises(RuntimeError, match="unset or empty"):
        Settings()


def test_production_fails_fast_on_wildcard_cors(
    clean_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("CORS_ORIGINS", "*")
    with pytest.raises(RuntimeError, match="wildcard"):
        Settings()


def test_production_allows_explicit_origins(
    clean_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("CORS_ORIGINS", "https://app.example.com,https://admin.example.com")
    # WS-14: production also needs an identity secret.
    monkeypatch.setenv("AUTH_SECRET", "a" * 48)
    settings = Settings()
    assert settings.cors_origins == [
        "https://app.example.com",
        "https://admin.example.com",
    ]


VALID_WEIGHTS = (
    '{"semantic":0.2,"skill":0.3,"experience":0.2,"seniority":0.1,"location":0.1,"preference":0.1}'
)


def test_match_weights_unset_is_none(clean_env: None) -> None:
    assert Settings().match_weights is None


def test_match_weights_valid_json_parses(clean_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MATCH_WEIGHTS", VALID_WEIGHTS)
    weights = Settings().match_weights
    assert weights == {
        "semantic": 0.2,
        "skill": 0.3,
        "experience": 0.2,
        "seniority": 0.1,
        "location": 0.1,
        "preference": 0.1,
    }


def test_match_weights_invalid_json_fails_fast(
    clean_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MATCH_WEIGHTS", "{not json")
    with pytest.raises(RuntimeError, match="not valid JSON"):
        Settings()


def test_match_weights_non_object_fails_fast(
    clean_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MATCH_WEIGHTS", "[0.2, 0.3]")
    with pytest.raises(RuntimeError, match="JSON object"):
        Settings()


def test_match_weights_bad_sum_fails_fast(clean_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "MATCH_WEIGHTS",
        '{"semantic":0.5,"skill":0.5,"experience":0.2,"seniority":0.1,"location":0.1,"preference":0.1}',
    )
    with pytest.raises(RuntimeError, match="sum"):
        Settings()


def test_match_weights_unknown_component_fails_fast(
    clean_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MATCH_WEIGHTS", '{"charisma":1.0}')
    with pytest.raises(RuntimeError, match="Unknown"):
        Settings()
