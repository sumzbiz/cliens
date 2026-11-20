"""Which optional Google integrations this server can use.

The frontend reads this to decide whether to offer the explanation and climate
outlook panels at all, rather than showing a button that can only fail.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.routes.dependencies import SettingsDep
from app.schemas.climate import IntegrationsResponse

router = APIRouter(prefix="/integrations", tags=["integrations"])


@router.get("", response_model=IntegrationsResponse, summary="Configured integrations")
async def get_integrations(settings: SettingsDep) -> IntegrationsResponse:
    """Report which integrations have credentials. Never reveals the credentials."""
    return IntegrationsResponse(
        gemini_explanations=settings.gemini_configured,
        earth_engine_projections=settings.earth_engine_configured,
    )
