"""Earth Engine client for NASA NEX-GDDP-CMIP6 period means at a point.

The ``earthengine-api`` library is synchronous, so each computation runs on a
worker thread under an explicit timeout. Everything a request needs is built as
one server-side ``ee.Dictionary`` and fetched with a single ``getInfo`` call, so a
projection costs one round trip however many models and periods it covers.

Two ways to authenticate, chosen by configuration:

* a service-account key file (local development), or
* Application Default Credentials — on Cloud Run, the service's own attached
  service account, so no key file exists anywhere in the deployment.
"""

from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import ee
import google.auth
import google.auth.exceptions

from app.core import constants
from app.core.exceptions import (
    ExternalServiceError,
    ExternalServiceTimeoutError,
    ExternalServiceUnconfiguredError,
    LocationNotCoveredError,
)
from app.core.logging import get_logger

logger = get_logger(__name__)

SERVICE = "earth_engine"

BANDS: tuple[str, ...] = (
    constants.EARTH_ENGINE_BAND_MAX_TEMPERATURE,
    constants.EARTH_ENGINE_BAND_PRECIPITATION,
    constants.EARTH_ENGINE_BAND_WIND_SPEED,
    constants.EARTH_ENGINE_BAND_RELATIVE_HUMIDITY,
)


@dataclass(frozen=True, slots=True)
class EarthEngineCredentials:
    """How to authenticate: a key file, or Application Default Credentials."""

    project_id: str
    service_account_email: str | None = None
    service_account_file: Path | None = None


# Raw band means: model -> period label -> band -> value, in the dataset's units.
PeriodMeans = dict[str, dict[str, dict[str, float]]]


class EarthEngineClient:
    """Computes multi-model CMIP6 band means for given periods at one point."""

    def __init__(self, credentials: EarthEngineCredentials | None) -> None:
        """Bind the client to its credentials; ``None`` means unconfigured."""
        self._credentials = credentials
        self._initialised = False
        self._lock = threading.Lock()

    async def period_means(
        self,
        *,
        latitude: float,
        longitude: float,
        periods: dict[str, tuple[int, int]],
    ) -> PeriodMeans:
        """Mean of each band, per model, over each inclusive span of years.

        Raises:
            ExternalServiceUnconfiguredError: If no credentials are configured.
            ExternalServiceTimeoutError: If Earth Engine does not answer in time.
            ExternalServiceError: If Earth Engine rejects the request.
            LocationNotCoveredError: If the dataset has no value at the point.
        """
        if self._credentials is None:
            raise ExternalServiceUnconfiguredError(
                "Climate projections are not configured on this server.", service=SERVICE
            )
        logger.info("earth_engine_request", latitude=latitude, longitude=longitude, periods=periods)
        try:
            raw = await asyncio.wait_for(
                asyncio.to_thread(self._compute, latitude, longitude, periods),
                timeout=constants.EARTH_ENGINE_TIMEOUT_SECONDS,
            )
        except TimeoutError as error:
            raise ExternalServiceTimeoutError(
                "Earth Engine did not return the projection in time.", service=SERVICE
            ) from error
        means = _validated(raw, periods)
        logger.info("earth_engine_response", models=len(means))
        return means

    def _initialise(self) -> None:
        """Authenticate once per process; later calls are no-ops.

        Raises:
            ExternalServiceUnconfiguredError: If ADC is requested but absent.
            ExternalServiceError: If Earth Engine refuses the credentials.
        """
        with self._lock:
            if self._initialised:
                return
            settings = self._credentials
            if settings is None:
                raise ExternalServiceUnconfiguredError(
                    "Climate projections are not configured on this server.", service=SERVICE
                )
            try:
                if settings.service_account_email and settings.service_account_file:
                    credentials: Any = ee.ServiceAccountCredentials(
                        settings.service_account_email, str(settings.service_account_file)
                    )
                else:
                    credentials, _ = google.auth.default(
                        scopes=list(constants.EARTH_ENGINE_OAUTH_SCOPES)
                    )
                ee.Initialize(credentials=credentials, project=settings.project_id)
            except google.auth.exceptions.DefaultCredentialsError as error:
                raise ExternalServiceUnconfiguredError(
                    "No Google credentials are available for Earth Engine.", service=SERVICE
                ) from error
            except ee.EEException as error:
                raise ExternalServiceError(
                    "Earth Engine refused the configured credentials.", service=SERVICE
                ) from error
            self._initialised = True
            logger.info("earth_engine_initialised", project=settings.project_id)

    def _compute(
        self, latitude: float, longitude: float, periods: dict[str, tuple[int, int]]
    ) -> object:
        """Build and fetch the whole computation in one round trip (worker thread).

        Raises:
            ExternalServiceError: If Earth Engine rejects the computation.
        """
        self._initialise()
        try:
            return _fetch(latitude, longitude, periods)
        except ee.EEException as error:
            raise ExternalServiceError(
                "Earth Engine could not compute the projection.",
                service=SERVICE,
                details={"reason": str(error)},
            ) from error


def _fetch(latitude: float, longitude: float, periods: dict[str, tuple[int, int]]) -> object:
    """Every model's per-period band means at the point, as one ``getInfo`` call."""
    point = ee.Geometry.Point([longitude, latitude])  # GeoJSON order: (lon, lat)
    region = point.buffer(constants.EARTH_ENGINE_SAMPLE_RADIUS_M)
    dataset = ee.ImageCollection(constants.EARTH_ENGINE_CMIP6_DATASET).filter(
        ee.Filter.eq("scenario", constants.EARTH_ENGINE_CMIP6_SCENARIO)
    )
    results: dict[str, Any] = {}
    for model in constants.EARTH_ENGINE_CMIP6_MODELS:
        per_period: dict[str, Any] = {}
        for label, (first, last) in periods.items():
            # filterDate's end is exclusive, so the span closes on 1 January after
            # the last year; the year bounds themselves are inclusive.
            mean = (
                dataset.filter(ee.Filter.eq("model", model))
                .filterDate(f"{first}-01-01", f"{last + 1}-01-01")
                .select(list(BANDS))
                .mean()
            )
            per_period[label] = mean.reduceRegion(
                reducer=ee.Reducer.mean(),
                geometry=region,
                scale=constants.EARTH_ENGINE_SCALE_M,
            )
        results[model] = ee.Dictionary(per_period)
    return ee.Dictionary(results).getInfo()


def _validated(raw: object, periods: dict[str, tuple[int, int]]) -> PeriodMeans:
    """Check the reply holds a number for every model, period and band.

    Raises:
        LocationNotCoveredError: If any value is missing — the point is off the
            dataset's land grid (open sea, for instance).
        ExternalServiceError: If the reply is not the expected shape.
    """
    if not isinstance(raw, dict):
        raise ExternalServiceError("Earth Engine returned an unexpected reply.", service=SERVICE)
    means: PeriodMeans = {}
    for model in constants.EARTH_ENGINE_CMIP6_MODELS:
        model_reply = raw.get(model)
        if not isinstance(model_reply, dict):
            raise ExternalServiceError(
                "Earth Engine returned an unexpected reply.", service=SERVICE
            )
        means[model] = {}
        for label in periods:
            bands = model_reply.get(label)
            values = bands if isinstance(bands, dict) else {}
            missing = [
                band
                for band in BANDS
                if not isinstance(values.get(band), int | float)
                or isinstance(values.get(band), bool)
            ]
            if missing:
                raise LocationNotCoveredError(
                    "The climate projection dataset has no values at this location.",
                    details={"model": model, "period": label, "missing_bands": missing},
                )
            means[model][label] = {band: float(values[band]) for band in BANDS}
    return means
