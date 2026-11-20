"""Climate outlook endpoint: NASA NEX-GDDP-CMIP6 via Earth Engine."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, status

from app.routes.dependencies import ProjectionServiceDep
from app.schemas.climate import (
    ClimateProjectionResponse,
    Latitude,
    Longitude,
    ProjectedVariableResponse,
)
from app.schemas.common import ErrorResponse

router = APIRouter(prefix="/climate", tags=["climate"])

PROJECTION_ERRORS: dict[int | str, dict[str, Any]] = {
    status.HTTP_404_NOT_FOUND: {
        "model": ErrorResponse,
        "description": "The projection dataset has no values at this point.",
    },
    status.HTTP_502_BAD_GATEWAY: {"model": ErrorResponse, "description": "Earth Engine failed."},
    status.HTTP_503_SERVICE_UNAVAILABLE: {
        "model": ErrorResponse,
        "description": "Earth Engine is not configured on this server.",
    },
    status.HTTP_504_GATEWAY_TIMEOUT: {
        "model": ErrorResponse,
        "description": "Earth Engine did not answer in time.",
    },
}


@router.get(
    "/projection",
    response_model=ClimateProjectionResponse,
    summary="Mid-century climate outlook at a point (CMIP6, SSP2-4.5)",
    responses=PROJECTION_ERRORS,
)
async def get_projection(
    service: ProjectionServiceDep,
    latitude: Latitude,
    longitude: Longitude,
) -> ClimateProjectionResponse:
    """Compare this decade with the decade a 30-year loan ends in, across models."""
    projection = await service.projection(latitude=latitude, longitude=longitude)
    return ClimateProjectionResponse(
        latitude=projection.latitude,
        longitude=projection.longitude,
        scenario=projection.scenario,
        models=projection.models,
        baseline_years=projection.baseline_years,
        future_years=projection.future_years,
        variables=tuple(
            ProjectedVariableResponse(
                name=variable.name,
                unit=variable.unit,
                baseline=variable.baseline,
                future=variable.future,
                change=variable.change,
                change_low=variable.change_low,
                change_high=variable.change_high,
            )
            for variable in projection.variables
        ),
        dataset=projection.dataset,
    )
