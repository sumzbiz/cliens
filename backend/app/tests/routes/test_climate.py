"""Tests for the climate outlook and integrations endpoints. Earth Engine is faked."""

from __future__ import annotations

from collections import OrderedDict

import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from app.core import constants
from app.core.config import Settings, get_settings
from app.external.earth_engine import BANDS, EarthEngineClient, PeriodMeans
from app.routes.dependencies import get_projection_service
from app.services import climate_projection
from app.services.climate_projection import ClimateProjectionService

pytestmark = pytest.mark.anyio


class FixedClient(EarthEngineClient):
    """Every model, period and band reads 1.0."""

    def __init__(self) -> None:
        super().__init__(None)

    async def period_means(
        self,
        *,
        latitude: float,
        longitude: float,
        periods: dict[str, tuple[int, int]],
    ) -> PeriodMeans:
        return {
            model: {label: dict.fromkeys(BANDS, 1.0) for label in periods}
            for model in constants.EARTH_ENGINE_CMIP6_MODELS
        }


@pytest.fixture(autouse=True)
def fresh_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    """Each test starts with an empty outlook cache."""
    monkeypatch.setattr(climate_projection, "_CACHE", OrderedDict())


class TestProjection:
    """The endpoint validates coordinates and relays the service's outlook."""

    async def test_returns_the_outlook(self, app: FastAPI, client: AsyncClient) -> None:
        app.dependency_overrides[get_projection_service] = lambda: ClimateProjectionService(
            FixedClient()
        )

        response = await client.get(
            "/api/climate/projection", params={"latitude": 13.08, "longitude": 80.27}
        )

        assert response.status_code == 200
        body = response.json()
        assert body["scenario"] == constants.EARTH_ENGINE_CMIP6_SCENARIO
        assert len(body["variables"]) == len(BANDS)

    async def test_rejects_an_impossible_latitude(self, client: AsyncClient) -> None:
        response = await client.get(
            "/api/climate/projection", params={"latitude": 91, "longitude": 80}
        )

        assert response.status_code == 422

    async def test_unconfigured_earth_engine_is_a_503(
        self, app: FastAPI, client: AsyncClient
    ) -> None:
        app.dependency_overrides[get_projection_service] = lambda: ClimateProjectionService(
            EarthEngineClient(None)
        )

        response = await client.get(
            "/api/climate/projection", params={"latitude": 13.08, "longitude": 80.27}
        )

        assert response.status_code == 503
        assert response.json()["error"]["code"] == "EXTERNAL_SERVICE_UNCONFIGURED"


class TestIntegrations:
    """The integrations flags follow configuration and never expose a credential."""

    async def test_reports_what_is_configured(
        self, app: FastAPI, client: AsyncClient, settings: Settings
    ) -> None:
        configured = settings.model_copy(
            update={"gemini_api_key": "secret-value", "earth_engine_project_id": None}
        )
        app.dependency_overrides[get_settings] = lambda: configured

        response = await client.get("/api/integrations")

        assert response.json() == {
            "gemini_explanations": True,
            "earth_engine_projections": False,
        }
        assert "secret-value" not in response.text
