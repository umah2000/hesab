"""Structured logging. Never log secrets, card data or PINs."""

from __future__ import annotations

import logging

import structlog


def configure_logging(level: str, *, json_output: bool) -> None:
    logging.basicConfig(format="%(message)s", level=level.upper())
    renderer = (
        structlog.processors.JSONRenderer() if json_output else structlog.dev.ConsoleRenderer()
    )
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelName(level.upper())),
    )
