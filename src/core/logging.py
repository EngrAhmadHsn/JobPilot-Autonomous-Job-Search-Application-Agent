from __future__ import annotations

import logging

from src.config.settings import get_settings
from src.security.redaction import mask_pii


class PiiMaskingFilter(logging.Filter):
    """Mask emails and phone numbers in every log record (SEC-12).

    Defense in depth: a call site that logs a raw email address still cannot
    write it to the log. The filter is attached to the *handlers* (not to the
    logger), because a logger-level filter does not run for records that
    propagate up from a child logger.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = mask_pii(record.msg)
        record.args = self._mask_args(record.args)
        return True

    @classmethod
    def _mask_args(cls, args: object) -> object:
        """Mask the string values inside a record's arguments."""
        if isinstance(args, dict):
            return {key: cls._mask(value) for key, value in args.items()}
        if isinstance(args, tuple):
            # ``logger.info("%(x)s", {"x": ...})`` reaches the record as a
            # one-element tuple holding the mapping.
            if len(args) == 1 and isinstance(args[0], dict):
                return (cls._mask_args(args[0]),)
            return tuple(cls._mask(value) for value in args)
        return args

    @staticmethod
    def _mask(value: object) -> object:
        """Mask a string value; leave every other type untouched."""
        return mask_pii(value) if isinstance(value, str) else value


def configure_logging() -> logging.Logger:
    settings = get_settings()
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    root = logging.getLogger()
    pii_filter = PiiMaskingFilter()
    for handler in root.handlers:
        if pii_filter not in handler.filters:
            handler.addFilter(pii_filter)
    return logging.getLogger("agentic_job_applier")
