"""Tests for the Earth Engine client. The ``ee`` computation is always faked."""

from __future__ import annotations

import ee
import pytest

from app.core import constants
from app.core.exceptions import (
    ExternalServiceError,
    ExternalServiceTimeoutError,
    ExternalServiceUnconfiguredError,
    LocationNotCoveredError,
)
from app.external import earth_engine
from app.external.earth_engine import BANDS, EarthEngineClient, EarthEngineCredentials

pytestmark = pytest.mark.anyio

PERIODS = {"baseline": (2025, 2034), "future": (2046, 2055)}
CREDENTIALS = EarthEngineCredentials(project_id="test-project")


def _reply(value: float | None = 1.0) -> dict[str, object]:
    bands = {band: value for band in BANDS}
    return {
        model: {label: dict(bands) for label in PERIODS}
        for model in constants.EARTH_ENGINE_CMIP6_MODELS
    }


def _client(monkeypatch: pytest.MonkeyPatch, reply: object) -> EarthEngineClient:
    client = EarthEngineClient(CREDENTIALS)

    def compute(*_: object) -> object:
        return reply

    monkeypatch.setattr(client, "_compute", compute)
    return client


async def _means(client: EarthEngineClient) -> earth_engine.PeriodMeans:
    return await client.period_means(latitude=13.08, longitude=80.27, periods=PERIODS)


class TestPeriodMeans:
    """The client validates the reply and maps every failure to a typed error."""

    async def test_unconfigured_is_a_typed_error(self) -> None:
        with pytest.raises(ExternalServiceUnconfiguredError):
            await _means(EarthEngineClient(None))

    async def test_returns_every_model_period_and_band(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        means = await _means(_client(monkeypatch, _reply(2.5)))

        assert set(means) == set(constants.EARTH_ENGINE_CMIP6_MODELS)
        assert means["ACCESS-CM2"]["future"] == {band: 2.5 for band in BANDS}

    async def test_a_missing_value_means_the_point_is_not_covered(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        with pytest.raises(LocationNotCoveredError):
            await _means(_client(monkeypatch, _reply(None)))

    async def test_an_unexpected_shape_is_an_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        with pytest.raises(ExternalServiceError):
            await _means(_client(monkeypatch, ["not", "a", "dict"]))

    async def test_a_slow_answer_times_out(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client = _client(monkeypatch, _reply())
        monkeypatch.setattr(constants, "EARTH_ENGINE_TIMEOUT_SECONDS", 0.01)

        def slow(*_: object) -> object:
            import time

            time.sleep(0.2)
            return _reply()

        monkeypatch.setattr(client, "_compute", slow)

        with pytest.raises(ExternalServiceTimeoutError):
            await _means(client)

    async def test_an_earth_engine_failure_is_typed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client = EarthEngineClient(CREDENTIALS)
        monkeypatch.setattr(client, "_initialise", lambda: None)

        def refuse(*_: object) -> object:
            raise ee.EEException("quota")

        monkeypatch.setattr(earth_engine, "_fetch", refuse)

        with pytest.raises(ExternalServiceError) as caught:
            await _means(client)
        assert caught.value.details["reason"] == "quota"
