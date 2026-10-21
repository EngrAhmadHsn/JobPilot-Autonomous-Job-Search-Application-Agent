from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

from src.matching.weights import validate_weights

BASE_DIR = Path(__file__).resolve().parents[2]
load_dotenv(BASE_DIR / ".env")

# The development origins: the API itself, a React dev server on 3000, and
# the Vite dev server on 5173. Production never uses this default — a
# production deployment must declare its origins explicitly (the check in
# ``Settings._validate_production_cors`` refuses to start without them).
_DEFAULT_CORS_ORIGINS = "http://localhost:3000,http://localhost:8000,http://localhost:5173"
_DEFAULT_ALLOWED_DOMAINS = (
    "greenhouse.io,lever.co,workday.com,ashbyhq.com,smartrecruiters.com,icims.com"
)


class Settings:
    def __init__(self) -> None:
        self.app_name = os.getenv("APP_NAME", "agentic-job-applier")
        self.app_env = os.getenv("APP_ENV", "development")
        self.app_debug = os.getenv("APP_DEBUG", "false").lower() == "true"
        self.log_level = os.getenv("LOG_LEVEL", "INFO")
        # All runtime state (SQLite dev DB, evidence, uploads, vector store)
        # lives under the gitignored data/ tree by default.
        self.database_url = os.getenv("DATABASE_URL", "sqlite:///./data/app.db")
        self._raw_cors_origins = os.getenv("CORS_ORIGINS")
        raw_origins = (
            self._raw_cors_origins if self._raw_cors_origins is not None else _DEFAULT_CORS_ORIGINS
        )
        self.cors_origins = [origin.strip() for origin in raw_origins.split(",") if origin.strip()]

        # LLM "brain" called from LangGraph nodes (never logged)
        self.llm_provider = os.getenv("LLM_PROVIDER", "")
        self.llm_api_key = os.getenv("LLM_API_KEY", "")
        self.llm_model = os.getenv("LLM_MODEL", "")
        self.llm_base_url = os.getenv("LLM_BASE_URL", "") or None
        self.llm_temperature = float(os.getenv("LLM_TEMPERATURE", "0.2"))
        # LLM resilience (WS-10). Three knobs decide how a provider failure is
        # absorbed: how long one call may take, how many calls per minute are
        # allowed, and how many times a retryable failure is retried.
        # LLM_MAX_RETRIES counts the retries AFTER the first attempt, so the
        # default of 2 means three attempts in total.
        self.llm_timeout = float(os.getenv("LLM_TIMEOUT", "60"))
        self.llm_max_rpm = int(os.getenv("LLM_MAX_RPM", "10"))
        self.llm_max_retries = int(os.getenv("LLM_MAX_RETRIES", "2"))
        # A timeout of zero would hang a call forever instead of bounding it,
        # and an RPM of zero would mean "never call the provider". Both are
        # typos, not intentions, so they fail loudly at startup rather than
        # silently at the first call.
        if self.llm_timeout <= 0:
            raise RuntimeError(
                f"LLM_TIMEOUT must be a positive number of seconds, got "
                f"{self.llm_timeout!r}. Refusing to start."
            )
        if self.llm_max_rpm < 1:
            raise RuntimeError(
                f"LLM_MAX_RPM must be at least 1 call per minute, got "
                f"{self.llm_max_rpm!r}. Refusing to start."
            )
        if self.llm_max_retries < 0:
            raise RuntimeError(
                f"LLM_MAX_RETRIES must be 0 or more, got {self.llm_max_retries!r}. "
                "Refusing to start."
            )

        # LangSmith tracing for LangGraph runs (optional)
        self.llm_tracing = os.getenv("LANGSMITH_TRACING", "false").lower() == "true"
        self.langsmith_api_key = os.getenv("LANGSMITH_API_KEY", "")
        self.langsmith_project = os.getenv("LANGSMITH_PROJECT", "agentic-job-applier")

        # Job sources (WS-02)
        self.greenhouse_boards = [
            b.strip() for b in os.getenv("GREENHOUSE_BOARDS", "").split(",") if b.strip()
        ]
        self.lever_companies = [
            c.strip() for c in os.getenv("LEVER_COMPANIES", "").split(",") if c.strip()
        ]
        self.ashby_orgs = [o.strip() for o in os.getenv("ASHBY_ORGS", "").split(",") if o.strip()]
        self.job_source_timeout = float(os.getenv("JOB_SOURCE_TIMEOUT", "15"))
        self.job_source_min_interval = float(
            os.getenv("JOB_SOURCE_MIN_INTERVAL", "1.0")
        )  # seconds/host

        # Matching / embeddings (WS-03)
        # Embedding provider (FU-7): "fastembed" runs EmbeddingGemma-2 locally,
        # in-process (no API, no quota); "gemini" keeps the Gemini embedding
        # API selectable for A/B and fallback (free-tier RPD 20 x 100-text
        # batches ~= 2,000 texts/day). Unknown values fail fast: a silent
        # provider mismatch would poison every cache key and vector space.
        self.embedding_provider = os.getenv("EMBEDDING_PROVIDER", "fastembed").strip().lower()
        if self.embedding_provider not in ("fastembed", "gemini"):
            raise RuntimeError(
                f"EMBEDDING_PROVIDER must be 'fastembed' or 'gemini', got "
                f"{self.embedding_provider!r}. Refusing to start."
            )
        # The @int8 suffix is identity, not decoration: it flows into every
        # cache key and the Chroma collection metadata, so a future fp32/q4
        # switch is structurally forced into a clean re-embed instead of
        # silently mixing embedding spaces.
        self.embedding_model = os.getenv("EMBEDDING_MODEL", "") or (
            "google/embeddinggemma-2@int8"
            if self.embedding_provider == "fastembed"
            else "gemini-embedding-2"
        )
        self.embedding_dimensionality = int(os.getenv("EMBEDDING_DIMENSIONALITY", "768"))
        # Free-tier Gemini embedding quota (AI Studio dashboard, 2026-10-11):
        # RPM 5, RPD 20. Defaults match the live limits; overridable for other
        # plans or providers (FU-4 budget/pacing).
        self.embedding_rpm_limit = int(os.getenv("EMBEDDING_RPM_LIMIT", "5"))
        self.embedding_rpd_limit = int(os.getenv("EMBEDDING_RPD_LIMIT", "20"))
        self.chroma_dir = os.getenv("CHROMA_DIR", "./data/chroma")
        self.match_weights = self._parse_match_weights(os.getenv("MATCH_WEIGHTS"))

        # Submission policy (WS-06). An unknown value is a configuration
        # error, not a silent fallback: the policy decides whether an
        # application may be executed at all, so a typo must fail loudly.
        from src.security.policy import SubmissionPolicy

        self.submission_policy = os.getenv("SUBMISSION_POLICY", "REQUIRE_APPROVAL").strip().upper()
        valid_policies = {policy.value for policy in SubmissionPolicy}
        if self.submission_policy not in valid_policies:
            raise RuntimeError(
                f"SUBMISSION_POLICY must be one of {', '.join(sorted(valid_policies))}, got "
                f"{self.submission_policy!r}. Refusing to start."
            )
        self.allowed_domains = [
            d.strip()
            for d in os.getenv("ALLOWED_DOMAINS", _DEFAULT_ALLOWED_DOMAINS).split(",")
            if d.strip()
        ]

        # Evidence / data locations (WS-05, WS-06, WS-08)
        self.data_dir = os.getenv("DATA_DIR", "./data")
        self.evidence_dir = os.getenv("EVIDENCE_DIR", "./data/evidence")
        self.resume_upload_dir = os.getenv("RESUME_UPLOAD_DIR", "./data/resumes")
        # Rendered tailored resumes (WS-05); defaults under the data dir.
        self.tailored_dir = os.getenv("TAILORED_DIR", "") or str(Path(self.data_dir) / "tailored")

        # -- Identity (WS-14 · A1) -----------------------------------------
        #
        # The API has no anonymous access any more: a caller is a
        # principal, and the principal is what the owner filter is keyed
        # on. These knobs decide how that identity is established and how
        # long it lives.
        #
        # ``auth_secret`` signs the password-reset and e-mail-verification
        # tokens. It is **not** a session secret — the sessions are
        # server-side rows, and revoking one is a DELETE — but a leaked
        # secret would let an attacker mint a reset token for any account.
        # It is therefore required in production and must be long.
        self.auth_secret = os.getenv("AUTH_SECRET", "")
        # The cookie that carries the session for the browser transport.
        self.auth_session_cookie_name = (
            os.getenv("AUTH_SESSION_COOKIE_NAME", "aja_session").strip() or "aja_session"
        )
        # The double-submit CSRF cookie. It is deliberately **not**
        # HttpOnly: the console's JavaScript has to read it to echo it in
        # the ``X-CSRF-Token`` header. It is not a credential — it grants
        # nothing without the session cookie.
        self.auth_csrf_cookie_name = os.getenv("AUTH_CSRF_COOKIE_NAME", "aja_csrf").strip() or (
            "aja_csrf"
        )
        # ``Secure`` on the session cookie. It is a **tri-state**: unset
        # means "follow the environment" — off in development, because the
        # development server is plain HTTP on localhost, and **on** in
        # production, without exception. An explicit "false" in production
        # is refused at startup rather than quietly honoured.
        self.auth_cookie_secure = os.getenv("AUTH_COOKIE_SECURE", "").strip().lower()
        # How long a session lives before it is refused.
        self.auth_session_ttl_seconds = int(os.getenv("AUTH_SESSION_TTL_SECONDS", "86400"))
        if self.auth_session_ttl_seconds < 60:
            raise RuntimeError(
                f"AUTH_SESSION_TTL_SECONDS must be at least 60 seconds, got "
                f"{self.auth_session_ttl_seconds!r}. Refusing to start."
            )
        # Whether a login requires a **verified** e-mail address. Off by
        # default: this deployment has no SMTP provider, so a verified
        # account could never be created and the API would be unusable.
        # A production deployment that sends mail turns it on.
        self.auth_require_verified = os.getenv("AUTH_REQUIRE_VERIFIED", "false").lower() == "true"
        # Whether the first registered account may claim the rows that
        # pre-date the identity work (the ``legacy`` owner). On by default:
        # that is how an operator's existing corpus reaches the operator's
        # own account instead of being orphaned. Phase D purges it instead
        # when the answer is "nobody".
        self.auth_claim_legacy = os.getenv("AUTH_CLAIM_LEGACY", "true").lower() == "true"

        self._validate_production_cors()
        self._validate_production_identity()

    @staticmethod
    def _parse_match_weights(raw: str | None) -> dict[str, float] | None:
        """Parse MATCH_WEIGHTS JSON, failing fast on invalid configuration."""
        if raw is None or not raw.strip():
            return None
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"MATCH_WEIGHTS is not valid JSON: {exc}") from exc
        if not isinstance(parsed, dict):
            # RuntimeError, not TypeError: this is environment misconfiguration,
            # consistent with the other fail-fast config checks in this module.
            raise RuntimeError("MATCH_WEIGHTS must be a JSON object of component weights")  # noqa: TRY004
        try:
            return validate_weights({str(key): value for key, value in parsed.items()})
        except ValueError as exc:
            raise RuntimeError(f"Invalid MATCH_WEIGHTS: {exc}") from exc

    def cookie_secure(self) -> bool:
        """Whether the session cookie carries the ``Secure`` attribute.

        A method rather than a plain attribute, because the answer
        depends on the environment: unset means "off in development, on
        in production", and the production rule is checked at startup.
        """
        if self.auth_cookie_secure in ("1", "true", "yes"):
            return True
        if self.auth_cookie_secure in ("0", "false", "no"):
            return False
        return self.app_env == "production"

    def _validate_production_cors(self) -> None:
        """Fail fast on unsafe CORS configuration when APP_ENV=production.

        A production app must declare the exact origins allowed to call it:
        an unset CORS_ORIGINS silently falls back to localhost dev origins,
        and a wildcard origin defeats credentialed-CORS protections.
        """
        if self.app_env != "production":
            return
        if self._raw_cors_origins is None or not self._raw_cors_origins.strip():
            raise RuntimeError(
                "APP_ENV=production requires an explicit CORS_ORIGINS setting "
                "(comma-separated list of allowed origins); it is unset or empty. "
                "Refusing to start."
            )
        if "*" in self.cors_origins:
            raise RuntimeError(
                "APP_ENV=production forbids wildcard CORS origins "
                "(CORS_ORIGINS contains '*'). List explicit origins instead. "
                "Refusing to start."
            )

    def _validate_production_identity(self) -> None:
        """Fail fast on an unsafe identity configuration in production.

        The identity settings decide whether a session can be forged, so a
        production deployment that is missing them must not start: an
        application that runs with a guessable session secret is worse than
        an application that refuses to run, because the first looks healthy.
        """
        if self.app_env != "production":
            return
        if not self.auth_secret:
            raise RuntimeError(
                "APP_ENV=production requires an explicit AUTH_SECRET setting; it is "
                "unset or empty. Refusing to start."
            )
        if len(self.auth_secret) < 32:
            raise RuntimeError(
                "AUTH_SECRET must be at least 32 characters long in production, got "
                f"{len(self.auth_secret)}. Refusing to start."
            )
        if self.auth_cookie_secure in ("0", "false", "no"):
            raise RuntimeError(
                "APP_ENV=production requires a Secure session cookie "
                "(AUTH_COOKIE_SECURE must not be false). Refusing to start."
            )


def ensure_dir(path: str | Path) -> Path:
    """Create ``path`` (and parents) if missing and return it as a Path.

    Data directories (``data_dir``, ``evidence_dir``, ``resume_upload_dir``,
    ``chroma_dir``) are derived lazily: the owning module calls this helper at
    the point of use, never at import time.
    """
    directory = Path(path)
    directory.mkdir(parents=True, exist_ok=True)
    return directory


@lru_cache
def get_settings() -> Settings:
    return Settings()
