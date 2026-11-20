"""Mid-century climate outlook for a site, from NASA NEX-GDDP-CMIP6 via Earth Engine.

Compares the decade a building is finished in with the decade its home loan ends
in, under SSP2-4.5, across several CMIP6 models. The model spread is reported
alongside the mean, so the outlook says how much the models agree rather than
presenting one projection as a measurement.

This is context shown beside the score. It does not feed the score: ``/score``
stays a pure function of the bundled, measured climate profiles.
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from statistics import fmean

from app.core import calculations, constants
from app.core.logging import get_logger
from app.external.earth_engine import EarthEngineClient, PeriodMeans

logger = get_logger(__name__)

BASELINE = "baseline"
FUTURE = "future"


@dataclass(frozen=True, slots=True)
class ProjectedVariable:
    """One climate variable in both decades, in internal units."""

    name: str
    unit: str
    baseline: float
    future: float
    change_low: float
    change_high: float

    @property
    def change(self) -> float:
        """Multi-model mean change from the baseline decade to the future one."""
        return self.future - self.baseline


@dataclass(frozen=True, slots=True)
class ClimateProjection:
    """The outlook for one site."""

    latitude: float
    longitude: float
    scenario: str
    models: tuple[str, ...]
    baseline_years: tuple[int, int]
    future_years: tuple[int, int]
    variables: tuple[ProjectedVariable, ...]
    dataset: str


# (band, display name, internal unit, conversion from the dataset's unit)
_VARIABLES: tuple[tuple[str, str, str, Callable[[float], float]], ...] = (
    (
        constants.EARTH_ENGINE_BAND_MAX_TEMPERATURE,
        "Mean daily maximum temperature",
        "°C",
        calculations.kelvin_to_celsius,  # K -> °C
    ),
    (
        constants.EARTH_ENGINE_BAND_PRECIPITATION,
        "Mean daily rainfall",
        "mm/day",
        calculations.precipitation_flux_to_mm_per_day,  # kg m-2 s-1 -> mm/day
    ),
    (
        constants.EARTH_ENGINE_BAND_WIND_SPEED,
        "Mean wind speed",
        "m/s",
        float,  # already m/s, the internal unit
    ),
    (
        constants.EARTH_ENGINE_BAND_RELATIVE_HUMIDITY,
        "Mean relative humidity",
        "%",
        float,  # already percent
    ),
)

_CACHE: OrderedDict[tuple[float, float], ClimateProjection] = OrderedDict()


class ClimateProjectionService:
    """Builds the outlook from the Earth Engine client's raw band means."""

    def __init__(self, client: EarthEngineClient) -> None:
        """Bind the service to an Earth Engine client."""
        self._client = client

    async def projection(self, *, latitude: float, longitude: float) -> ClimateProjection:
        """The outlook at a point, cached by the point rounded to ~1 km.

        Raises:
            ExternalServiceUnconfiguredError: If Earth Engine is not configured.
            ExternalServiceError: If Earth Engine fails.
            LocationNotCoveredError: If the dataset has no values there.
        """
        key = (
            round(latitude, constants.PROJECTION_COORDINATE_PRECISION_DP),
            round(longitude, constants.PROJECTION_COORDINATE_PRECISION_DP),
        )
        cached = _CACHE.get(key)
        if cached is not None:
            _CACHE.move_to_end(key)
            return cached

        means = await self._client.period_means(
            latitude=key[0],
            longitude=key[1],
            periods={
                BASELINE: constants.PROJECTION_BASELINE_YEARS,
                FUTURE: constants.PROJECTION_FUTURE_YEARS,
            },
        )
        projection = ClimateProjection(
            latitude=key[0],
            longitude=key[1],
            scenario=constants.EARTH_ENGINE_CMIP6_SCENARIO,
            models=constants.EARTH_ENGINE_CMIP6_MODELS,
            baseline_years=constants.PROJECTION_BASELINE_YEARS,
            future_years=constants.PROJECTION_FUTURE_YEARS,
            variables=tuple(_variable(means, *spec) for spec in _VARIABLES),
            dataset=constants.EARTH_ENGINE_CMIP6_DATASET,
        )
        _CACHE[key] = projection
        while len(_CACHE) > constants.PROJECTION_CACHE_ENTRIES:
            _CACHE.popitem(last=False)
        logger.info("climate_projection_built", latitude=key[0], longitude=key[1])
        return projection


def _variable(
    means: PeriodMeans, band: str, name: str, unit: str, convert: Callable[[float], float]
) -> ProjectedVariable:
    """Average one band across models, converting units, with the change's model spread."""
    baselines = [convert(periods[BASELINE][band]) for periods in means.values()]
    futures = [convert(periods[FUTURE][band]) for periods in means.values()]
    changes = [future - baseline for baseline, future in zip(baselines, futures, strict=True)]
    return ProjectedVariable(
        name=name,
        unit=unit,
        baseline=fmean(baselines),
        future=fmean(futures),
        change_low=min(changes),
        change_high=max(changes),
    )
