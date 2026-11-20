"""FastAPI application factory: middleware, routers, exception handlers, lifespan.

This is the composition root. Every cross-cutting concern is wired here exactly
once — correlation IDs, structured logging, CORS, rate limiting, and the exception
handlers that guarantee a consistent error envelope. No route below this file
formats an error response itself.
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager

from fastapi import FastAPI, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from app.core.config import Settings, get_settings, load_settings_or_exit
from app.core.constants import validate_constants
from app.core.database import dispose_database, init_database
from app.core.exceptions import AppError, RateLimitExceededError
from app.core.logging import (
    REQUEST_ID_HEADER,
    configure_logging,
    get_logger,
    get_request_id,
    new_request_id,
    reset_request_id,
    set_request_id,
)
from app.core.rate_limit import FixedWindowRateLimiter
from app.external.http import close_client as close_http_client
from app.ml.registry import try_load_registry
from app.routes import basemap, health, materials, reports, scoring, sites, voice
from app.schemas.common import ErrorResponse

logger = get_logger(__name__)

API_PREFIX = "/api"

# Path prefixes exempt from rate limiting.
#
# Map tiles belong here and their absence was a real bug: one screen of a slippy
# map is twenty to forty tile requests, so a map view exhausted a 60-per-minute
# budget in seconds. Worse, the budget is shared, so the exhausted limiter then
# rejected `/score/districts` too and the whole page fell back to an error state
# with no map at all. A tile is a cached static image, not an expensive call, so
# throttling it protects nothing.
RATE_LIMIT_EXEMPT_PREFIXES: tuple[str, ...] = (f"{API_PREFIX}/tiles/",)

# Paths exempt from rate limiting. Health probes are polled continuously by
# orchestrators and must never be throttled; the docs are static.
RATE_LIMIT_EXEMPT_PATHS: frozenset[str] = frozenset(
    {
        f"{API_PREFIX}/health/live",
        f"{API_PREFIX}/health/ready",
        "/docs",
        "/redoc",
        "/openapi.json",
    }
)


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    """Bind a correlation ID to every request and log its lifecycle.

    The ID comes from the client's ``X-Request-ID`` header when present, so a trace
    can span the frontend and the backend, and is generated otherwise. It is echoed
    on the response and attached to every log line emitted while handling the
    request, including those from services and external clients.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        """Handle one request inside a correlation-ID context."""
        incoming = request.headers.get(REQUEST_ID_HEADER)
        request_id = incoming if incoming else new_request_id()
        token = set_request_id(request_id)
        started = time.perf_counter()

        logger.info(
            "request_started",
            method=request.method,
            path=request.url.path,
            client=request.client.host if request.client else None,
        )

        try:
            response = await call_next(request)
        except Exception:
            # The exception handlers below turn this into a response; logging here
            # keeps the timing and correlation ID attached to the failure.
            logger.exception(
                "request_failed",
                method=request.method,
                path=request.url.path,
                duration_ms=round((time.perf_counter() - started) * 1000, 2),
            )
            raise
        else:
            response.headers[REQUEST_ID_HEADER] = request_id
            logger.info(
                "request_completed",
                method=request.method,
                path=request.url.path,
                status_code=response.status_code,
                duration_ms=round((time.perf_counter() - started) * 1000, 2),
            )
            return response
        finally:
            reset_request_id(token)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Enforce the per-IP request budget on public endpoints.

    The rejection response is built here rather than raised as an exception:
    Starlette's exception handlers live inside the middleware stack, so an
    exception raised from middleware would bypass them and become a bare 500.
    """

    def __init__(self, app: object, *, limiter: FixedWindowRateLimiter) -> None:
        """Wrap ``app``, enforcing ``limiter``."""
        super().__init__(app)  # type: ignore[arg-type]  # Starlette types this as ASGIApp
        self._limiter = limiter

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        """Check the budget, then either forward the request or reject it."""
        path = request.url.path
        if path in RATE_LIMIT_EXEMPT_PATHS or path.startswith(RATE_LIMIT_EXEMPT_PREFIXES):
            return await call_next(request)

        # Note: this trusts the socket peer address. Behind a reverse proxy the
        # deployment must strip and set X-Forwarded-For, and uvicorn must run with
        # --proxy-headers, or every client resolves to the proxy's IP.
        client_key = request.client.host if request.client else "unknown"
        decision = self._limiter.check(client_key)

        if not decision.allowed:
            error = RateLimitExceededError(
                "Too many requests. Please wait before trying again.",
                details={
                    "limit": decision.limit,
                    "retry_after_seconds": decision.retry_after_seconds,
                },
            )
            logger.warning("rate_limit_exceeded", client=client_key, limit=decision.limit)
            rejection = JSONResponse(
                status_code=error.http_status,
                content=error.to_envelope(request_id=get_request_id()),
            )
            rejection.headers["Retry-After"] = str(decision.retry_after_seconds)
            return rejection

        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(decision.limit)
        response.headers["X-RateLimit-Remaining"] = str(decision.remaining)
        return response


def _error_response(error: AppError) -> JSONResponse:
    """Render an application error as the standard envelope."""
    return JSONResponse(
        status_code=error.http_status,
        content=error.to_envelope(request_id=get_request_id()),
    )


def _register_exception_handlers(app: FastAPI) -> None:
    """Install handlers so no failure escapes as an unstructured 500.

    Handlers are typed against ``Exception`` because that is the signature Starlette
    requires; each narrows to its own type immediately.
    """

    async def handle_app_error(_request: Request, exc: Exception) -> Response:
        """Expected application failures, already carrying a code and status."""
        if not isinstance(exc, AppError):  # pragma: no cover — registration guarantees this
            raise exc
        logger.warning(
            "application_error",
            code=exc.code,
            status_code=exc.http_status,
            message=exc.message,
            details=exc.details,
        )
        return _error_response(exc)

    async def handle_validation_error(_request: Request, exc: Exception) -> Response:
        """Pydantic rejected the request body, query or path parameters."""
        if not isinstance(exc, RequestValidationError):  # pragma: no cover
            raise exc
        # `errors()` echoes the offending input, which here can be a large polygon.
        # Only the location and the reason are returned.
        problems = [
            {
                "field": ".".join(str(part) for part in error["loc"]),
                "reason": error["msg"],
            }
            for error in exc.errors()
        ]
        logger.info("request_validation_failed", problems=problems)
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "The request did not match the expected shape.",
                    "details": {"problems": problems},
                    "request_id": get_request_id(),
                }
            },
        )

    async def handle_http_exception(_request: Request, exc: Exception) -> Response:
        """Starlette's own errors, most often a 404 for an unrouted path."""
        if not isinstance(exc, StarletteHTTPException):  # pragma: no cover
            raise exc
        codes = {
            status.HTTP_404_NOT_FOUND: "NOT_FOUND",
            status.HTTP_405_METHOD_NOT_ALLOWED: "METHOD_NOT_ALLOWED",
        }
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "code": codes.get(exc.status_code, "HTTP_ERROR"),
                    "message": str(exc.detail),
                    "request_id": get_request_id(),
                }
            },
        )

    async def handle_unexpected_error(_request: Request, exc: Exception) -> Response:
        """Anything not anticipated above.

        The message is deliberately generic: an unexpected exception may carry
        internal detail, so only the correlation ID is returned and the full
        traceback goes to the logs.
        """
        logger.exception("unhandled_exception", error_type=type(exc).__name__)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "error": {
                    "code": "INTERNAL_ERROR",
                    "message": (
                        "An unexpected error occurred. " "Quote the request ID when reporting it."
                    ),
                    "request_id": get_request_id(),
                }
            },
        )

    app.add_exception_handler(AppError, handle_app_error)
    app.add_exception_handler(RequestValidationError, handle_validation_error)
    app.add_exception_handler(StarletteHTTPException, handle_http_exception)
    app.add_exception_handler(Exception, handle_unexpected_error)


def _build_lifespan(
    settings: Settings,
) -> Callable[[FastAPI], AbstractAsyncContextManager[None]]:
    """Create the lifespan handler bound to a specific configuration."""

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        """Start and stop process-wide resources.

        Constants are validated first: a weight table that stopped summing to 1.0
        would bias every score, and failing at startup beats serving subtly wrong
        numbers.
        """
        validate_constants()
        init_database(settings)
        # Models load once, here. Absent artifacts degrade the app rather than
        # stopping it: site and material endpoints keep working, readiness reports
        # the gap, and scoring fails explicitly with MODEL_UNAVAILABLE.
        try_load_registry()
        logger.info(
            "application_started",
            environment=settings.environment,
            gemini_configured=settings.gemini_configured,
            earth_engine_configured=settings.earth_engine_configured,
            # Key count rather than the keys themselves: enough to tell "not
            # configured" from "one key, no failover" from "both", without ever
            # putting credential material in a log line.
            voice_keys=len(settings.sarvam_keys),
            voice_speaker=settings.sarvam_tts_speaker,
        )
        try:
            yield
        finally:
            await close_http_client()
            await dispose_database()
            logger.info("application_stopped")

    return lifespan


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the ASGI application.

    Args:
        settings: Configuration to use. Tests pass their own; production reads the
            environment.
    """
    resolved = settings if settings is not None else load_settings_or_exit()
    configure_logging(resolved)

    app = FastAPI(
        title="Building Quality Score API",
        version="0.1.0",
        summary="Scores how well building materials suit a district's measured climate.",
        lifespan=_build_lifespan(resolved),
        # The generated OpenAPI spec is the source of the frontend's types, so the
        # error envelope is declared globally rather than repeated per route.
        responses={"default": {"model": ErrorResponse, "description": "Error"}},
    )

    limiter = FixedWindowRateLimiter(
        max_requests=resolved.rate_limit_requests,
        window_seconds=resolved.rate_limit_window_seconds,
    )
    # Exposed so tests can reset counters between cases.
    app.state.rate_limiter = limiter

    # Starlette runs middleware in reverse registration order, so the last one
    # added is outermost. Correlation IDs must therefore be added last: the rate
    # limiter's rejection log needs the ID already bound.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(resolved.cors_origins),  # exact origins; config rejects "*" in prod
        allow_credentials=False,  # no cookies or auth headers in v1
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", REQUEST_ID_HEADER],
        expose_headers=[
            REQUEST_ID_HEADER,
            "X-RateLimit-Limit",
            "X-RateLimit-Remaining",
        ],
    )
    app.add_middleware(RateLimitMiddleware, limiter=limiter)
    app.add_middleware(CorrelationIdMiddleware)

    # Dependencies resolve settings through `get_settings`, which reads the
    # environment and caches. Without this override an app built with explicit
    # settings would still hand its services the ambient ones — so a test could
    # believe it had configured nothing while a client reached a real upstream.
    app.dependency_overrides[get_settings] = lambda: resolved

    _register_exception_handlers(app)

    app.include_router(health.router, prefix=API_PREFIX)
    app.include_router(materials.router, prefix=API_PREFIX)
    app.include_router(scoring.router, prefix=API_PREFIX)
    app.include_router(reports.router, prefix=API_PREFIX)
    app.include_router(basemap.router, prefix=API_PREFIX)
    app.include_router(voice.router, prefix=API_PREFIX)
    app.include_router(sites.router, prefix=API_PREFIX)

    return app


app = create_app()
