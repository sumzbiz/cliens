"""Site persistence endpoints.

Saving is a deliberate side effect, kept out of ``/score`` and ``/score/area`` on
purpose: those stay a pure computation over whatever the client sends, exactly as
their own docstrings promise, and persisting what the user drew is a separate
action with its own failure mode (a database write, not a scoring input problem).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, status

from app.routes.dependencies import SiteServiceDep
from app.schemas.common import ErrorResponse
from app.schemas.sites import CreateSiteRequest, SiteResponse

router = APIRouter(prefix="/sites", tags=["sites"])

SITE_ERRORS: dict[int | str, dict[str, Any]] = {
    status.HTTP_422_UNPROCESSABLE_ENTITY: {
        "model": ErrorResponse,
        "description": "The outline is not a usable polygon, or not a plausible site size.",
    },
}


@router.post(
    "",
    response_model=SiteResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Save a drawn site boundary",
    responses=SITE_ERRORS,
)
async def create_site(request: CreateSiteRequest, service: SiteServiceDep) -> SiteResponse:
    """Persist a drawn polygon and return its authoritative area."""
    record = await service.save(request.geometry, request.label)
    return SiteResponse(
        id=record.id,
        area_sq_ft=record.area_sq_ft,
        centroid_latitude=record.centroid_latitude,
        centroid_longitude=record.centroid_longitude,
        label=record.label,
        created_at=record.created_at,
    )
