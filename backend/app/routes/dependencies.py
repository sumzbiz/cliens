"""FastAPI dependency wiring.

Routes declare which service they need; this module is the only place that knows
how to build one. Keeping construction here means a route never imports a
repository, which is what stops the layering being quietly bypassed.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.database import get_session
from app.external.earth_engine import EarthEngineClient, EarthEngineCredentials
from app.external.sarvam import SarvamTtsClient
from app.ml.quality_score import QualityScoreModel
from app.ml.registry import get_registry
from app.repositories.knowledge_base import load_knowledge_base
from app.repositories.materials import MaterialRepository
from app.repositories.sites import SiteRepository
from app.services.climate_data import ClimateDataService
from app.services.climate_projection import ClimateProjectionService
from app.services.explanation import ExplanationService
from app.services.materials import MaterialService
from app.services.narration import NarrationService
from app.services.scoring import QualityScoringService
from app.services.sites import SiteService

SessionDep = Annotated[AsyncSession, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


@lru_cache(maxsize=1)
def _narration_service(keys: tuple[str, ...], speaker: str, language: str) -> NarrationService:
    """Build the narration service once per configuration.

    Cached because the client holds which key is currently active. A fresh
    instance per request would forget that an exhausted key had already been
    retired and rediscover the rate limit on every narration.
    """
    return NarrationService(
        SarvamTtsClient(keys, speaker=speaker, language=language),
        speaker=speaker,
        language=language,
    )


def get_narration_service(settings: SettingsDep) -> NarrationService:
    """Provide the narration service, bound to the resolved settings."""
    return _narration_service(
        settings.sarvam_keys,
        settings.sarvam_tts_speaker,
        settings.sarvam_tts_language,
    )


NarrationServiceDep = Annotated[NarrationService, Depends(get_narration_service)]


def get_material_service(session: SessionDep) -> MaterialService:
    """Build the material service for one request."""
    return MaterialService(MaterialRepository(session))


MaterialServiceDep = Annotated[MaterialService, Depends(get_material_service)]


def get_climate_service() -> ClimateDataService:
    """Build the climate service.

    Backed entirely by the bundled GRIB-derived profiles, so it needs no session
    and makes no network call.
    """
    return ClimateDataService()


ClimateServiceDep = Annotated[ClimateDataService, Depends(get_climate_service)]


def get_scoring_service(climate: ClimateServiceDep) -> QualityScoringService:
    """Build the quality score engine for one request.

    The model registry is process-wide and loaded at startup, so this only wraps
    already-loaded artifacts — nothing is read from disk per request.
    """
    knowledge_base = load_knowledge_base()
    absorption = {
        item.id: item.max_water_absorption_percent for item in knowledge_base.masonry_properties
    }
    return QualityScoringService(
        climate=climate,
        model=QualityScoreModel(get_registry().quality, absorption, knowledge_base),
        knowledge_base=knowledge_base,
    )


ScoringServiceDep = Annotated[QualityScoringService, Depends(get_scoring_service)]


def get_site_service(session: SessionDep) -> SiteService:
    """Provide the site service, bound to the request's session."""
    return SiteService(SiteRepository(session))


SiteServiceDep = Annotated[SiteService, Depends(get_site_service)]


def get_explanation_service(
    scoring: ScoringServiceDep, settings: SettingsDep
) -> ExplanationService:
    """Provide the explanation service, bound to the scoring engine and Gemini settings."""
    return ExplanationService(
        scoring=scoring, api_key=settings.gemini_api_key, model=settings.gemini_model
    )


ExplanationServiceDep = Annotated[ExplanationService, Depends(get_explanation_service)]


@lru_cache(maxsize=1)
def _earth_engine_client(credentials: EarthEngineCredentials | None) -> EarthEngineClient:
    """Build the Earth Engine client once per configuration.

    Cached because authenticating is a network round trip; it happens on the
    first projection request and is then reused for the life of the process.
    """
    return EarthEngineClient(credentials)


def get_projection_service(settings: SettingsDep) -> ClimateProjectionService:
    """Provide the climate outlook service, bound to the Earth Engine settings."""
    credentials = None
    if settings.earth_engine_configured and settings.earth_engine_project_id:
        use_key = not settings.earth_engine_use_application_default
        credentials = EarthEngineCredentials(
            project_id=settings.earth_engine_project_id,
            service_account_email=settings.earth_engine_service_account_email if use_key else None,
            service_account_file=settings.earth_engine_service_account_file if use_key else None,
        )
    return ClimateProjectionService(_earth_engine_client(credentials))


ProjectionServiceDep = Annotated[ClimateProjectionService, Depends(get_projection_service)]
