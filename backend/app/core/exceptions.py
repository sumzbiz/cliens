"""Typed application exception hierarchy and the JSON error envelope they map to.

Every failure the application can produce is one of these types. Each carries a
stable machine-readable ``code`` that clients may branch on, an HTTP status, and a
human-readable message safe to show a user. The global handlers in ``app.main``
translate them into a single consistent envelope, so no code path can leak a bare
500 or an unstructured stack trace.
"""

from __future__ import annotations

from typing import Any

from fastapi import status


class AppError(Exception):
    """Base class for every expected application failure.

    Attributes:
        code: Stable identifier for the failure, safe for clients to branch on.
            Never renamed without a corresponding frontend change.
        message: Human-readable explanation, safe to display to an end user.
        http_status: The HTTP status the global handler will return.
        details: Structured, non-sensitive context (which field, which upstream).
            Must never contain credentials or raw upstream payloads.
    """

    code: str = "INTERNAL_ERROR"
    http_status: int = status.HTTP_500_INTERNAL_SERVER_ERROR

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details: dict[str, Any] = details or {}

    def to_envelope(self, *, request_id: str | None = None) -> dict[str, Any]:
        """Render the error as the JSON body returned to the client."""
        error: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.details:
            error["details"] = self.details
        if request_id is not None:
            error["request_id"] = request_id
        return {"error": error}


# ---------------------------------------------------------------------------
# Client-side failures (4xx)
# ---------------------------------------------------------------------------
class ValidationError(AppError):
    """Input passed schema validation but violated a business rule.

    Purely structural problems are caught by Pydantic before reaching a service and
    are reported by the RequestValidationError handler instead.
    """

    code = "VALIDATION_ERROR"
    http_status = status.HTTP_422_UNPROCESSABLE_ENTITY


class InvalidGeometryError(ValidationError):
    """Submitted polygon geometry is not usable as a building site.

    Raised for self-intersecting rings, insufficient vertices, out-of-range
    coordinates, or an area outside the supported bounds.
    """

    code = "INVALID_GEOMETRY"


class ResourceNotFoundError(AppError):
    """A referenced entity does not exist."""

    code = "NOT_FOUND"
    http_status = status.HTTP_404_NOT_FOUND


class UnknownMaterialError(ValidationError):
    """A submitted material identifier is not in the catalogue.

    Material IDs are untrusted client input and are always resolved against the
    catalogue before use in scoring.
    """

    code = "UNKNOWN_MATERIAL"


class RateLimitExceededError(AppError):
    """The client exceeded the configured per-IP request rate."""

    code = "RATE_LIMIT_EXCEEDED"
    http_status = status.HTTP_429_TOO_MANY_REQUESTS


# ---------------------------------------------------------------------------
# Server and upstream failures (5xx)
# ---------------------------------------------------------------------------
class ExternalServiceError(AppError):
    """An upstream dependency failed.

    Args:
        service: Which upstream failed, e.g. "earth_engine", "imd", "gemini".
    """

    code = "EXTERNAL_SERVICE_ERROR"
    http_status = status.HTTP_502_BAD_GATEWAY

    def __init__(
        self,
        message: str,
        *,
        service: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, details={**(details or {}), "service": service})
        self.service = service


class ExternalServiceTimeoutError(ExternalServiceError):
    """An upstream dependency did not respond within its timeout."""

    code = "EXTERNAL_SERVICE_TIMEOUT"
    http_status = status.HTTP_504_GATEWAY_TIMEOUT


class ExternalServiceUnconfiguredError(ExternalServiceError):
    """An upstream dependency is missing its credentials.

    Returned instead of degraded or invented data: in a permit-approval context a
    fabricated number is worse than an explicit failure.
    """

    code = "EXTERNAL_SERVICE_UNCONFIGURED"
    http_status = status.HTTP_503_SERVICE_UNAVAILABLE


class ModelUnavailableError(AppError):
    """A required ML artifact could not be loaded.

    Raised at startup when an artifact is missing or was produced by a different
    scikit-learn version, and at request time if inference is attempted anyway.
    """

    code = "MODEL_UNAVAILABLE"
    http_status = status.HTTP_503_SERVICE_UNAVAILABLE


class DatabaseError(AppError):
    """A database operation failed for a reason the caller cannot fix."""

    code = "DATABASE_ERROR"
    http_status = status.HTTP_500_INTERNAL_SERVER_ERROR
