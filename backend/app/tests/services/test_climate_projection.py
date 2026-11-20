"""Tests for the climate outlook: unit conversion, model spread and caching."""

from __future__ import annotations

from collections import OrderedDict

import pytest

from app.core import constants
from app.external.earth_engine import BANDS, EarthEngineClient, PeriodMeans
from app.services import climate_projection
from app.services.climate_projection import ClimateProjectionService

pytestmark = pytest.mark.anyio

TASMAX, PR, WIND, RH = BANDS
KELVIN_30C = 303.15
FLUX_5MM_PER_DAY = 5.0 / constants.SECONDS_PER_DAY


class FakeClient(EarthEngineClient):
    """Returns fixed band means; future warmth differs by model to give a spread."""

    def __init__(self) -> None:
        super().__init__(None)
        self.calls: list[tuple[float, float]] = []

    async def period_means(
        self,
        *,
        latitude: float,
        longitude: float,
        periods: dict[str, tuple[int, int]],
    ) -> PeriodMeans:
        self.calls.append((latitude, longitude))
        base = {TASMAX: KELVIN_30C, PR: FLUX_5MM_PER_DAY, WIND: 3.0, RH: 70.0}
        return {
            model: {
                "baseline": dict(base),
                "future": {**base, TASMAX: KELVIN_30C + warming},
            }
            for model, warming in zip(
                constants.EARTH_ENGINE_CMIP6_MODELS, (1.0, 1.5, 2.0, 2.5), strict=True
            )
        }


@pytest.fixture(autouse=True)
def fresh_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    """Each test starts with an empty outlook cache."""
    monkeypatch.setattr(climate_projection, "_CACHE", OrderedDict())


class TestProjection:
    """Raw dataset units become internal units, with the change's spread."""

    async def test_converts_units_and_reports_the_model_spread(self) -> None:
        projection = await ClimateProjectionService(FakeClient()).projection(
            latitude=13.08, longitude=80.27
        )
        by_name = {variable.unit: variable for variable in projection.variables}

        temperature = by_name["°C"]
        assert temperature.baseline == pytest.approx(30.0)
        assert temperature.change == pytest.approx(1.75)
        assert (temperature.change_low, temperature.change_high) == pytest.approx((1.0, 2.5))
        assert by_name["mm/day"].baseline == pytest.approx(5.0)
        assert by_name["m/s"].change == pytest.approx(0.0)

    async def test_nearby_points_share_one_computation(self) -> None:
        client = FakeClient()
        service = ClimateProjectionService(client)

        first = await service.projection(latitude=13.0812, longitude=80.2708)
        second = await service.projection(latitude=13.0779, longitude=80.2741)

        assert first == second
        assert client.calls == [(13.08, 80.27)]
