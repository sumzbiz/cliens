"""Climate for a user-drawn area, from the measured grid.

This is the only place in the application that produces a climate value which was
not read directly from ``data.grib``. It exists because the interface lets a user
drag a boundary anywhere, and a drawn box will often fall between the 0.25 degree
nodes the record actually holds.

THE RULE THIS MODULE ENFORCES
-----------------------------
An interpolated value is permitted only when it is grounded in real neighbouring
readings, and it is always flagged. Concretely:

* If the drawn area contains grid nodes, only those nodes are used. Nothing is
  interpolated and ``interpolated`` is False.
* If it contains none, the value is inverse-distance weighted from at most
  ``MAX_INTERPOLATION_SOURCES`` nodes within ``MAX_INTERPOLATION_DISTANCE_KM``, and
  ``interpolated`` is True.
* If no node is within that distance, the request is refused. There is no
  neighbouring evidence, so any number produced would be invention rather than
  interpolation, and a wrong number in a permit context is worse than an error.

Means are interpolated. Maxima are *not* — they are taken as the maximum over the
contributing nodes. Averaging peak gusts across cells would understate the design
value for the worst cell in the area, and a peak wind figure is used to size against
the worst case, not the typical one.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.core import calculations, constants
from app.core.logging import get_logger
from app.repositories.district_profiles import (
    ClimateProfileSet,
    ClimateProfileUnavailableError,
    DistrictClimateProfile,
)

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class AreaBounds:
    """A drawn rectangle in WGS84 degrees."""

    south: float
    north: float
    west: float
    east: float

    @property
    def centre(self) -> tuple[float, float]:
        """The rectangle's centre as ``(latitude, longitude)``."""
        return (self.south + self.north) / 2.0, (self.west + self.east) / 2.0

    def contains(self, latitude: float, longitude: float) -> bool:
        """Whether a point falls inside the rectangle, edges included."""
        return self.south <= latitude <= self.north and self.west <= longitude <= self.east


@dataclass(frozen=True, slots=True)
class AreaClimate:
    """A climate profile for a drawn area, with how it was arrived at.

    The provenance fields are not decoration. ``interpolated`` decides whether the
    interface must tell the user the reading was derived rather than measured, and
    ``source_districts`` lets them check which real cells stand behind it.
    """

    profile: DistrictClimateProfile
    source_districts: tuple[str, ...]
    #: Grid nodes that fell inside the drawn area. Zero means the value was
    #: interpolated from outside it.
    enclosed_node_count: int
    interpolated: bool
    #: Distance from the area's centre to the nearest contributing node, in km.
    nearest_source_km: float


#: Fields averaged across contributing nodes.
_MEAN_FIELDS: tuple[str, ...] = (
    "distance_to_coast_km",
    "mean_relative_humidity_percent",
    "humid_hours_fraction",
    "mean_temperature_c",
    "mean_max_temperature_c",
    "mean_hourly_rainfall_mm",
    "wet_hours_fraction",
    "wet_dry_cycles_per_year",
    "mean_wind_speed_ms",
    "mean_soil_moisture_m3_m3",
)

#: Fields taken as the worst case across contributing nodes rather than averaged.
_MAX_FIELDS: tuple[str, ...] = (
    "max_temperature_c",
    "max_hourly_rainfall_mm",
    "max_wind_gust_ms",
)


class AreaClimateService:
    """Derives a climate profile for a drawn area from the measured grid."""

    def __init__(self, profiles: ClimateProfileSet) -> None:
        """Bind the service to the loaded profile set."""
        self._profiles = profiles

    def for_area(self, area: AreaBounds) -> AreaClimate:
        """Climate for a drawn area.

        Raises:
            ClimateProfileUnavailableError: If no measured node lies inside the area
                or within ``MAX_INTERPOLATION_DISTANCE_KM`` of its centre.
        """
        profiles = self._profiles.profiles
        if not profiles:
            raise ClimateProfileUnavailableError("No district climate profiles are loaded.")

        centre_lat, centre_lon = area.centre
        enclosed = tuple(
            profile
            for profile in profiles
            if area.contains(profile.grid_latitude, profile.grid_longitude)
        )

        if enclosed:
            # Real nodes inside the drawn box. Weight them evenly: each represents
            # an equal-area cell, so distance to the box centre is not a measure of
            # how much of the area each one speaks for.
            weights = [1.0] * len(enclosed)
            sources = enclosed
            interpolated = False
        else:
            sources, weights = self._interpolation_sources(centre_lat, centre_lon)
            interpolated = True

        nearest_km = min(
            calculations.haversine_km(
                centre_lat, centre_lon, profile.grid_latitude, profile.grid_longitude
            )
            for profile in sources
        )

        profile = self._blend(sources, weights, centre_lat, centre_lon)

        logger.info(
            "area_climate_derived",
            south=area.south,
            north=area.north,
            west=area.west,
            east=area.east,
            enclosed_nodes=len(enclosed),
            source_count=len(sources),
            interpolated=interpolated,
            nearest_source_km=round(nearest_km, 1),
        )

        return AreaClimate(
            profile=profile,
            source_districts=tuple(source.district for source in sources),
            enclosed_node_count=len(enclosed),
            interpolated=interpolated,
            nearest_source_km=round(nearest_km, 1),
        )

    def _interpolation_sources(
        self, latitude: float, longitude: float
    ) -> tuple[tuple[DistrictClimateProfile, ...], list[float]]:
        """The nodes that may ground an interpolated value, and their weights.

        Raises:
            ClimateProfileUnavailableError: If nothing is close enough to qualify.
        """
        ranked = sorted(
            (
                (
                    calculations.haversine_km(
                        latitude, longitude, profile.grid_latitude, profile.grid_longitude
                    ),
                    profile,
                )
                for profile in self._profiles.profiles
            ),
            key=lambda pair: pair[0],
        )

        within = [
            (distance, profile)
            for distance, profile in ranked
            if distance <= constants.MAX_INTERPOLATION_DISTANCE_KM
        ][: constants.MAX_INTERPOLATION_SOURCES]

        if not within:
            nearest_distance, nearest_profile = ranked[0]
            raise ClimateProfileUnavailableError(
                "There is no measured climate near that area, and nothing close "
                "enough to interpolate from. The nearest place we hold data for is "
                f"{nearest_profile.district}, {nearest_distance:,.0f} km away. "
                "Draw your site inside the region we cover.",
                details={
                    "nearest_district": nearest_profile.district,
                    "nearest_distance_km": round(nearest_distance, 1),
                    "max_interpolation_distance_km": constants.MAX_INTERPOLATION_DISTANCE_KM,
                },
            )

        sources = tuple(profile for _, profile in within)
        weights = [
            (
                # A node effectively on top of the query point takes over entirely,
                # rather than producing a division by zero.
                1.0
                / (constants.COINCIDENT_NODE_DISTANCE_KM**constants.INTERPOLATION_DISTANCE_POWER)
                if distance < constants.COINCIDENT_NODE_DISTANCE_KM
                else 1.0 / (distance**constants.INTERPOLATION_DISTANCE_POWER)
            )
            for distance, _ in within
        ]
        return sources, weights

    def _blend(
        self,
        sources: tuple[DistrictClimateProfile, ...],
        weights: list[float],
        centre_lat: float,
        centre_lon: float,
    ) -> DistrictClimateProfile:
        """Combine contributing nodes into one profile for the area."""
        total = sum(weights)

        # strict=True: sources and weights are built together and must stay the same
        # length. If they ever diverge, every blended field would be silently wrong,
        # so this fails loudly instead.
        weighted = tuple(zip(sources, weights, strict=True))

        blended: dict[str, float] = {
            field: sum(getattr(source, field) * weight for source, weight in weighted) / total
            for field in _MEAN_FIELDS
        }
        worst: dict[str, float] = {
            field: max(getattr(source, field) for source in sources) for field in _MAX_FIELDS
        }

        # The shortest record among contributors, because the blended series is only
        # as long as its shortest input. Claiming the longest would overstate it.
        observation_days = min(source.observation_days for source in sources)

        # Named for what it is. This value did not come from one district, so it must
        # not borrow a district's name and pass as that district's reading.
        label = (
            sources[0].district if len(sources) == 1 else f"Selected area ({len(sources)} cells)"
        )

        return DistrictClimateProfile(
            district=label,
            grid_latitude=centre_lat,
            grid_longitude=centre_lon,
            observation_days=observation_days,
            **blended,
            **worst,
        )
