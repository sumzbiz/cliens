"""Material catalogue endpoints."""

from __future__ import annotations

from fastapi import APIRouter, status

from app.routes.dependencies import MaterialServiceDep
from app.schemas.common import ErrorResponse
from app.schemas.materials import MaterialCatalogueResponse, MaterialSelection, ResolvedMaterial

router = APIRouter(prefix="/materials", tags=["materials"])


@router.get(
    "",
    response_model=MaterialCatalogueResponse,
    summary="Material catalogue, grouped by building component",
)
async def get_catalogue(service: MaterialServiceDep) -> MaterialCatalogueResponse:
    """Return every available material with its resistance ratings and sources.

    Drives the component pickers in the UI. Each entry carries the published basis
    its resistance values were derived from.
    """
    return await service.get_catalogue()


@router.post(
    "/resolve",
    response_model=tuple[ResolvedMaterial, ...],
    summary="Validate a per-component material selection",
    responses={
        status.HTTP_422_UNPROCESSABLE_ENTITY: {
            "model": ErrorResponse,
            "description": "A code is unknown, or is not valid for the component chosen.",
        }
    },
)
async def resolve_selection(
    selection: MaterialSelection, service: MaterialServiceDep
) -> tuple[ResolvedMaterial, ...]:
    """Resolve a material selection against the catalogue.

    Lets the frontend validate a selection before committing to a score, and makes
    the resolution rules visible rather than hidden inside the scoring endpoint.
    """
    return await service.resolve_selection(selection)
