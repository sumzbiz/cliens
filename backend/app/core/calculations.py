"""Shared pure calculations — the single source of truth for maths used more than once.

Everything here is a pure function of its arguments: no I/O, no clocks, no randomness,
no globals beyond the constants module. That is what makes ``/score`` reproducible,
and it means each function is directly unit-testable at its boundaries.

Anything in this module that more than one caller relies on — the score engine,
the service-life estimate, the climate pipeline — exists exactly once, per the DRY
rules in CLAUDE.md.
"""

from __future__ import annotations

import math

from app.core import constants


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------
def clamp(value: float, minimum: float, maximum: float) -> float:
    """Constrain ``value`` to the inclusive range ``[minimum, maximum]``.

    Raises:
        ValueError: If the range is inverted, or ``value`` is NaN. Either would
            silently return nonsense: ``min``/``max`` never select a NaN, so it
            came back as ``maximum`` — a NaN prediction would have been reported
            as a perfect score.
    """
    if minimum > maximum:
        raise ValueError(f"invalid clamp range: minimum {minimum} exceeds maximum {maximum}")
    if math.isnan(value):
        raise ValueError("cannot clamp NaN")
    return max(minimum, min(maximum, value))


# ---------------------------------------------------------------------------
# Unit conversion
# ---------------------------------------------------------------------------
def sq_metres_to_sq_feet(area_sq_m: float) -> float:
    """Convert square metres to square feet.

    PostGIS geography areas come back in square metres; the product's user-facing
    unit is square feet.
    """
    return area_sq_m * constants.SQ_FEET_PER_SQ_METRE


def sq_feet_to_sq_metres(area_sq_ft: float) -> float:
    """Convert square feet to square metres."""
    return area_sq_ft * constants.SQ_METRES_PER_SQ_FOOT


def kelvin_to_celsius(temperature_k: float) -> float:
    """Convert kelvin to degrees Celsius.

    CMIP6 temperature bands (``tas``, ``tasmax``) are published in kelvin; every
    internal temperature is in Celsius.
    """
    return temperature_k - constants.KELVIN_TO_CELSIUS_OFFSET


def precipitation_flux_to_mm_per_day(flux_kg_m2_s: float) -> float:
    """Convert a CMIP6 precipitation flux to millimetres per day.

    The ``pr`` band is a mass flux in kg m-2 s-1. For liquid water that is
    numerically equal to mm/s, so a day's depth is the flux times the seconds in a
    day.
    """
    return flux_kg_m2_s * constants.SECONDS_PER_DAY


def relative_humidity_from_dewpoint(temperature_c: float, dewpoint_c: float) -> float:
    """Derive relative humidity from air temperature and dewpoint.

    ERA5 publishes 2 m temperature and 2 m dewpoint but not relative humidity, and
    humidity is what drives the corrosion and durability rules in IS 456. This uses
    the August-Roche-Magnus approximation with the Alduchov & Eskridge (1996)
    coefficients, taking the ratio of saturation vapour pressure at the dewpoint to
    that at the air temperature.

    Args:
        temperature_c: Air temperature in degrees Celsius.
        dewpoint_c: Dewpoint temperature in degrees Celsius.

    Returns:
        Relative humidity as a percentage, clamped to ``[0, 100]``.

    The clamp matters: dewpoint can exceed air temperature by a hair in reanalysis
    output, which would otherwise yield a physically impossible value above 100%.
    """
    a = constants.MAGNUS_COEFFICIENT_A
    b = constants.MAGNUS_COEFFICIENT_B_C
    numerator = math.exp((a * dewpoint_c) / (b + dewpoint_c))
    denominator = math.exp((a * temperature_c) / (b + temperature_c))
    return clamp(100.0 * numerator / denominator, 0.0, 100.0)


def metres_to_millimetres(depth_m: float) -> float:
    """Convert a precipitation depth from metres to millimetres.

    ERA5 reports total precipitation in metres; the internal unit is millimetres.
    """
    return depth_m * constants.MM_PER_METRE


def wind_speed_from_components(eastward_ms: float, northward_ms: float) -> float:
    """Combine u/v wind components into a scalar speed.

    ERA5 gives wind as orthogonal components. Magnitude is what loading depends on;
    direction is not used by the score.
    """
    return math.hypot(eastward_ms, northward_ms)


# ---------------------------------------------------------------------------
# Estimated service life
# ---------------------------------------------------------------------------
def estimated_service_life_years(
    *,
    required_water_cement_ratio: float,
    provided_water_cement_ratio: float,
    required_cover_mm: float,
    provided_cover_mm: float,
    worst_other_shortfall_ratio: float,
) -> float:
    """Years of service life this specification implies, from the code's baseline.

    Anchored at ``DESIGN_SERVICE_LIFE_YEARS``: a specification sitting exactly on
    its exposure class's limits returns exactly that, because those limits are
    what the 50-year target is written to deliver.

    Three adjustments move it from there:

    * The cover term. Corrosion starts once chlorides or the carbonation front
      cross the cover. Both advance with the square root of time — Fick's second
      law for chloride ingress, ``x = K * sqrt(t)`` for carbonation — so the time
      to cross a cover ``c`` grows with ``c**2``, and life scales as
      ``(provided / required) ** 2``. Halving the cover quarters the time.
    * The water/cement term. That ingress is diffusion-controlled and the
      diffusion coefficient rises exponentially with w/c, so life also scales as
      ``exp(k * (required - provided))``. Beating the limit buys time; exceeding
      it loses time, and steeply.
    * The shortfall term. Missing the minimum grade or cement content means the
      concrete does not meet the assumptions behind that target at all, so a
      further proportional reduction applies. Only the worst of those parameters
      counts — deficiencies here are not independent, and multiplying them would
      compound the same underlying problem twice.

    Args:
        required_water_cement_ratio: The exposure class maximum.
        provided_water_cement_ratio: What the specification proposes.
        required_cover_mm: The nominal cover the member needs.
        provided_cover_mm: The nominal cover the specification proposes.
        worst_other_shortfall_ratio: How far the worst of the *other* durability
            parameters (grade, cement content, walling) falls below its minimum,
            as a non-negative fraction of that minimum. Zero when they comply.

    Returns:
        Years, clamped to the bounds in ``constants``.

    Raises:
        ValueError: If either cover is not positive.
    """
    if required_cover_mm <= 0 or provided_cover_mm <= 0:
        raise ValueError(
            f"covers must be positive, got required={required_cover_mm}, "
            f"provided={provided_cover_mm}"
        )
    cover_factor = math.pow(provided_cover_mm / required_cover_mm, 2)
    diffusion_factor = math.exp(
        constants.INGRESS_WATER_CEMENT_SENSITIVITY
        * (required_water_cement_ratio - provided_water_cement_ratio)
    )

    # clamp: a shortfall worse than the penalty can absorb would otherwise drive
    # the factor negative and flip the sign of the estimate.
    shortfall_factor = clamp(
        1.0 - constants.SERVICE_LIFE_SHORTFALL_PENALTY * max(worst_other_shortfall_ratio, 0.0),
        0.0,
        1.0,
    )

    years = constants.DESIGN_SERVICE_LIFE_YEARS * cover_factor * diffusion_factor * shortfall_factor
    return clamp(
        years,
        constants.MIN_ESTIMATED_SERVICE_LIFE_YEARS,
        constants.MAX_ESTIMATED_SERVICE_LIFE_YEARS,
    )


def service_life_interval(years: float) -> tuple[float, float]:
    """The plausible band around a service life estimate.

    Returned alongside the point value because a single year would imply a
    precision this model cannot support: two structures built to identical
    specifications diverge by decades on workmanship and cover accuracy alone.
    Bounded by the same limits as the estimate, so the band never extends past
    where the model stops meaning anything.
    """
    spread = years * constants.SERVICE_LIFE_UNCERTAINTY_FRACTION
    return (
        clamp(
            years - spread,
            constants.MIN_ESTIMATED_SERVICE_LIFE_YEARS,
            constants.MAX_ESTIMATED_SERVICE_LIFE_YEARS,
        ),
        clamp(
            years + spread,
            constants.MIN_ESTIMATED_SERVICE_LIFE_YEARS,
            constants.MAX_ESTIMATED_SERVICE_LIFE_YEARS,
        ),
    )


# ---------------------------------------------------------------------------
# Geodesy
# ---------------------------------------------------------------------------
def haversine_km(
    latitude_a: float,
    longitude_a: float,
    latitude_b: float,
    longitude_b: float,
) -> float:
    """Great-circle distance between two WGS84 points, in kilometres.

    Spherical rather than ellipsoidal. The error against WGS84 is under 0.5%, which
    at the distances this is used for — a pin against a grid node tens of
    kilometres away — is far below the 27 km cell it is being compared to.

    A planar approximation is deliberately not used: it degrades with latitude and
    fails outright across the antimeridian, and this runs on pins the user may drop
    anywhere on the globe, not only inside the observed region.
    """
    lat_a_rad = math.radians(latitude_a)
    lat_b_rad = math.radians(latitude_b)
    delta_lat = math.radians(latitude_b - latitude_a)
    delta_lon = math.radians(longitude_b - longitude_a)

    inner = (
        math.sin(delta_lat / 2.0) ** 2
        + math.cos(lat_a_rad) * math.cos(lat_b_rad) * math.sin(delta_lon / 2.0) ** 2
    )
    # clamp guards against a floating-point result marginally above 1.0 for
    # coincident points, which would make asin raise.
    return 2.0 * constants.EARTH_MEAN_RADIUS_KM * math.asin(math.sqrt(clamp(inner, 0.0, 1.0)))
