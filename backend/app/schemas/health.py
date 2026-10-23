"""Liveness and readiness response schemas."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from app.schemas.common import SchemaBase


class LivenessResponse(SchemaBase):
    """Confirms the process is running and able to serve requests."""

    status: Literal["ok"] = "ok"


class DependencyStatus(SchemaBase):
    """The state of one dependency the application needs to do useful work."""

    name: str = Field(description="Dependency identifier, e.g. 'database' or 'postgis'.")
    ready: bool = Field(description="Whether this dependency is usable right now.")
    detail: str | None = Field(
        default=None,
        description="Version, or the reason it is not ready. Never contains credentials.",
    )


class ReadinessResponse(SchemaBase):
    """Aggregate readiness across every dependency.

    ``ready`` is false when any required dependency is unavailable; the endpoint
    then returns HTTP 503 so an orchestrator can act on it without parsing the body.
    """

    ready: bool
    dependencies: tuple[DependencyStatus, ...]
