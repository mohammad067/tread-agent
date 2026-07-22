"""Structured logging via structlog (frozen requirement: structured only, never ``print``).

One configuration entry point; every log line is a JSON event with a ``run_id`` correlation key
where available. The renderer is JSON so logs are machine-parsable end to end (cross-cutting §G2).
"""

from __future__ import annotations

import logging
from typing import Any

import structlog


def configure_logging(level: str = "INFO") -> None:
    """Configure structlog + stdlib logging for JSON structured output. Idempotent."""
    logging.basicConfig(format="%(message)s", level=getattr(logging, level.upper(), logging.INFO))
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.EventRenamer("event"),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level.upper(), logging.INFO)
        ),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str = "market_state_engine", **initial: Any) -> Any:
    """Return a bound structlog logger with optional initial context (e.g. ``run_id``)."""
    return structlog.get_logger(name).bind(**initial)
