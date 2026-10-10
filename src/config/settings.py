from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parents[2]
load_dotenv(BASE_DIR / ".env")


class Settings:
    def __init__(self) -> None:
        self.app_name = os.getenv("APP_NAME", "agentic-job-applier")
        self.app_env = os.getenv("APP_ENV", "development")
        self.app_debug = os.getenv("APP_DEBUG", "false").lower() == "true"
        self.log_level = os.getenv("LOG_LEVEL", "INFO")
        self.database_url = os.getenv("DATABASE_URL", "sqlite:///./app.db")
        raw_origins = os.getenv("CORS_ORIGINS", "http://localhost:3000,http://localhost:8000")
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


@lru_cache
def get_settings() -> Settings:
    return Settings()
