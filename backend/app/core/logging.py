"""Structured JSON logging setup and the request correlation-ID context variable.

Every log line carries the correlation ID of the request that produced it, so a
single user request can be traced from the route, through the service, into every
external call it made. The ID is stored in a ``ContextVar`` rather than threaded
through function signatures, which keeps service and client code free of logging
plumbing while still working correctly under asyncio concurrency.

Use ``get_logger(__name__)`` everywhere. ``print`` is banned by ruff's T20 rules.
"""

from __future__ import annotations

import logging
import sys
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token
from typing import Any

import structlog
from structlog.types import EventDict, Processor

from app.core.config import Settings

# Set by the correlation-ID middleware for the lifetime of one request.
_request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)

# The header clients may send to supply their own ID; echoed back on the response.
REQUEST_ID_HEADER = "X-Request-ID"


def new_request_id() -> str:
    """Generate a correlation ID for a request that arrived without one."""
    return uuid.uuid4().hex


def get_request_id() -> str | None:
    """Return the current request's correlation ID, if inside a request."""
    return _request_id_var.get()


def set_request_id(request_id: str) -> Token[str | None]:
    """Bind a correlation ID to the current context.

    Returns the token needed to reset the context variable afterwards.
    """
    return _request_id_var.set(request_id)


def reset_request_id(token: Token[str | None]) -> None:
    """Restore the previous correlation ID, preventing leakage between requests."""
    _request_id_var.reset(token)


@contextmanager
def request_context(request_id: str) -> Iterator[str]:
    """Bind a correlation ID for the duration of a block.

    Used by entry points that are not HTTP requests, such as CLI commands, so their
    logs are traceable in the same way.
    """
    token = set_request_id(request_id)
    try:
        yield request_id
    finally:
        reset_request_id(token)


def _add_request_id(_logger: logging.Logger, _method_name: str, event_dict: EventDict) -> EventDict:
    """structlog processor injecting the correlation ID into every event."""
    request_id = get_request_id()
    if request_id is not None:
        event_dict["request_id"] = request_id
    return event_dict


def configure_logging(settings: Settings) -> None:
    """Configure structlog and the stdlib logging bridge.

    Development renders colourised, human-readable lines; test and production
    render one JSON object per line for ingestion by a log aggregator.

    Safe to call more than once — later calls replace the configuration rather
    than stacking additional handlers.
    """
    shared_processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        # NOT structlog.stdlib.add_logger_name: that processor reads `logger.name`,
        # which only exists on a stdlib logger. This app uses PrintLoggerFactory, so
        # it would raise AttributeError on the first log call. `get_logger` binds the
        # module name as `logger` instead, giving the same field without the
        # stdlib dependency.
        _add_request_id,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.UnicodeDecoder(),
    ]

    renderer: Processor = (
        structlog.dev.ConsoleRenderer(colors=True)
        if settings.environment == "development"
        else structlog.processors.JSONRenderer()
    )

    structlog.configure(
        processors=[
            *shared_processors,
            # format_exc_info must precede the renderer so tracebacks are rendered
            # as a field rather than dropped.
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelNamesMapping()[settings.log_level]
        ),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )

    # Route stdlib loggers (uvicorn, sqlalchemy, httpx) through the same handler so
    # the output stream stays uniformly structured.
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=settings.log_level,
        force=True,
    )
    # uvicorn installs its own handlers; clearing them prevents duplicate lines.
    for noisy in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logging.getLogger(noisy).handlers.clear()
        logging.getLogger(noisy).propagate = True


def get_logger(
    name: str,
    **initial_values: Any,  # noqa: ANN401 — structlog fields are arbitrary by design
) -> structlog.stdlib.BoundLogger:
    """Return a bound structured logger.

    Args:
        name: Logger name, conventionally the calling module's ``__name__``.
        initial_values: Fields bound to every event from this logger.
    """
    # `logger=name` is bound explicitly here rather than added by a processor; see
    # the note in configure_logging.
    logger: structlog.stdlib.BoundLogger = structlog.get_logger(name).bind(
        logger=name, **initial_values
    )
    return logger
