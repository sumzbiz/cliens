"""Tests for the shared calculations that every score depends on.

These are pure functions, so they are tested at their boundaries: minimum risk,
maximum risk, missing data, and both ends of the 2025-2055 horizon, as the brief
requires.
"""

from __future__ import annotations

import math

import pytest

from app.core import calculations


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

    def test_rejects_nan(self) -> None:
        """NaN used to come back as the upper bound, so it read as a perfect score."""
        with pytest.raises(ValueError, match="NaN"):
            calculations.clamp(math.nan, 0.0, 100.0)

    @pytest.mark.parametrize(("value", "expected"), [(math.inf, 1.0), (-math.inf, 0.0)])
    def test_infinities_clamp_to_the_bounds(self, value: float, expected: float) -> None:
        assert calculations.clamp(value, 0.0, 1.0) == expected


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
