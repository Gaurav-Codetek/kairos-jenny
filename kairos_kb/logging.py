"""Structured logging configuration for Kairos.

Provides formatted log output with correlation IDs so log entries
from the same request can be traced end-to-end.
"""

from __future__ import annotations

import logging
import sys
from contextvars import ContextVar

# Context variable holding the current request's correlation ID.
correlation_id_var: ContextVar[str] = ContextVar("correlation_id", default="-")


class CorrelationFilter(logging.Filter):
    """Inject the current correlation ID into every log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.correlation_id = correlation_id_var.get("-")  # type: ignore[attr-defined]
        return True


def setup_logging(*, level: str = "INFO") -> None:
    """Configure the root logger with structured formatting."""
    fmt = (
        "%(asctime)s | %(levelname)-8s | %(correlation_id)s | %(name)s | %(message)s"
    )
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(fmt))
    handler.addFilter(CorrelationFilter())

    root = logging.getLogger()
    root.setLevel(level.upper())
    # Avoid duplicate handlers on repeated calls (e.g. tests).
    if not root.handlers:
        root.addHandler(handler)

    # Quieten noisy third-party loggers.
    for name in ("httpx", "httpcore", "asyncio", "langchain", "langchain_core", "langsmith"):
        logging.getLogger(name).setLevel(logging.WARNING)
