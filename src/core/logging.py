from __future__ import annotations

import logging

from src.config.settings import get_settings


def configure_logging() -> logging.Logger:
    settings = get_settings()
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    return logging.getLogger("agentic_job_applier")
