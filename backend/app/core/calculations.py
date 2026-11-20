"""Shared pure calculations — the single source of truth for maths used more than once.

Everything here is a pure function of its arguments: no I/O, no clocks, no randomness,
no globals beyond the constants module. That is what makes ``/score`` reproducible,
and it means each function is directly unit-testable at its boundaries.

Anything in this module that is used by both the score engine and the re-score path
exists exactly once, per the DRY rules in CLAUDE.md.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final

from app.core import constants


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------
def clamp(value: float, minimum: float, maximum: float) -> float:
    """Constrain ``value`` to the inclusive range ``[minimum, maximum]``.

    Raises:
        ValueError: If the range is inverted, which would silently return nonsense.
    """
    if minimum > maximum:
        raise ValueError(f"invalid clamp range: minimum {minimum} exceeds maximum {maximum}")
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


def kmph_to_ms(speed_kmph: float) -> float:
    """Convert kilometres per hour to metres per second.

    IMD publishes cyclone wind speeds in km/h. Every internal wind calculation is in
    m/s, so IMD values are converted at the client boundary and never afterwards.
    """
    return speed_kmph * constants.MS_PER_KMPH


def ms_to_kmph(speed_ms: float) -> float:
    """Convert metres per second to kilometres per hour.

    Used when presenting a wind speed alongside an IMD cyclone category, which is
    defined in km/h.
    """
    return speed_ms / constants.MS_PER_KMPH


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


def wet_bulb_temperature_c(temperature_c: float, relative_humidity_percent: float) -> float:
    """Estimate wet-bulb temperature from dry-bulb temperature and relative humidity.

    Uses the empirical fit from Stull, R. (2011), "Wet-Bulb Temperature from
    Relative Humidity and Air Temperature", Journal of Applied Meteorology and
    Climatology 50(11):2267-2269. It is accurate to about ±1 °C over the range
    that matters here, and needs only the two variables CMIP6 publishes directly,
    avoiding an extra pressure assumption.

    Args:
        temperature_c: Dry-bulb temperature in degrees Celsius.
        relative_humidity_percent: Relative humidity as a percentage, 0-100.

    Returns:
        Wet-bulb temperature in degrees Celsius.

    Raises:
        ValueError: If relative humidity is outside 0-100.
    """
    if not 0.0 <= relative_humidity_percent <= 100.0:
        raise ValueError(
            f"relative_humidity_percent must be within [0, 100], "
            f"got {relative_humidity_percent}"
        )

    humidity = relative_humidity_percent
    # math.pow rather than `**`: the ** operator is typed as returning Any for
    # float bases (it can yield a complex result for a negative base), which would
    # silently widen this function's return type.
    return (
        temperature_c * math.atan(0.151977 * math.sqrt(humidity + 8.313659))
        + math.atan(temperature_c + humidity)
        - math.atan(humidity - 1.676331)
        + 0.00391838 * math.pow(humidity, 1.5) * math.atan(0.023101 * humidity)
        - 4.686035
    )


def classify_cyclone_category(wind_speed_ms: float) -> str:
    """Return the IMD cyclone category for a sustained wind speed.

    Args:
        wind_speed_ms: Sustained surface wind speed in metres per second.

    Bounds are treated as inclusive within a tolerance, because converting the
    internal m/s value back to km/h is not exact in binary floating point.

    Returns:
        The IMD category name, or ``"Below Depression"`` for speeds under the
        weakest classified band.
    """
    speed_kmph = ms_to_kmph(wind_speed_ms)
    category = "Below Depression"
    for name, lower_bound_kmph in constants.IMD_CYCLONE_CATEGORIES_KMPH:
        if speed_kmph >= lower_bound_kmph - constants.CYCLONE_CATEGORY_BOUNDARY_TOLERANCE_KMPH:
            category = name
        else:
            break
    return category


# ---------------------------------------------------------------------------
# Hazard normalisation
# ---------------------------------------------------------------------------
def normalise_hazard_intensity(projected_value: float, reference_value: float) -> float:
    """Express a projected hazard value as a dimensionless intensity.

    An intensity of 1.0 means the projection sits exactly at the reference severity
    (the design wind speed, the "extremely heavy rainfall" threshold, and so on).
    The result is clamped to ``MAX_NORMALISED_HAZARD_INTENSITY`` because the damage
    relationship is not resolved by the calibration data beyond that point.

    Args:
        projected_value: Projected hazard value, in the hazard's own unit.
        reference_value: The reference severity for that hazard, same unit.

    Raises:
        ValueError: If ``reference_value`` is not positive.
    """
    if reference_value <= 0:
        raise ValueError(f"reference_value must be positive, got {reference_value}")
    intensity = projected_value / reference_value
    return clamp(intensity, 0.0, constants.MAX_NORMALISED_HAZARD_INTENSITY)


# ---------------------------------------------------------------------------
# Resistance-weighted stress — the core shared calculation
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class StressContribution:
    """One component's contribution to total structural stress.

    Attributes:
        component: Building component name (foundation, walls, roofing).
        hazard_contributions: Stress contributed by each hazard, already weighted
            by the component's weight and its sensitivity to that hazard.
        total: Sum of ``hazard_contributions``.
    """

    component: str
    hazard_contributions: Mapping[str, float]
    total: float


@dataclass(frozen=True, slots=True)
class StressBreakdown:
    """A fully auditable decomposition of structural stress.

    The brief requires every score to be traceable to the inputs that produced it,
    so the engine carries this structure rather than a bare number.

    Attributes:
        total: Overall dimensionless stress across all components and hazards.
        by_component: Per-component decomposition, in ``BUILDING_COMPONENTS`` order.
        by_hazard: Total stress attributable to each hazard across all components.
    """

    total: float
    by_component: tuple[StressContribution, ...]
    by_hazard: Mapping[str, float]


def resistance_weighted_stress(
    hazard_intensities: Mapping[str, float],
    component_resistances: Mapping[str, Mapping[str, float]],
) -> StressBreakdown:
    """Combine hazard intensities with material resistance into structural stress.

    For each component ``c`` and hazard ``h``::

        contribution(c, h) = weight(c) x sensitivity(c, h) x intensity(h) x (1 - resistance(c, h))

    The ``(1 - resistance)`` term is the share of the load the material fails to
    resist. Total stress is the sum over every component and hazard, so a stress of
    0 means every hazard is fully resisted and higher values mean more load reaches
    the structure.

    This function is the only place this relationship is expressed. The baseline
    score and the re-scored "prove" path both call it, which is what guarantees the
    two are comparable.

    Args:
        hazard_intensities: Dimensionless intensity per hazard, keyed by the names
            in ``constants.HAZARDS``. Typically from ``normalise_hazard_intensity``.
        component_resistances: Resistance in ``[0, 1]`` per component per hazard,
            keyed by ``constants.BUILDING_COMPONENTS`` then ``constants.HAZARDS``.

    Returns:
        A full breakdown; ``StressBreakdown.total`` is the scalar stress.

    Raises:
        ValueError: If a hazard or component is missing, or a resistance falls
            outside ``[0, 1]``. Missing data is never treated as zero — that would
            quietly understate risk.
    """
    missing_hazards = set(constants.HAZARDS) - set(hazard_intensities)
    if missing_hazards:
        raise ValueError(f"missing hazard intensities: {sorted(missing_hazards)}")

    missing_components = set(constants.BUILDING_COMPONENTS) - set(component_resistances)
    if missing_components:
        raise ValueError(f"missing component resistances: {sorted(missing_components)}")

    contributions: list[StressContribution] = []
    hazard_totals: dict[str, float] = dict.fromkeys(constants.HAZARDS, 0.0)

    for component in constants.BUILDING_COMPONENTS:
        component_weight = constants.COMPONENT_WEIGHTS[component]
        sensitivities = constants.COMPONENT_HAZARD_SENSITIVITY[component]
        resistances = component_resistances[component]

        missing_resistances = set(constants.HAZARDS) - set(resistances)
        if missing_resistances:
            raise ValueError(
                f"component {component!r} is missing resistances for "
                f"{sorted(missing_resistances)}"
            )

        per_hazard: dict[str, float] = {}
        for hazard in constants.HAZARDS:
            resistance = resistances[hazard]
            if not 0.0 <= resistance <= 1.0:
                raise ValueError(
                    f"resistance for {component!r}/{hazard!r} must be in [0, 1], got {resistance}"
                )
            unresisted_share = 1.0 - resistance
            contribution = (
                component_weight
                * sensitivities[hazard]
                * hazard_intensities[hazard]
                * unresisted_share
            )
            per_hazard[hazard] = contribution
            hazard_totals[hazard] += contribution

        contributions.append(
            StressContribution(
                component=component,
                hazard_contributions=per_hazard,
                total=sum(per_hazard.values()),
            )
        )

    return StressBreakdown(
        total=sum(c.total for c in contributions),
        by_component=tuple(contributions),
        by_hazard=hazard_totals,
    )


# ---------------------------------------------------------------------------
# Exposure scaling
# ---------------------------------------------------------------------------
def area_exposure_factor(area_sq_ft: float) -> float:
    """Scale stress by floor area, relative to a reference footprint.

    A larger building presents more envelope to wind and more slab to flooding, but
    damage ratio scales far more weakly than area does. A logarithmic term captures
    that: a building at the reference area scores 1.0, one at ten times the
    reference scores only modestly higher.

    Args:
        area_sq_ft: Floor area in square feet.

    Returns:
        A multiplier applied to total stress; 1.0 at the reference area.

    Raises:
        ValueError: If the area is outside the supported bounds.
    """
    if not constants.MIN_FLOOR_AREA_SQ_FT <= area_sq_ft <= constants.MAX_FLOOR_AREA_SQ_FT:
        raise ValueError(
            f"area_sq_ft must be within "
            f"[{constants.MIN_FLOOR_AREA_SQ_FT}, {constants.MAX_FLOOR_AREA_SQ_FT}], "
            f"got {area_sq_ft}"
        )
    ratio = area_sq_ft / constants.REFERENCE_FLOOR_AREA_SQ_FT
    return 1.0 + constants.AREA_EXPOSURE_COEFFICIENT * math.log10(ratio)


# ---------------------------------------------------------------------------
# Threshold crossing
# ---------------------------------------------------------------------------
def is_uninsurable(damage_ratio: float) -> bool:
    """Whether a damage ratio is at or above the uninsurability threshold."""
    return damage_ratio >= constants.UNINSURABLE_DAMAGE_RATIO


def first_crossing_year(damage_ratio_by_year: Mapping[int, float]) -> int | None:
    """Find the earliest year whose damage ratio reaches the uninsurable threshold.

    This is the Climate Lien Score itself. Years are evaluated in ascending order, so
    a projection that dips back below the threshold later does not move the score —
    once a site is uninsurable it does not become financeable again.

    Args:
        damage_ratio_by_year: Damage ratio for each year in the horizon.

    Returns:
        The first crossing year, or ``None`` if the threshold is never reached
        within the horizon. ``None`` means "survives the horizon", which callers
        must present distinctly from a late crossing year.

    Raises:
        ValueError: If the mapping is empty, or any year lies outside the horizon.
    """
    if not damage_ratio_by_year:
        raise ValueError("damage_ratio_by_year must not be empty")

    out_of_range = [
        year
        for year in damage_ratio_by_year
        if not constants.HORIZON_START_YEAR <= year <= constants.HORIZON_END_YEAR
    ]
    if out_of_range:
        raise ValueError(
            f"years outside the horizon "
            f"[{constants.HORIZON_START_YEAR}, {constants.HORIZON_END_YEAR}]: "
            f"{sorted(out_of_range)}"
        )

    for year in sorted(damage_ratio_by_year):
        if is_uninsurable(damage_ratio_by_year[year]):
            return year
    return None


def clamp_damage_ratio(value: float) -> float:
    """Constrain a predicted damage ratio to its physically meaningful range.

    A regression model can extrapolate outside ``[0, 1]``; a damage ratio outside
    that range is meaningless, so predictions are clamped before use.
    """
    return clamp(value, constants.MIN_DAMAGE_RATIO, constants.MAX_DAMAGE_RATIO)


# ---------------------------------------------------------------------------
# Uncertainty reporting
# ---------------------------------------------------------------------------
def confidence_label(interval_width_years: float) -> str:
    """Map an uncertainty band width on the crossing year to a qualitative label.

    Args:
        interval_width_years: Width of the confidence interval, in years.

    Raises:
        ValueError: If the width is negative.
    """
    if interval_width_years < 0:
        raise ValueError(f"interval_width_years must be non-negative, got {interval_width_years}")
    for label, upper_bound in constants.CONFIDENCE_LABEL_THRESHOLDS_YEARS:
        if interval_width_years <= upper_bound:
            return label
    # Unreachable: the final threshold is infinity. Kept so the function is total.
    return constants.CONFIDENCE_LABEL_THRESHOLDS_YEARS[-1][0]


def confidence_interval(point_estimate: float, standard_error: float) -> tuple[float, float]:
    """Build a two-sided 95% interval around a prediction.

    The half-width is clamped so the reported band is never narrower than the model
    can justify nor so wide as to be useless.

    Args:
        point_estimate: The model's prediction.
        standard_error: Standard error of that prediction, from ensemble spread.

    Returns:
        ``(lower, upper)`` bounds.

    Raises:
        ValueError: If ``standard_error`` is negative.
    """
    if standard_error < 0:
        raise ValueError(f"standard_error must be non-negative, got {standard_error}")
    half_width = clamp(
        constants.CONFIDENCE_INTERVAL_Z_SCORE * standard_error,
        constants.MIN_CONFIDENCE_INTERVAL_WIDTH / 2.0,
        constants.MAX_CONFIDENCE_INTERVAL_WIDTH / 2.0,
    )
    return point_estimate - half_width, point_estimate + half_width


# ---------------------------------------------------------------------------
# Estimated service life
# ---------------------------------------------------------------------------
def estimated_service_life_years(
    *,
    required_water_cement_ratio: float,
    provided_water_cement_ratio: float,
    worst_other_shortfall_ratio: float,
) -> float:
    """Years of service life this specification implies, from the code's baseline.

    Anchored at ``DESIGN_SERVICE_LIFE_YEARS``: a mix sitting exactly on its
    exposure class's limits returns exactly that, because those limits are what
    the 50-year target is written to deliver.

    Two adjustments move it from there:

    * The water/cement term. Corrosion onset is diffusion-controlled and the
      diffusion coefficient rises exponentially with w/c, so life scales as
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
        worst_other_shortfall_ratio: How far the worst of the *other* durability
            parameters falls below its minimum, as a non-negative fraction of
            that minimum. Zero when everything else complies.

    Returns:
        Years, clamped to the bounds in ``constants``.
    """
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

    years = constants.DESIGN_SERVICE_LIFE_YEARS * diffusion_factor * shortfall_factor
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


# ---------------------------------------------------------------------------
# Cache keys
# ---------------------------------------------------------------------------
_COORDINATE_PRECISION: Final[int] = constants.CACHE_COORDINATE_PRECISION_DP


def round_coordinate(value: float) -> float:
    """Round a coordinate to the cache's spatial precision.

    Two sites within about a metre of each other resolve to the same cache key and
    reuse one upstream response. The precision is far finer than any climate grid
    cell, so this cannot merge genuinely different climate conditions.
    """
    return round(value, _COORDINATE_PRECISION)
