"""Serves measured district climate, reduced to what the IS 456 rules consume.

Thin by design. All the work happens offline in the GRIB pipeline; at request time
this looks up a precomputed profile and adapts it to the shape the rules engine
expects. There is no network call and no projection.

Rainfall note that governs one design choice here: the source accumulates over a
single hour, so ``ClimateSummary.annual_rainfall_mm`` cannot be filled honestly.
The rules engine takes a wetness *index* instead — see ``to_rules_summary``.
"""

from __future__ import annotations

from app.core import constants
from app.core.logging import get_logger
from app.repositories.district_profiles import (
    ClimateProfileSet,
    ClimateProfileUnavailableError,
    DistrictClimateProfile,
    load_climate_profiles,
)
from app.schemas.scoring import CoverageBounds, DistrictLocation
from app.services.rules_engine import ClimateSummary

logger = get_logger(__name__)


class ClimateDataService:
    """Reads measured climate profiles for a district."""

    def __init__(self, profiles: ClimateProfileSet | None = None) -> None:
        """Bind the service to a profile set, loading the bundle by default."""
        self._profiles = profiles or load_climate_profiles()

    @property
    def profile_set(self) -> ClimateProfileSet:
        """The loaded profiles, for services that need the whole set.

        Exposed so area interpolation can reach every node without loading the
        bundle a second time and risking two views of the same data.
        """
        return self._profiles

    @property
    def available_districts(self) -> tuple[str, ...]:
        """Districts with a measured profile."""
        return self._profiles.names()

    @property
    def locations(self) -> tuple[DistrictLocation, ...]:
        """Where each supported district sits, for map and globe pickers."""
        return tuple(
            DistrictLocation(
                name=profile.district,
                grid_latitude=profile.grid_latitude,
                grid_longitude=profile.grid_longitude,
            )
            for profile in self._profiles.profiles
        )

    @property
    def coverage(self) -> CoverageBounds:
        """The bounding box of the observed region, derived from the profiles.

        Computed rather than declared so it cannot fall out of step with the data
        if the GRIB source is ever re-cut over a different area.

        Raises:
            ClimateProfileUnavailableError: If no profiles are loaded.
        """
        profiles = self._profiles.profiles
        if not profiles:
            raise ClimateProfileUnavailableError("No district climate profiles are loaded.")

        latitudes = [profile.grid_latitude for profile in profiles]
        longitudes = [profile.grid_longitude for profile in profiles]
        return CoverageBounds(
            south=min(latitudes),
            north=max(latitudes),
            west=min(longitudes),
            east=max(longitudes),
        )

    def resolve_nearest(
        self, latitude: float, longitude: float
    ) -> tuple[DistrictClimateProfile, float]:
        """Resolve dropped-pin coordinates to a supported district and its distance.

        Refuses rather than guesses once the pin leaves the observed region. A
        nearest-node lookup never fails on its own, so without this check a pin
        dropped anywhere on Earth would come back with a confident Indian district
        and a score describing somewhere thousands of kilometres away.

        Raises:
            ClimateProfileUnavailableError: If the nearest grid node is further than
                ``MAX_PIN_TO_GRID_DISTANCE_KM``, or no profiles are loaded.
        """
        profile, distance_km = self._profiles.nearest(latitude, longitude)

        if distance_km > constants.MAX_PIN_TO_GRID_DISTANCE_KM:
            logger.info(
                "pin_outside_observed_region",
                latitude=latitude,
                longitude=longitude,
                nearest_district=profile.district,
                distance_km=round(distance_km, 1),
            )
            raise ClimateProfileUnavailableError(
                "There is no measured climate for that point. The nearest place we "
                f"hold data for is {profile.district}, {distance_km:,.0f} km away. "
                "Pick somewhere inside the highlighted region."
            )

        logger.info(
            "coordinates_resolved_to_district",
            latitude=latitude,
            longitude=longitude,
            district=profile.district,
            distance_km=round(distance_km, 1),
        )
        return profile, distance_km

    @property
    def provenance(self) -> dict[str, str]:
        """Where the profiles came from, for display alongside any score."""
        return {
            "source": self._profiles.source_grib,
            "dataset": "ECMWF ERA5 reanalysis",
            "observation_start": self._profiles.observation_start,
            "observation_end": self._profiles.observation_end,
        }

    def get_profile(self, district: str) -> DistrictClimateProfile:
        """Measured climate for one district.

        Raises:
            ClimateProfileUnavailableError: If the district has no profile.
        """
        profile = self._profiles.get(district)
        logger.info("climate_profile_read", district=profile.district)
        return profile

    def to_rules_summary(self, profile: DistrictClimateProfile) -> ClimateSummary:
        """Adapt a measured profile to the rules engine's input.

        ``wetness_index`` replaces an annual rainfall depth. It is the fraction of
        sampled hours that were wet, which the source supports directly, whereas an
        annual total would require assuming a diurnal cycle the file does not
        contain.
        """
        return ClimateSummary(
            district=profile.district,
            mean_relative_humidity_percent=profile.mean_relative_humidity_percent,
            wetness_index=profile.wet_hours_fraction,
            wet_dry_cycles_per_year=profile.wet_dry_cycles_per_year,
            max_wind_gust_ms=profile.max_wind_gust_ms,
            mean_max_temperature_c=profile.mean_max_temperature_c,
            distance_to_coast_km=profile.distance_to_coast_km,
        )
