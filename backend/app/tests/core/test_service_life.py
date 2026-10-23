"""Tests for the estimated service life calculation.

This is a code-anchored estimate, not a fitted survival model, so what is tested
is that it behaves the way the reasoning behind it says it should: the code's own
minimums return the code's own design life, better mixes last longer, worse ones
less, and the whole thing stays inside bounds where it still means something.
"""

from __future__ import annotations

import pytest

from app.core import calculations, constants


class TestBaseline:
    """A specification sitting exactly on the code's limits is the anchor."""

    def test_meeting_the_limit_exactly_gives_the_design_life(self) -> None:
        years = calculations.estimated_service_life_years(
            required_water_cement_ratio=0.50,
            provided_water_cement_ratio=0.50,
            worst_other_shortfall_ratio=0.0,
        )

        assert years == pytest.approx(constants.DESIGN_SERVICE_LIFE_YEARS)

    @pytest.mark.parametrize("limit", [0.35, 0.45, 0.55, 0.60])
    def test_the_anchor_holds_at_every_exposure_class(self, limit: float) -> None:
        """Each class has a different w/c limit but the same 50-year target."""
        years = calculations.estimated_service_life_years(
            required_water_cement_ratio=limit,
            provided_water_cement_ratio=limit,
            worst_other_shortfall_ratio=0.0,
        )

        assert years == pytest.approx(constants.DESIGN_SERVICE_LIFE_YEARS)


class TestWaterCementRatio:
    """The dominant lever, and the one with actual physics behind it."""

    def test_a_drier_mix_lasts_longer(self) -> None:
        years = calculations.estimated_service_life_years(
            required_water_cement_ratio=0.50,
            provided_water_cement_ratio=0.40,
            worst_other_shortfall_ratio=0.0,
        )

        assert years > constants.DESIGN_SERVICE_LIFE_YEARS

    def test_a_wetter_mix_lasts_less(self) -> None:
        years = calculations.estimated_service_life_years(
            required_water_cement_ratio=0.50,
            provided_water_cement_ratio=0.60,
            worst_other_shortfall_ratio=0.0,
        )

        assert years < constants.DESIGN_SERVICE_LIFE_YEARS

    def test_the_response_is_exponential_not_linear(self) -> None:
        """Diffusion-controlled ingress means equal steps are not equal losses.

        Guards the shape of the model, not just its direction: a linear stand-in
        would pass the two tests above and still be the wrong curve.
        """
        one_step = calculations.estimated_service_life_years(
            required_water_cement_ratio=0.50,
            provided_water_cement_ratio=0.45,
            worst_other_shortfall_ratio=0.0,
        )
        two_steps = calculations.estimated_service_life_years(
            required_water_cement_ratio=0.50,
            provided_water_cement_ratio=0.40,
            worst_other_shortfall_ratio=0.0,
        )

        gain_first = one_step - constants.DESIGN_SERVICE_LIFE_YEARS
        gain_second = two_steps - one_step
        assert gain_second > gain_first

    def test_monotonic_across_the_usable_range(self) -> None:
        ratios = [0.30, 0.35, 0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70]
        lives = [
            calculations.estimated_service_life_years(
                required_water_cement_ratio=0.50,
                provided_water_cement_ratio=ratio,
                worst_other_shortfall_ratio=0.0,
            )
            for ratio in ratios
        ]

        assert lives == sorted(lives, reverse=True)


class TestShortfallPenalty:
    """Missing a minimum means the 50-year target's assumptions do not hold."""

    def test_a_shortfall_shortens_life(self) -> None:
        compliant = calculations.estimated_service_life_years(
            required_water_cement_ratio=0.50,
            provided_water_cement_ratio=0.50,
            worst_other_shortfall_ratio=0.0,
        )
        deficient = calculations.estimated_service_life_years(
            required_water_cement_ratio=0.50,
            provided_water_cement_ratio=0.50,
            worst_other_shortfall_ratio=0.20,
        )

        assert deficient < compliant

    def test_a_severe_shortfall_does_not_produce_a_negative_life(self) -> None:
        """The penalty can exceed 1.0 before clamping; the result must not invert."""
        years = calculations.estimated_service_life_years(
            required_water_cement_ratio=0.50,
            provided_water_cement_ratio=0.50,
            worst_other_shortfall_ratio=5.0,
        )

        assert years == constants.MIN_ESTIMATED_SERVICE_LIFE_YEARS

    def test_a_negative_shortfall_is_ignored_rather_than_rewarded(self) -> None:
        """Exceeding a minimum is already credited by the score, not twice here."""
        neutral = calculations.estimated_service_life_years(
            required_water_cement_ratio=0.50,
            provided_water_cement_ratio=0.50,
            worst_other_shortfall_ratio=0.0,
        )
        surplus = calculations.estimated_service_life_years(
            required_water_cement_ratio=0.50,
            provided_water_cement_ratio=0.50,
            worst_other_shortfall_ratio=-0.5,
        )

        assert surplus == pytest.approx(neutral)


class TestBounds:
    """Outside these the model stops discriminating and must say so."""

    def test_an_excellent_mix_is_capped(self) -> None:
        years = calculations.estimated_service_life_years(
            required_water_cement_ratio=0.60,
            provided_water_cement_ratio=0.25,
            worst_other_shortfall_ratio=0.0,
        )

        assert years == constants.MAX_ESTIMATED_SERVICE_LIFE_YEARS

    def test_a_terrible_mix_is_floored(self) -> None:
        years = calculations.estimated_service_life_years(
            required_water_cement_ratio=0.35,
            provided_water_cement_ratio=1.20,
            worst_other_shortfall_ratio=0.0,
        )

        assert years == constants.MIN_ESTIMATED_SERVICE_LIFE_YEARS


class TestInterval:
    """A single year would imply precision this cannot support."""

    def test_the_band_brackets_the_estimate(self) -> None:
        lower, upper = calculations.service_life_interval(50.0)

        assert lower < 50.0 < upper

    def test_the_band_is_the_configured_width(self) -> None:
        lower, upper = calculations.service_life_interval(50.0)

        assert lower == pytest.approx(50.0 * (1 - constants.SERVICE_LIFE_UNCERTAINTY_FRACTION))
        assert upper == pytest.approx(50.0 * (1 + constants.SERVICE_LIFE_UNCERTAINTY_FRACTION))

    def test_the_band_never_escapes_the_model_bounds(self) -> None:
        """At the cap the upper bound must not claim more than the model allows."""
        _, upper = calculations.service_life_interval(constants.MAX_ESTIMATED_SERVICE_LIFE_YEARS)
        lower, _ = calculations.service_life_interval(constants.MIN_ESTIMATED_SERVICE_LIFE_YEARS)

        assert upper == constants.MAX_ESTIMATED_SERVICE_LIFE_YEARS
        assert lower == constants.MIN_ESTIMATED_SERVICE_LIFE_YEARS
