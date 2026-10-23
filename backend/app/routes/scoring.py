"""Building Quality Score endpoints.

Thin by design: parse, call one service, map the result. Both modes go through the
same handler because the engine always computes both sides — supplying materials
is evaluate mode, omitting them is recommend mode.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, status

from app.core import constants
from app.routes.dependencies import ClimateServiceDep, ScoringServiceDep
from app.schemas.common import ErrorResponse
from app.schemas.scoring import (
    AreaScoreRequest,
    ClimateProfileResponse,
    ClimateProvenanceResponse,
    ComplianceFindingResponse,
    DistrictListResponse,
    MaterialSelectionInput,
    PinRequest,
    PinResolutionResponse,
    RecommendationResponse,
    ScoredSelectionResponse,
    ScoreRequest,
    ScoreResponse,
    ServiceLifeResponse,
)
from app.services.area_climate import AreaBounds
from app.services.rules_engine import ConcreteMix, MaterialSelection
from app.services.scoring import ScoreComparison, ScoredSelection

router = APIRouter(prefix="/score", tags=["scoring"])

SCORE_ERRORS: dict[int | str, dict[str, Any]] = {
    status.HTTP_422_UNPROCESSABLE_ENTITY: {
        "model": ErrorResponse,
        "description": "The request did not match the expected shape.",
    },
    status.HTTP_503_SERVICE_UNAVAILABLE: {
        "model": ErrorResponse,
        "description": "No measured climate profile for that district, or models not trained.",
    },
}


@router.get(
    "/districts",
    response_model=DistrictListResponse,
    summary="Districts with a measured climate profile",
)
async def list_districts(climate: ClimateServiceDep) -> DistrictListResponse:
    """List the districts that can be scored, with where each one sits.

    Coordinates are included so a map or globe can place markers and resolve a
    dropped pin to a supported district. ``grid_resolution_km`` is returned with
    them deliberately: a picker must not offer finer precision than the climate
    grid actually has, or it implies a per-building reading that does not exist.
    """
    provenance = climate.provenance
    return DistrictListResponse(
        districts=climate.available_districts,
        locations=climate.locations,
        grid_resolution_km=constants.CLIMATE_GRID_RESOLUTION_KM,
        coverage=climate.coverage,
        max_pin_distance_km=constants.MAX_PIN_TO_GRID_DISTANCE_KM,
        observation_start=provenance["observation_start"],
        observation_end=provenance["observation_end"],
        source=provenance["source"],
    )


@router.post(
    "/resolve",
    response_model=PinResolutionResponse,
    summary="Resolve a dropped pin to the grid cell that will be scored",
    responses=SCORE_ERRORS,
)
async def resolve_pin(request: PinRequest, climate: ClimateServiceDep) -> PinResolutionResponse:
    """Turn map coordinates into the district whose reading applies there.

    Separate from ``POST /score`` on purpose. A globe needs an answer as the pin
    moves, long before there is a specification to score, and keeping the lookup
    here leaves ``/score`` a pure function of a named district.
    """
    profile, distance_km = climate.resolve_nearest(request.latitude, request.longitude)
    return PinResolutionResponse(
        district=profile.district,
        grid_latitude=profile.grid_latitude,
        grid_longitude=profile.grid_longitude,
        distance_km=round(distance_km, 1),
    )


@router.post(
    "",
    response_model=ScoreResponse,
    summary="Score a district's materials, and the recommendation alongside",
    responses=SCORE_ERRORS,
)
async def create_score(request: ScoreRequest, service: ScoringServiceDep) -> ScoreResponse:
    """Return the proposed and recommended specifications, both scored.

    Supplying ``materials`` evaluates them. Omitting it returns the recommendation
    against a conventional baseline, so a before/after always exists.
    """
    proposed = to_selection(request.materials)
    comparison = service.compare(
        district=request.district,
        proposed=proposed,
        situation=request.element_situation,
    )
    return _to_response(comparison)


@router.post(
    "/area",
    response_model=ScoreResponse,
    summary="Score a drawn site boundary",
    responses=SCORE_ERRORS,
)
async def create_area_score(request: AreaScoreRequest, service: ScoringServiceDep) -> ScoreResponse:
    """Score an area drawn on the map rather than a named district.

    The reply is the same shape as ``POST /score`` with one addition:
    ``climate_provenance`` says whether the climate was measured inside the drawn
    area or interpolated from surrounding cells. That field is the interface's only
    way to distinguish the two, so it is always populated here.
    """
    comparison, area_climate = service.compare_area(
        area=AreaBounds(
            south=request.area.south,
            north=request.area.north,
            west=request.area.west,
            east=request.area.east,
        ),
        proposed=to_selection(request.materials),
        situation=request.element_situation,
    )
    return _to_response(
        comparison,
        provenance=ClimateProvenanceResponse(
            interpolated=area_climate.interpolated,
            enclosed_node_count=area_climate.enclosed_node_count,
            source_districts=area_climate.source_districts,
            nearest_source_km=area_climate.nearest_source_km,
        ),
    )


def to_selection(materials: MaterialSelectionInput | None) -> MaterialSelection | None:
    """Map the request body onto the engine's input type.

    Shared with the report endpoint, which takes the same body — defined once so
    the two cannot drift apart.
    """
    if materials is None:
        return None
    return MaterialSelection(
        concrete=ConcreteMix(
            grade=materials.concrete.grade,
            cement_content_kg_m3=materials.concrete.cement_content_kg_m3,
            water_cement_ratio=materials.concrete.water_cement_ratio,
            cement_type=materials.concrete.cement_type,
            admixtures=tuple(materials.concrete.admixtures),
        ),
        walling_material_id=materials.walling_material_id,
        element_situation=materials.element_situation,
    )


SERVICE_LIFE_BASIS = (
    "Estimated from IS 456's 50-year design life, adjusted for how this mix's "
    "water/cement ratio and compliance compare to the exposure class minimums. "
    "Not a prediction from observed building failures."
)


def _to_service_life(scored: ScoredSelection) -> ServiceLifeResponse:
    """Map the estimate and its band onto the response shape."""
    lower, upper = scored.service_life_interval
    return ServiceLifeResponse(
        years=round(scored.service_life_years, 1),
        lower_years=round(lower, 1),
        upper_years=round(upper, 1),
        baseline_years=constants.DESIGN_SERVICE_LIFE_YEARS,
        basis=SERVICE_LIFE_BASIS,
    )


def _to_scored(scored: ScoredSelection) -> ScoredSelectionResponse:
    """Map one scored specification onto its response shape."""
    from app.schemas.scoring import ConcreteMixInput

    return ScoredSelectionResponse(
        concrete=ConcreteMixInput(
            grade=scored.selection.concrete.grade,
            cement_content_kg_m3=scored.selection.concrete.cement_content_kg_m3,
            water_cement_ratio=scored.selection.concrete.water_cement_ratio,
            cement_type=scored.selection.concrete.cement_type,
            admixtures=tuple(scored.selection.concrete.admixtures),
        ),
        walling_material_id=scored.selection.walling_material_id,
        score=scored.score,
        rules_score=scored.rules_score,
        band=scored.band,
        compliant=scored.assessment.compliant,
        service_life=_to_service_life(scored),
        findings=tuple(
            ComplianceFindingResponse(
                parameter=finding.parameter,
                label=finding.label,
                required=finding.required,
                provided=finding.provided,
                compliant=finding.compliant,
                margin_ratio=round(finding.margin_ratio, 4),
                standard=finding.standard,
                message=finding.message,
            )
            for finding in scored.assessment.findings
        ),
    )


def _to_response(
    comparison: ScoreComparison,
    provenance: ClimateProvenanceResponse | None = None,
) -> ScoreResponse:
    """Map the engine's comparison onto the API response."""
    climate = comparison.climate
    followed = set(comparison.proposed.assessment.followed_recommendation_ids)

    return ScoreResponse(
        district=comparison.district,
        climate=ClimateProfileResponse(
            district=climate.district,
            distance_to_coast_km=climate.distance_to_coast_km,
            mean_relative_humidity_percent=climate.mean_relative_humidity_percent,
            mean_max_temperature_c=climate.mean_max_temperature_c,
            max_wind_gust_ms=climate.max_wind_gust_ms,
            wet_hours_fraction=climate.wet_hours_fraction,
            wet_dry_cycles_per_year=climate.wet_dry_cycles_per_year,
            observation_days=climate.observation_days,
        ),
        exposure_class=comparison.exposure.id,
        exposure_label=comparison.exposure.label,
        exposure_reasons=comparison.exposure_reasons,
        proposed=_to_scored(comparison.proposed),
        recommended=_to_scored(comparison.recommended),
        improvement=comparison.improvement,
        recommendations=tuple(
            RecommendationResponse(
                id=item.id,
                condition_label=item.condition_label,
                material=item.material,
                purpose=item.purpose,
                standard=item.standard,
                followed=item.id in followed,
            )
            for item in comparison.proposed.assessment.applicable_recommendations
        ),
        model_version=comparison.model_version,
        data_source=comparison.provenance,
        climate_provenance=provenance,
    )
