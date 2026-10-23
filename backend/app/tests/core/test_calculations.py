"""Tests for the shared calculations that every score depends on.

These are pure functions, so they are tested at their boundaries: minimum risk,
maximum risk, missing data, and both ends of the 2025-2055 horizon, as the brief
requires.
"""

from __future__ import annotations

import math

import pytest

from app.core import calculations, constants


class TestClamp:
    """``clamp`` underpins every bounded quantity in the engine."""

    @pytest.mark.parametrize(
        ("value", "expected"),
        [(-5.0, 0.0), (0.0, 0.0), (0.5, 0.5), (1.0, 1.0), (7.0, 1.0)],
    )
    def test_constrains_to_range(self, value: float, expected: float) -> None:
        assert calculations.clamp(value, 0.0, 1.0) == expected

    def test_rejects_inverted_range(self) -> None:
        """An inverted range would silently return the wrong bound."""
        with pytest.raises(ValueError, match="invalid clamp range"):
            calculations.clamp(0.5, 1.0, 0.0)


class TestUnitConversion:
    """Unit mistakes are the failure mode the brief calls out most explicitly."""

    def test_square_foot_conversion_matches_the_international_definition(self) -> None:
        # 1 sq ft is exactly 0.09290304 sq m (1 inch == 25.4 mm exactly).
        assert calculations.sq_feet_to_sq_metres(1.0) == pytest.approx(0.09290304)

    def test_area_conversion_round_trips(self) -> None:
        original_sq_ft = 2000.0
        round_tripped = calculations.sq_metres_to_sq_feet(
            calculations.sq_feet_to_sq_metres(original_sq_ft)
        )
        assert round_tripped == pytest.approx(original_sq_ft)

    def test_kmph_to_ms_matches_known_value(self) -> None:
        # 36 km/h is exactly 10 m/s.
        assert calculations.kmph_to_ms(36.0) == pytest.approx(10.0)

    def test_wind_speed_round_trips(self) -> None:
        assert calculations.ms_to_kmph(calculations.kmph_to_ms(118.0)) == pytest.approx(118.0)


class TestCycloneClassification:
    """IMD categories are defined on km/h thresholds; the engine works in m/s."""

    @pytest.mark.parametrize(
        ("speed_kmph", "expected"),
        [
            (10.0, "Below Depression"),
            (31.0, "Depression"),
            (62.0, "Cyclonic Storm"),
            (118.0, "Very Severe Cyclonic Storm"),
            (165.0, "Very Severe Cyclonic Storm"),
            (166.0, "Extremely Severe Cyclonic Storm"),
            (222.0, "Super Cyclonic Storm"),
            (300.0, "Super Cyclonic Storm"),
        ],
    )
    def test_classifies_at_category_boundaries(self, speed_kmph: float, expected: str) -> None:
        speed_ms = calculations.kmph_to_ms(speed_kmph)
        assert calculations.classify_cyclone_category(speed_ms) == expected


class TestHazardNormalisation:
    """Normalised intensity is what makes three different hazards comparable."""

    def test_reference_value_normalises_to_one(self) -> None:
        result = calculations.normalise_hazard_intensity(
            constants.WIND_REFERENCE_MS, constants.WIND_REFERENCE_MS
        )
        assert result == pytest.approx(1.0)

    def test_clamps_at_the_ceiling(self) -> None:
        """Beyond the ceiling the calibration data no longer resolves damage."""
        result = calculations.normalise_hazard_intensity(1_000.0, constants.WIND_REFERENCE_MS)
        assert result == constants.MAX_NORMALISED_HAZARD_INTENSITY

    def test_zero_projection_is_zero_intensity(self) -> None:
        assert calculations.normalise_hazard_intensity(0.0, constants.WIND_REFERENCE_MS) == 0.0

    def test_rejects_non_positive_reference(self) -> None:
        with pytest.raises(ValueError, match="reference_value must be positive"):
            calculations.normalise_hazard_intensity(50.0, 0.0)


def _resistances(value: float) -> dict[str, dict[str, float]]:
    """Build a uniform resistance table across every component and hazard."""
    return {
        component: dict.fromkeys(constants.HAZARDS, value)
        for component in constants.BUILDING_COMPONENTS
    }


class TestResistanceWeightedStress:
    """The core shared calculation behind both the baseline and improved scores."""

    def test_full_resistance_gives_zero_stress(self) -> None:
        """Minimum risk: a material that resists everything transmits no load."""
        intensities = dict.fromkeys(constants.HAZARDS, 1.0)
        breakdown = calculations.resistance_weighted_stress(intensities, _resistances(1.0))
        assert breakdown.total == pytest.approx(0.0)

    def test_no_resistance_at_reference_intensity_gives_unit_stress(self) -> None:
        """Maximum-information case: weights sum to 1, so stress equals intensity.

        This is the property that makes the numbers interpretable — a stress of 1.0
        means "the whole reference load reaches the structure".
        """
        intensities = dict.fromkeys(constants.HAZARDS, 1.0)
        breakdown = calculations.resistance_weighted_stress(intensities, _resistances(0.0))
        assert breakdown.total == pytest.approx(1.0)

    def test_zero_intensity_gives_zero_stress(self) -> None:
        intensities = dict.fromkeys(constants.HAZARDS, 0.0)
        breakdown = calculations.resistance_weighted_stress(intensities, _resistances(0.0))
        assert breakdown.total == pytest.approx(0.0)

    def test_breakdown_components_sum_to_the_total(self) -> None:
        """The breakdown is the audit trail; it must reconcile exactly."""
        intensities = {"wind": 1.5, "flood": 0.4, "heat": 0.9}
        breakdown = calculations.resistance_weighted_stress(intensities, _resistances(0.3))

        assert sum(c.total for c in breakdown.by_component) == pytest.approx(breakdown.total)
        assert sum(breakdown.by_hazard.values()) == pytest.approx(breakdown.total)

    def test_breakdown_covers_every_component_and_hazard(self) -> None:
        intensities = dict.fromkeys(constants.HAZARDS, 1.0)
        breakdown = calculations.resistance_weighted_stress(intensities, _resistances(0.5))

        assert {c.component for c in breakdown.by_component} == set(constants.BUILDING_COMPONENTS)
        for contribution in breakdown.by_component:
            assert set(contribution.hazard_contributions) == set(constants.HAZARDS)

    def test_more_resistance_never_increases_stress(self) -> None:
        """Monotonicity: improving materials must never make the score worse.

        The whole "apply suggested materials" feature depends on this holding.
        """
        intensities = {"wind": 1.2, "flood": 0.8, "heat": 0.6}
        weak = calculations.resistance_weighted_stress(intensities, _resistances(0.2)).total
        strong = calculations.resistance_weighted_stress(intensities, _resistances(0.8)).total
        assert strong < weak

    def test_missing_hazard_is_an_error_not_a_zero(self) -> None:
        """Missing data must not be silently treated as "no hazard"."""
        with pytest.raises(ValueError, match="missing hazard intensities"):
            calculations.resistance_weighted_stress({"wind": 1.0}, _resistances(0.5))

    def test_missing_component_is_an_error(self) -> None:
        intensities = dict.fromkeys(constants.HAZARDS, 1.0)
        partial = {"roofing": dict.fromkeys(constants.HAZARDS, 0.5)}
        with pytest.raises(ValueError, match="missing component resistances"):
            calculations.resistance_weighted_stress(intensities, partial)

    def test_missing_resistance_for_one_hazard_is_an_error(self) -> None:
        intensities = dict.fromkeys(constants.HAZARDS, 1.0)
        resistances = _resistances(0.5)
        del resistances["walls"]["heat"]
        with pytest.raises(ValueError, match="is missing resistances for"):
            calculations.resistance_weighted_stress(intensities, resistances)

    @pytest.mark.parametrize("bad_resistance", [-0.1, 1.1])
    def test_rejects_resistance_outside_the_unit_interval(self, bad_resistance: float) -> None:
        intensities = dict.fromkeys(constants.HAZARDS, 1.0)
        with pytest.raises(ValueError, match=r"must be in \[0, 1\]"):
            calculations.resistance_weighted_stress(intensities, _resistances(bad_resistance))


class TestAreaExposureFactor:
    """Area scales exposure weakly; the reference footprint is the anchor."""

    def test_reference_area_is_neutral(self) -> None:
        factor = calculations.area_exposure_factor(constants.REFERENCE_FLOOR_AREA_SQ_FT)
        assert factor == pytest.approx(1.0)

    def test_ten_times_the_reference_adds_one_coefficient(self) -> None:
        factor = calculations.area_exposure_factor(constants.REFERENCE_FLOOR_AREA_SQ_FT * 10)
        assert factor == pytest.approx(1.0 + constants.AREA_EXPOSURE_COEFFICIENT)

    def test_smaller_than_reference_reduces_exposure(self) -> None:
        assert calculations.area_exposure_factor(constants.REFERENCE_FLOOR_AREA_SQ_FT / 10) < 1.0

    @pytest.mark.parametrize(
        "area_sq_ft",
        [
            constants.MIN_FLOOR_AREA_SQ_FT - 1,
            constants.MAX_FLOOR_AREA_SQ_FT + 1,
            0.0,
        ],
    )
    def test_rejects_areas_outside_supported_bounds(self, area_sq_ft: float) -> None:
        with pytest.raises(ValueError, match="area_sq_ft must be within"):
            calculations.area_exposure_factor(area_sq_ft)

    @pytest.mark.parametrize(
        "area_sq_ft", [constants.MIN_FLOOR_AREA_SQ_FT, constants.MAX_FLOOR_AREA_SQ_FT]
    )
    def test_accepts_the_bounds_themselves(self, area_sq_ft: float) -> None:
        assert math.isfinite(calculations.area_exposure_factor(area_sq_ft))


class TestUninsurabilityThreshold:
    """The threshold is the single most consequential number in the product."""

    def test_exactly_at_the_threshold_counts_as_uninsurable(self) -> None:
        assert calculations.is_uninsurable(constants.UNINSURABLE_DAMAGE_RATIO)

    def test_just_below_the_threshold_does_not(self) -> None:
        assert not calculations.is_uninsurable(constants.UNINSURABLE_DAMAGE_RATIO - 1e-9)

    @pytest.mark.parametrize(
        ("value", "expected"),
        [(-0.5, 0.0), (0.0, 0.0), (0.42, 0.42), (1.0, 1.0), (1.7, 1.0)],
    )
    def test_damage_ratio_is_clamped_to_its_physical_range(
        self, value: float, expected: float
    ) -> None:
        assert calculations.clamp_damage_ratio(value) == expected


class TestFirstCrossingYear:
    """This function *is* the Climate Lien Score."""

    def test_minimum_risk_never_crosses(self) -> None:
        """A site that stays safe returns None, not the final year."""
        safe = dict.fromkeys(constants.HORIZON_YEARS, 0.0)
        assert calculations.first_crossing_year(safe) is None

    def test_maximum_risk_crosses_in_the_first_year(self) -> None:
        doomed = dict.fromkeys(constants.HORIZON_YEARS, 1.0)
        assert calculations.first_crossing_year(doomed) == constants.HORIZON_START_YEAR

    def test_crossing_exactly_at_the_start_boundary(self) -> None:
        ratios = dict.fromkeys(constants.HORIZON_YEARS, 0.0)
        ratios[constants.HORIZON_START_YEAR] = constants.UNINSURABLE_DAMAGE_RATIO
        assert calculations.first_crossing_year(ratios) == constants.HORIZON_START_YEAR

    def test_crossing_exactly_at_the_end_boundary(self) -> None:
        ratios = dict.fromkeys(constants.HORIZON_YEARS, 0.0)
        ratios[constants.HORIZON_END_YEAR] = constants.UNINSURABLE_DAMAGE_RATIO
        assert calculations.first_crossing_year(ratios) == constants.HORIZON_END_YEAR

    def test_returns_the_earliest_crossing_when_risk_later_recedes(self) -> None:
        """Once uninsurable, a site does not become financeable again."""
        ratios = dict.fromkeys(constants.HORIZON_YEARS, 0.0)
        ratios[2030] = 0.9
        ratios[2031] = 0.0
        ratios[2040] = 0.9
        assert calculations.first_crossing_year(ratios) == 2030

    def test_evaluates_years_in_ascending_order_regardless_of_input_order(self) -> None:
        ratios = {2040: 0.9, 2025: 0.0, 2033: 0.9}
        assert calculations.first_crossing_year(ratios) == 2033

    def test_rejects_empty_input(self) -> None:
        with pytest.raises(ValueError, match="must not be empty"):
            calculations.first_crossing_year({})

    @pytest.mark.parametrize(
        "year", [constants.HORIZON_START_YEAR - 1, constants.HORIZON_END_YEAR + 1]
    )
    def test_rejects_years_outside_the_horizon(self, year: int) -> None:
        with pytest.raises(ValueError, match="outside the horizon"):
            calculations.first_crossing_year({year: 0.9})


class TestConfidenceReporting:
    """The brief forbids presenting a point estimate as certain."""

    @pytest.mark.parametrize(
        ("width_years", "expected"),
        [(0.0, "high"), (3.0, "high"), (3.1, "moderate"), (7.0, "moderate"), (7.1, "low")],
    )
    def test_labels_at_threshold_boundaries(self, width_years: float, expected: str) -> None:
        assert calculations.confidence_label(width_years) == expected

    def test_rejects_negative_width(self) -> None:
        with pytest.raises(ValueError, match="must be non-negative"):
            calculations.confidence_label(-1.0)

    def test_interval_is_never_narrower_than_the_floor(self) -> None:
        """A zero standard error must not be reported as perfect certainty."""
        lower, upper = calculations.confidence_interval(0.5, 0.0)
        assert upper - lower == pytest.approx(constants.MIN_CONFIDENCE_INTERVAL_WIDTH)

    def test_interval_is_never_wider_than_the_ceiling(self) -> None:
        lower, upper = calculations.confidence_interval(0.5, 100.0)
        assert upper - lower == pytest.approx(constants.MAX_CONFIDENCE_INTERVAL_WIDTH)

    def test_interval_is_centred_on_the_estimate(self) -> None:
        lower, upper = calculations.confidence_interval(0.42, 0.05)
        assert (lower + upper) / 2 == pytest.approx(0.42)

    def test_rejects_negative_standard_error(self) -> None:
        with pytest.raises(ValueError, match="must be non-negative"):
            calculations.confidence_interval(0.5, -0.1)


class TestCacheCoordinateRounding:
    """Cache keys must merge near-identical sites without merging distinct ones."""

    def test_rounds_to_the_configured_precision(self) -> None:
        assert calculations.round_coordinate(80.270721234) == pytest.approx(80.27072)

    def test_sites_a_metre_apart_share_a_key(self) -> None:
        # 1e-6 degrees is roughly 0.1 m, finer than the 5 dp cache precision.
        assert calculations.round_coordinate(80.270721) == calculations.round_coordinate(80.2707214)

    def test_sites_far_apart_do_not_share_a_key(self) -> None:
        assert calculations.round_coordinate(80.27072) != calculations.round_coordinate(80.28072)
