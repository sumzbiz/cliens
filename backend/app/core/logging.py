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
from collections.abc import Callable, Iterator
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

# Google's load balancer stamps every request with this: "TRACE_ID/SPAN_ID;o=FLAG".
CLOUD_TRACE_HEADER = "X-Cloud-Trace-Context"

# The trace ID from CLOUD_TRACE_HEADER, for the lifetime of one request.
_trace_id_var: ContextVar[str | None] = ContextVar("trace_id", default=None)


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


def set_trace_id(header: str | None) -> Token[str | None]:
    """Bind the trace ID parsed from an ``X-Cloud-Trace-Context`` header, if any."""
    trace_id = header.split("/", 1)[0].strip() if header else ""
    return _trace_id_var.set(trace_id or None)


def reset_trace_id(token: Token[str | None]) -> None:
    """Restore the previous trace ID."""
    _trace_id_var.reset(token)


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


def _name_field(_logger: logging.Logger, _method_name: str, event_dict: EventDict) -> EventDict:
    """Emit the module name bound by ``get_logger`` under the conventional ``logger`` key."""
    if "logger_name" in event_dict:
        event_dict["logger"] = event_dict.pop("logger_name")
    return event_dict


def _cloud_logging_fields(project: str) -> Callable[[logging.Logger, str, EventDict], EventDict]:
    """A processor adding the fields Cloud Logging reads from a JSON log line.

    ``severity`` sets the entry's level (otherwise every stdout line is DEFAULT),
    ``message`` is what the log viewer shows as the summary, and the trace field
    groups every line of one request under its Cloud Trace span.
    """

    def add_fields(_logger: logging.Logger, method_name: str, event_dict: EventDict) -> EventDict:
        event_dict["severity"] = str(event_dict.get("level", method_name)).upper()
        event_dict.setdefault("message", event_dict.get("event"))
        trace_id = _trace_id_var.get()
        if trace_id is not None:
            event_dict["logging.googleapis.com/trace"] = f"projects/{project}/traces/{trace_id}"
        return event_dict

    return add_fields


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
        _name_field,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.UnicodeDecoder(),
    ]
    if settings.google_cloud_project:
        shared_processors.append(_cloud_logging_fields(settings.google_cloud_project))

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
    #
    # Passed as initial values, NOT via `.bind()`: binding the lazy proxy builds
    # the real logger immediately, with whatever configuration exists at that
    # moment. Module-level loggers are created at import, before
    # configure_logging runs, so `.bind()` froze every one of them on structlog's
    # default console renderer — production logged plain text without request
    # IDs. Initial values stay lazy until the first log call.
    #
    # The name travels as `logger_name` because `logger` is already a parameter of
    # structlog.get_logger; `_name_field` renames it on output.
    logger: structlog.stdlib.BoundLogger = structlog.get_logger(
        name, logger_name=name, **initial_values
    )
    return logger
