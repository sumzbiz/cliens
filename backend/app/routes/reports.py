"""Downloadable client report endpoint."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, status
from fastapi.responses import Response

from app.routes.dependencies import ScoringServiceDep
from app.routes.scoring import to_selection
from app.schemas.common import ErrorResponse
from app.schemas.scoring import AreaScoreRequest, ScoreRequest
from app.services.area_climate import AreaBounds
from app.services.report_pdf import build_report_pdf
from app.services.scoring import ScoreComparison

router = APIRouter(prefix="/reports", tags=["reports"])

REPORT_ERRORS: dict[int | str, dict[str, Any]] = {
    status.HTTP_422_UNPROCESSABLE_ENTITY: {
        "model": ErrorResponse,
        "description": "The request did not match the expected shape.",
    },
    status.HTTP_503_SERVICE_UNAVAILABLE: {
        "model": ErrorResponse,
        "description": "No measured climate profile for that district, or models not trained.",
    },
}


@router.post(
    "",
    summary="Download the client report as a PDF",
    responses={
        status.HTTP_200_OK: {
            "content": {"application/pdf": {}},
            "description": "The report.",
        },
        **REPORT_ERRORS,
    },
)
async def download_report(request: ScoreRequest, service: ScoringServiceDep) -> Response:
    """Score the district and return the result as a downloadable PDF.

    Takes the same body as ``POST /score`` and re-scores rather than reading a
    stored result. Scoring is deterministic and inexpensive, so this avoids
    persisting anything and guarantees the document matches the current engine
    rather than a stale row.
    """
    comparison = service.compare(
        district=request.district,
        proposed=to_selection(request.materials),
        situation=request.element_situation,
    )
    return _pdf_response(comparison, evaluated_own_materials=request.materials is not None)


@router.post(
    "/area",
    summary="Download the client report for a drawn site as a PDF",
    responses={
        status.HTTP_200_OK: {
            "content": {"application/pdf": {}},
            "description": "The report.",
        },
        **REPORT_ERRORS,
    },
)
async def download_area_report(request: AreaScoreRequest, service: ScoringServiceDep) -> Response:
    """The same report, for a boundary drawn on the map rather than a named district.

    A separate endpoint for the same reason `/score/area` is separate: a drawn
    outline has no district name, and `ScoreRequest` requires one. Without this,
    downloading the report after plotting a site failed validation before it ever
    reached the engine.
    """
    comparison, _ = service.compare_area(
        area=AreaBounds(
            south=request.area.south,
            north=request.area.north,
            west=request.area.west,
            east=request.area.east,
        ),
        proposed=to_selection(request.materials),
        situation=request.element_situation,
    )
    return _pdf_response(comparison, evaluated_own_materials=request.materials is not None)


def _pdf_response(comparison: ScoreComparison, *, evaluated_own_materials: bool) -> Response:
    """Render a comparison as a downloadable PDF.

    Shared by both endpoints so the document and its filename cannot differ
    depending on how the site was chosen.
    """
    pdf = build_report_pdf(comparison, evaluated_own_materials=evaluated_own_materials)
    # A drawn area's name contains spaces and brackets, neither of which belong in
    # a filename a browser is about to write to disk.
    slug = "".join(
        character if character.isalnum() else "-" for character in comparison.district.lower()
    ).strip("-")
    filename = f"building-quality-score-{slug or 'site'}.pdf"
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
