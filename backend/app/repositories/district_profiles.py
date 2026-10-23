"""Loads the GRIB-derived district climate profiles.

This is the sole source of climate data in the application. It replaced Google
Earth Engine outright: every value here was measured between 2016 and 2026 and
traces through ``ml/build_district_profiles.py`` and ``ml/grib_to_csv.py`` back to
``data.grib``. Nothing is projected or modelled.

Regenerate with ``node scripts/py.mjs ../ml/build_district_profiles.py``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from app.core import calculations
from app.core.exceptions import AppError

PROFILES_PATH = Path(__file__).parent / "data" / "district_climate_profiles.json"


class ClimateProfileUnavailableError(AppError):
    """The bundled district profiles are missing, malformed, or lack a district."""

    code = "CLIMATE_PROFILE_UNAVAILABLE"
    http_status = 503


@dataclass(frozen=True, slots=True)
class DistrictClimateProfile:
    """Measured climate for one district, reduced to what the IS rules use.

    Rainfall is deliberately expressed as an hourly sample and as fractions rather
    than an annual depth: the source field accumulates over one hour at 00:00 UTC,
    so an annual total cannot be derived without inventing the diurnal cycle.
    Districts remain directly comparable because the sampling is identical.
    """

    district: str
    grid_latitude: float
    grid_longitude: float
    distance_to_coast_km: float
    mean_relative_humidity_percent: float
    humid_hours_fraction: float
    mean_temperature_c: float
    mean_max_temperature_c: float
    max_temperature_c: float
    mean_hourly_rainfall_mm: float
    max_hourly_rainfall_mm: float
    wet_hours_fraction: float
    wet_dry_cycles_per_year: float
    mean_wind_speed_ms: float
    max_wind_gust_ms: float
    mean_soil_moisture_m3_m3: float
    observation_days: int


@dataclass(frozen=True, slots=True)
class ClimateProfileSet:
    """Every district profile plus the provenance of the whole set."""

    profiles: tuple[DistrictClimateProfile, ...]
    source_grib: str
    source_csv: str
    observation_start: str
    observation_end: str
    generated_at: str

    def names(self) -> tuple[str, ...]:
        """District names, alphabetical."""
        return tuple(profile.district for profile in self.profiles)

    def nearest(self, latitude: float, longitude: float) -> tuple[DistrictClimateProfile, float]:
        """The closest grid node to a point, with its great-circle distance in km.

        Lets a map or globe hand back raw coordinates and still resolve to a
        district the model can actually score.

        The distance is returned rather than discarded because the caller has to
        decide whether the pin is inside the observed region at all. A bare nearest
        lookup always succeeds — it would answer a pin dropped in the Atlantic with
        an inland Indian district — so the distance is the only thing standing
        between a dropped pin and a fabricated answer.

        Raises:
            ClimateProfileUnavailableError: If no profiles are loaded.
        """
        if not self.profiles:
            raise ClimateProfileUnavailableError("No district climate profiles are loaded.")

        def separation(profile: DistrictClimateProfile) -> float:
            return calculations.haversine_km(
                latitude, longitude, profile.grid_latitude, profile.grid_longitude
            )

        closest = min(self.profiles, key=separation)
        return closest, separation(closest)

    def get(self, district: str) -> DistrictClimateProfile:
        """Look up one district, case-insensitively.

        Raises:
            ClimateProfileUnavailableError: If the district has no profile. The
                error names the districts that do, because the usual cause is a
                place outside the bundled grid.
        """
        wanted = district.strip().casefold()
        for profile in self.profiles:
            if profile.district.casefold() == wanted:
                return profile
        raise ClimateProfileUnavailableError(
            f"No measured climate profile for {district!r}.",
            details={"available_districts": list(self.names())},
        )


@lru_cache(maxsize=1)
def load_climate_profiles() -> ClimateProfileSet:
    """Parse and cache the bundled profiles.

    Raises:
        ClimateProfileUnavailableError: If the file is missing or malformed.
    """
    try:
        with PROFILES_PATH.open(encoding="utf-8") as handle:
            payload = json.load(handle)
        rows = payload["profiles"]
        period = payload["observation_period"]
    except (OSError, json.JSONDecodeError, KeyError) as error:
        raise ClimateProfileUnavailableError(
            "The bundled district climate profiles could not be read. Run "
            "`node scripts/py.mjs ../ml/build_district_profiles.py`.",
            details={"path": str(PROFILES_PATH)},
        ) from error

    return ClimateProfileSet(
        profiles=tuple(DistrictClimateProfile(**row) for row in rows),
        source_grib=payload.get("source_grib", "data.grib"),
        source_csv=payload.get("source_csv", ""),
        observation_start=period["start"],
        observation_end=period["end"],
        generated_at=payload.get("generated_at", ""),
    )
