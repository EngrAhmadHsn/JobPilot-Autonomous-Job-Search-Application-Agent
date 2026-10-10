from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parents[2]
load_dotenv(BASE_DIR / ".env")

_DEFAULT_CORS_ORIGINS = "http://localhost:3000,http://localhost:8000"
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
            self._raw_cors_origins
            if self._raw_cors_origins is not None
            else _DEFAULT_CORS_ORIGINS
        )
        self.cors_origins = [origin.strip() for origin in raw_origins.split(",") if origin.strip()]

        # LLM "brain" called from LangGraph nodes (never logged)
        self.llm_provider = os.getenv("LLM_PROVIDER", "")
        self.llm_api_key = os.getenv("LLM_API_KEY", "")
        self.llm_model = os.getenv("LLM_MODEL", "")
        self.llm_base_url = os.getenv("LLM_BASE_URL", "") or None
        self.llm_temperature = float(os.getenv("LLM_TEMPERATURE", "0.2"))

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
        self.job_source_timeout = float(os.getenv("JOB_SOURCE_TIMEOUT", "15"))
        self.job_source_min_interval = float(
            os.getenv("JOB_SOURCE_MIN_INTERVAL", "1.0")
        )  # seconds/host

        # Matching / embeddings (WS-03)
        self.embedding_model = os.getenv("EMBEDDING_MODEL", "gemini-embedding-2")
        self.embedding_dimensionality = int(os.getenv("EMBEDDING_DIMENSIONALITY", "768"))
        self.chroma_dir = os.getenv("CHROMA_DIR", "./data/chroma")

        # Submission policy (WS-06)
        self.submission_policy = os.getenv("SUBMISSION_POLICY", "REQUIRE_APPROVAL")
        self.allowed_domains = [
            d.strip()
            for d in os.getenv("ALLOWED_DOMAINS", _DEFAULT_ALLOWED_DOMAINS).split(",")
            if d.strip()
        ]

        # Evidence / data locations (WS-05, WS-06, WS-08)
        self.data_dir = os.getenv("DATA_DIR", "./data")
        self.evidence_dir = os.getenv("EVIDENCE_DIR", "./data/evidence")
        self.resume_upload_dir = os.getenv("RESUME_UPLOAD_DIR", "./data/resumes")

        self._validate_production_cors()

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
