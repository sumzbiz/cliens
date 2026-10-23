"""Tests for the internal consistency of the constants table.

A weighting table that stopped summing to 1.0 would bias every score in a way no
single-function test would notice, so the invariants are asserted directly.
"""

from __future__ import annotations

import pytest

from app.core import constants


class TestWeightTables:
    """The weights are what make a stress of 1.0 mean "the full reference load"."""

    def test_component_weights_sum_to_one(self) -> None:
        assert sum(constants.COMPONENT_WEIGHTS.values()) == pytest.approx(1.0)

    def test_component_weights_cover_exactly_the_known_components(self) -> None:
        assert set(constants.COMPONENT_WEIGHTS) == set(constants.BUILDING_COMPONENTS)

    @pytest.mark.parametrize("component", constants.BUILDING_COMPONENTS)
    def test_hazard_sensitivities_sum_to_one_per_component(self, component: str) -> None:
        assert sum(constants.COMPONENT_HAZARD_SENSITIVITY[component].values()) == pytest.approx(1.0)

    @pytest.mark.parametrize("component", constants.BUILDING_COMPONENTS)
    def test_hazard_sensitivities_cover_every_hazard(self, component: str) -> None:
        assert set(constants.COMPONENT_HAZARD_SENSITIVITY[component]) == set(constants.HAZARDS)

    def test_all_weights_are_non_negative(self) -> None:
        assert all(weight >= 0 for weight in constants.COMPONENT_WEIGHTS.values())


class TestHorizon:
    """The 2025-2055 window is the product's stated scope."""

    def test_horizon_is_ordered(self) -> None:
        assert constants.HORIZON_START_YEAR < constants.HORIZON_END_YEAR

    def test_horizon_years_are_contiguous_and_inclusive(self) -> None:
        assert constants.HORIZON_YEARS[0] == constants.HORIZON_START_YEAR
        assert constants.HORIZON_YEARS[-1] == constants.HORIZON_END_YEAR
        assert len(constants.HORIZON_YEARS) == (
            constants.HORIZON_END_YEAR - constants.HORIZON_START_YEAR + 1
        )


class TestThresholds:
    """Bounds that keep derived values physically meaningful."""

    def test_uninsurable_ratio_lies_strictly_inside_the_damage_range(self) -> None:
        assert constants.MIN_DAMAGE_RATIO < constants.UNINSURABLE_DAMAGE_RATIO
        assert constants.UNINSURABLE_DAMAGE_RATIO < constants.MAX_DAMAGE_RATIO

    def test_floor_area_bounds_are_ordered(self) -> None:
        assert constants.MIN_FLOOR_AREA_SQ_FT < constants.MAX_FLOOR_AREA_SQ_FT

    def test_reference_area_lies_within_the_supported_bounds(self) -> None:
        assert (
            constants.MIN_FLOOR_AREA_SQ_FT
            <= constants.REFERENCE_FLOOR_AREA_SQ_FT
            <= constants.MAX_FLOOR_AREA_SQ_FT
        )

    def test_confidence_interval_bounds_are_ordered(self) -> None:
        assert constants.MIN_CONFIDENCE_INTERVAL_WIDTH < constants.MAX_CONFIDENCE_INTERVAL_WIDTH

    def test_confidence_labels_are_in_ascending_width_order(self) -> None:
        widths = [width for _, width in constants.CONFIDENCE_LABEL_THRESHOLDS_YEARS]
        assert widths == sorted(widths)

    def test_final_confidence_label_is_unbounded(self) -> None:
        """Otherwise `confidence_label` would not be a total function."""
        assert constants.CONFIDENCE_LABEL_THRESHOLDS_YEARS[-1][1] == float("inf")


class TestCycloneCategories:
    """IMD category bounds must ascend for the classifier to work."""

    def test_lower_bounds_ascend(self) -> None:
        bounds = [bound for _, bound in constants.IMD_CYCLONE_CATEGORIES_KMPH]
        assert bounds == sorted(bounds)

    def test_category_names_are_unique(self) -> None:
        names = [name for name, _ in constants.IMD_CYCLONE_CATEGORIES_KMPH]
        assert len(names) == len(set(names))


class TestValidateConstants:
    """`validate_constants` runs at startup and must actually catch drift."""

    def test_passes_on_the_shipped_values(self) -> None:
        constants.validate_constants()

    def test_detects_component_weights_that_stop_summing_to_one(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        broken = dict(constants.COMPONENT_WEIGHTS)
        broken["roofing"] += 0.1
        monkeypatch.setattr(constants, "COMPONENT_WEIGHTS", broken)

        with pytest.raises(ValueError, match="COMPONENT_WEIGHTS must sum to 1.0"):
            constants.validate_constants()

    def test_detects_hazard_sensitivities_that_stop_summing_to_one(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        broken = {
            component: dict(sensitivities)
            for component, sensitivities in constants.COMPONENT_HAZARD_SENSITIVITY.items()
        }
        broken["walls"]["wind"] += 0.2
        monkeypatch.setattr(constants, "COMPONENT_HAZARD_SENSITIVITY", broken)

        with pytest.raises(ValueError, match="must sum to 1.0"):
            constants.validate_constants()

    def test_detects_a_missing_component(self, monkeypatch: pytest.MonkeyPatch) -> None:
        broken = dict(constants.COMPONENT_WEIGHTS)
        del broken["walls"]
        monkeypatch.setattr(constants, "COMPONENT_WEIGHTS", broken)

        with pytest.raises(ValueError, match="COMPONENT_WEIGHTS"):
            constants.validate_constants()

    def test_detects_an_inverted_horizon(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(constants, "HORIZON_START_YEAR", 2060)
        with pytest.raises(ValueError, match="HORIZON_START_YEAR must be before"):
            constants.validate_constants()

    def test_detects_an_out_of_range_uninsurability_threshold(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(constants, "UNINSURABLE_DAMAGE_RATIO", 1.5)
        with pytest.raises(ValueError, match="must lie strictly within"):
            constants.validate_constants()
