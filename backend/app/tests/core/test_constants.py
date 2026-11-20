"""Tests for the internal consistency of the constants table.

Tables that must agree with each other — member types and their minimum cover,
the supported grades and the conventional baseline — are asserted directly, so an
edit to one that forgets the other fails here rather than as a KeyError in a score.
"""

from __future__ import annotations

import pytest

from app.core import constants


class TestCoverTables:
    """Every member the API accepts must have a minimum cover, and only those."""

    def test_member_minimums_cover_exactly_the_member_types(self) -> None:
        assert set(constants.MEMBER_MINIMUM_COVER_MM) == set(constants.MEMBER_TYPES)

    def test_member_minimums_are_non_negative(self) -> None:
        assert all(value >= 0 for value in constants.MEMBER_MINIMUM_COVER_MM.values())

    def test_ceiling_clears_the_deepest_table_16_requirement(self) -> None:
        """Extreme exposure needs 75 mm; the accepted ceiling must not reject it."""
        assert constants.MAX_NOMINAL_COVER_MM > 75.0


class TestSupportedInputs:
    """The conventional baseline must be a specification the API itself accepts."""

    def test_baseline_grade_is_supported(self) -> None:
        assert constants.CONVENTIONAL_BASELINE_GRADE in constants.SUPPORTED_CONCRETE_GRADES

    def test_baseline_cement_type_is_supported(self) -> None:
        assert constants.CONVENTIONAL_BASELINE_CEMENT_TYPE in constants.SUPPORTED_CEMENT_TYPES

    def test_supported_grades_ascend(self) -> None:
        strengths = [int(grade[1:]) for grade in constants.SUPPORTED_CONCRETE_GRADES]
        assert strengths == sorted(strengths)


class TestBounds:
    """Paired bounds that would silently invert a check if swapped."""

    def test_year_bounds_are_ordered(self) -> None:
        assert constants.HORIZON_START_YEAR < constants.HORIZON_END_YEAR

    def test_floor_area_bounds_are_ordered(self) -> None:
        assert constants.MIN_FLOOR_AREA_SQ_FT < constants.MAX_FLOOR_AREA_SQ_FT

    def test_service_life_bounds_bracket_the_design_life(self) -> None:
        assert (
            constants.MIN_ESTIMATED_SERVICE_LIFE_YEARS
            < constants.DESIGN_SERVICE_LIFE_YEARS
            < constants.MAX_ESTIMATED_SERVICE_LIFE_YEARS
        )


class TestValidateConstants:
    """The startup check passes as shipped and catches each inconsistency."""

    def test_passes_on_the_shipped_values(self) -> None:
        constants.validate_constants()

    def test_detects_a_member_without_a_minimum(self, monkeypatch: pytest.MonkeyPatch) -> None:
        broken = dict(constants.MEMBER_MINIMUM_COVER_MM)
        del broken["column"]
        monkeypatch.setattr(constants, "MEMBER_MINIMUM_COVER_MM", broken)

        with pytest.raises(ValueError, match="MEMBER_MINIMUM_COVER_MM"):
            constants.validate_constants()

    def test_detects_an_unsupported_baseline_grade(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(constants, "CONVENTIONAL_BASELINE_GRADE", "M999")

        with pytest.raises(ValueError, match="CONVENTIONAL_BASELINE_GRADE"):
            constants.validate_constants()

    def test_detects_an_unsupported_baseline_cement(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(constants, "CONVENTIONAL_BASELINE_CEMENT_TYPE", "XYZ")

        with pytest.raises(ValueError, match="CONVENTIONAL_BASELINE_CEMENT_TYPE"):
            constants.validate_constants()

    @pytest.mark.parametrize("cover", [0.0, -5.0, 500.0])
    def test_detects_an_implausible_baseline_cover(
        self, monkeypatch: pytest.MonkeyPatch, cover: float
    ) -> None:
        monkeypatch.setattr(constants, "CONVENTIONAL_BASELINE_COVER_MM", cover)

        with pytest.raises(ValueError, match="CONVENTIONAL_BASELINE_COVER_MM"):
            constants.validate_constants()

    def test_detects_a_tts_chunk_over_the_api_limit(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            constants, "SARVAM_CHUNK_TARGET_CHARACTERS", constants.SARVAM_MAX_TEXT_CHARACTERS
        )

        with pytest.raises(ValueError, match="SARVAM_CHUNK_TARGET_CHARACTERS"):
            constants.validate_constants()
