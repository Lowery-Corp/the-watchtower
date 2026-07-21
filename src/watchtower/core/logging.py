"""Structured application logging."""

import logging
from typing import cast

import structlog


def configure_logging() -> None:
    """Configure JSON logging for application-owned events."""

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.BoundLogger:
    """Return a logger bound to a stable component name."""

    return cast(structlog.BoundLogger, structlog.get_logger().bind(logger=name))
