"""Tests for the IS-code rules engine.

This layer decides what a reviewer would challenge — which exposure class applies
and whether a mix complies — so the tests are written against the standard's own
wording: a Severe class demands M30, 320 kg/m3 and w/c 0.45, and the engine must
say so and explain why.

The Phase 4 model trains on these labels, so a silent change here would propagate
into the score without any test noticing unless it is pinned down.
"""

from __future__ import annotations

import pytest

from app.core import constants
from app.repositories.knowledge_base import KnowledgeBaseError, load_knowledge_base
from app.services.rules_engine import (
    ClimateSummary,
    ConcreteMix,
    MaterialSelection,
    assess,
    check_mix_compliance,
    check_walling_suitability,
    classify_exposure,
    climate_conditions,
    parse_grade_mpa,
)


def climate(
    *,
    humidity: float = 65.0,
    wetness: float = 0.18,
    cycles: float = 20.0,
    gust: float = 15.0,
    temperature: float = 34.0,
    coast_km: float = 200.0,
) -> ClimateSummary:
    """A climate summary with inland-Tamil-Nadu defaults, overridable per test."""
    return ClimateSummary(
        district="Coimbatore",
        mean_relative_humidity_percent=humidity,
        wetness_index=wetness,
        wet_dry_cycles_per_year=cycles,
        max_wind_gust_ms=gust,
        mean_max_temperature_c=temperature,
        distance_to_coast_km=coast_km,
    )


class TestKnowledgeBase:
    """The bundled tables must parse and match the published standard."""

    def test_loads_all_four_tables(self) -> None:
        base = load_knowledge_base()

        assert len(base.exposure_classes) == 5
        assert base.material_recommendations
        assert base.brick_suitability
        assert base.masonry_properties

    @pytest.mark.parametrize(
        ("exposure_id", "grade", "cement", "ratio"),
        [
            ("mild", 20, 300, 0.55),
            ("moderate", 25, 300, 0.50),
            ("severe", 30, 320, 0.45),
            ("very_severe", 35, 340, 0.45),
            ("extreme", 40, 360, 0.40),
        ],
    )
    def test_matches_is456_table_5(
        self, exposure_id: str, grade: int, cement: int, ratio: float
    ) -> None:
        """Transcription check against IS 456 Table 5, row by row."""
        exposure = load_knowledge_base().exposure_by_id(exposure_id)

        assert exposure.min_grade_mpa == grade
        assert exposure.min_cement_kg_m3 == cement
        assert exposure.max_water_cement_ratio == pytest.approx(ratio)

    def test_severity_ordering_is_strictly_increasing(self) -> None:
        """Escalation logic depends on severity being a usable ordinal."""
        severities = [item.severity for item in load_knowledge_base().exposure_classes]
        assert severities == sorted(severities)
        assert len(set(severities)) == len(severities)

    def test_unknown_exposure_class_raises(self) -> None:
        with pytest.raises(KnowledgeBaseError):
            load_knowledge_base().exposure_by_id("apocalyptic")

    def test_severity_lookup_clamps_rather_than_failing(self) -> None:
        """Severity comes from arithmetic, so it must saturate, not explode."""
        base = load_knowledge_base()

        assert base.exposure_by_severity(-3).id == "mild"
        assert base.exposure_by_severity(99).id == "extreme"

    def test_every_recommendation_cites_a_standard(self) -> None:
        """An uncited recommendation is not defensible in a permit context."""
        for recommendation in load_knowledge_base().material_recommendations:
            assert recommendation.standard.strip()


class TestGradeParsing:
    """Grades are compared numerically so M45 correctly clears an M35 requirement."""

    @pytest.mark.parametrize(("label", "expected"), [("M20", 20), ("M30", 30), ("m45", 45)])
    def test_parses_valid_grades(self, label: str, expected: int) -> None:
        assert parse_grade_mpa(label) == expected

    @pytest.mark.parametrize("label", ["", "30", "Grade30", "MM30", "M"])
    def test_rejects_malformed_grades(self, label: str) -> None:
        with pytest.raises(ValueError, match="Unrecognised concrete grade"):
            parse_grade_mpa(label)


class TestExposureClassification:
    """IS 456 Table 3, expressed as thresholds over measured climate."""

    def test_enclosed_element_in_a_benign_climate_is_mild(self) -> None:
        result = classify_exposure(climate(), "enclosed")
        assert result.exposure.id == "mild"

    def test_exposed_element_inland_is_moderate(self) -> None:
        """Baseline for the inland districts this build targets."""
        result = classify_exposure(climate(), "exposed")
        assert result.exposure.id == "moderate"

    def test_shoreline_proximity_forces_very_severe(self) -> None:
        result = classify_exposure(climate(coast_km=0.5), "exposed")
        assert result.exposure.id == "very_severe"

    def test_coastal_band_forces_at_least_severe(self) -> None:
        result = classify_exposure(climate(coast_km=10.0), "exposed")
        assert result.exposure.severity >= 3

    def test_heavy_rain_on_an_exposed_element_is_severe(self) -> None:
        result = classify_exposure(climate(wetness=0.45), "exposed")
        assert result.exposure.id == "severe"

    def test_wet_dry_cycling_is_severe(self) -> None:
        result = classify_exposure(climate(cycles=120.0), "exposed")
        assert result.exposure.id == "severe"

    def test_high_humidity_alone_does_not_escalate_sheltered_element(self) -> None:
        """Mean humidity affects walling suitability, not exposure class by itself."""
        result = classify_exposure(climate(humidity=85.0), "sheltered")
        assert result.exposure.id == "moderate"

    def test_tidal_situation_is_extreme_regardless_of_climate(self) -> None:
        """A benign-looking climate must never downgrade an inherently harsh site."""
        result = classify_exposure(climate(humidity=30.0, wetness=0.02), "tidal")
        assert result.exposure.id == "extreme"

    def test_rain_does_not_escalate_an_enclosed_element(self) -> None:
        """Rainfall is irrelevant to a surface the rain cannot reach."""
        result = classify_exposure(climate(wetness=0.60), "enclosed")
        assert result.exposure.id == "mild"

    def test_reasons_explain_the_verdict(self) -> None:
        """The classification has to be auditable, not just correct."""
        result = classify_exposure(climate(coast_km=5.0), "exposed")

        assert result.reasons
        assert any("coast" in reason.lower() for reason in result.reasons)
        assert any(result.exposure.label in reason for reason in result.reasons)


class TestMixCompliance:
    """IS 456 Table 5 minimums, checked with signed margins."""

    def test_compliant_mix_passes_every_check(self) -> None:
        exposure = load_knowledge_base().exposure_by_id("severe")
        mix = ConcreteMix(grade="M30", cement_content_kg_m3=320, water_cement_ratio=0.45)

        findings = check_mix_compliance(exposure, mix)

        assert all(finding.compliant for finding in findings)
        assert len(findings) == 3

    def test_underspecified_grade_fails(self) -> None:
        exposure = load_knowledge_base().exposure_by_id("severe")
        mix = ConcreteMix(grade="M20", cement_content_kg_m3=320, water_cement_ratio=0.45)

        grade_finding = next(
            f for f in check_mix_compliance(exposure, mix) if f.parameter == "concrete_grade_mpa"
        )

        assert grade_finding.compliant is False
        assert grade_finding.margin_ratio < 0
        assert "below" in grade_finding.message.lower()

    def test_excess_water_cement_ratio_fails(self) -> None:
        """w/c is a maximum, so the comparison runs the other way."""
        exposure = load_knowledge_base().exposure_by_id("severe")
        mix = ConcreteMix(grade="M30", cement_content_kg_m3=320, water_cement_ratio=0.60)

        finding = next(
            f for f in check_mix_compliance(exposure, mix) if f.parameter == "water_cement_ratio"
        )

        assert finding.compliant is False
        assert finding.margin_ratio < 0

    def test_lower_water_cement_ratio_scores_a_positive_margin(self) -> None:
        exposure = load_knowledge_base().exposure_by_id("severe")
        mix = ConcreteMix(grade="M30", cement_content_kg_m3=320, water_cement_ratio=0.35)

        finding = next(
            f for f in check_mix_compliance(exposure, mix) if f.parameter == "water_cement_ratio"
        )

        assert finding.compliant is True
        assert finding.margin_ratio > 0

    def test_margin_scales_with_the_size_of_the_shortfall(self) -> None:
        """A near-miss must read differently from a gross failure."""
        exposure = load_knowledge_base().exposure_by_id("severe")
        near = ConcreteMix(grade="M25", cement_content_kg_m3=320, water_cement_ratio=0.45)
        far = ConcreteMix(grade="M20", cement_content_kg_m3=320, water_cement_ratio=0.45)

        near_margin = next(
            f for f in check_mix_compliance(exposure, near) if f.parameter == "concrete_grade_mpa"
        ).margin_ratio
        far_margin = next(
            f for f in check_mix_compliance(exposure, far) if f.parameter == "concrete_grade_mpa"
        ).margin_ratio

        assert far_margin < near_margin < 0

    def test_stronger_grade_than_required_passes(self) -> None:
        exposure = load_knowledge_base().exposure_by_id("moderate")
        mix = ConcreteMix(grade="M45", cement_content_kg_m3=340, water_cement_ratio=0.40)

        assert all(finding.compliant for finding in check_mix_compliance(exposure, mix))

    def test_every_finding_cites_its_standard(self) -> None:
        exposure = load_knowledge_base().exposure_by_id("very_severe")
        mix = ConcreteMix(grade="M35", cement_content_kg_m3=340, water_cement_ratio=0.45)

        for finding in check_mix_compliance(exposure, mix):
            assert "IS 456" in finding.standard


class TestWallingSuitability:
    """Brick choice is judged against the published climate-suitability table."""

    def test_red_brick_flagged_in_a_humid_climate(self) -> None:
        finding = check_walling_suitability(climate(humidity=85.0), "burnt_clay_brick")

        assert finding is not None
        assert finding.compliant is False

    def test_red_brick_accepted_in_a_dry_climate(self) -> None:
        finding = check_walling_suitability(climate(humidity=55.0), "burnt_clay_brick")

        assert finding is not None
        assert finding.compliant is True

    def test_fly_ash_brick_suits_humidity(self) -> None:
        """Low absorption is exactly what the reference table recommends it for."""
        finding = check_walling_suitability(climate(humidity=85.0), "fly_ash_brick")

        assert finding is not None
        assert finding.compliant is True

    def test_unlisted_material_is_unassessed_not_failed(self) -> None:
        """Absence of data is reported as absence, never as a verdict."""
        assert check_walling_suitability(climate(), "moon_rock") is None


class TestClimateConditions:
    """Recommendations are triggered by measured climate, not a hardcoded map."""

    def test_inland_dry_site_is_not_coastal(self) -> None:
        assert "coastal_marine" not in climate_conditions(climate(coast_km=200.0))

    def test_near_coast_triggers_marine_recommendations(self) -> None:
        assert "coastal_marine" in climate_conditions(climate(coast_km=10.0))

    def test_heavy_rain_triggers_flood_recommendations(self) -> None:
        conditions = climate_conditions(climate(wetness=0.50))

        assert "high_rainfall" in conditions
        assert "flood_prone" in conditions

    def test_design_wind_speed_triggers_cyclone_recommendations(self) -> None:
        conditions = climate_conditions(climate(gust=constants.WIND_REFERENCE_MS + 1))
        assert "high_wind" in conditions

    def test_sustainability_always_offered(self) -> None:
        """Lower-carbon substitution is compatible with every exposure class."""
        assert "sustainability_priority" in climate_conditions(climate())


class TestFullAssessment:
    """End to end: climate plus materials in, explained verdict out."""

    def test_compliant_selection_reports_compliant(self) -> None:
        selection = MaterialSelection(
            concrete=ConcreteMix(grade="M30", cement_content_kg_m3=340, water_cement_ratio=0.42),
            walling_material_id="fly_ash_brick",
            element_situation="exposed",
        )

        result = assess(climate(), selection)

        assert result.compliant is True
        assert not result.unmet

    def test_non_compliant_selection_lists_what_is_wrong(self) -> None:
        selection = MaterialSelection(
            concrete=ConcreteMix(grade="M20", cement_content_kg_m3=280, water_cement_ratio=0.60),
            walling_material_id="burnt_clay_brick",
            element_situation="exposed",
        )

        result = assess(climate(humidity=85.0, wetness=0.45), selection)

        assert result.compliant is False
        assert len(result.unmet) >= 3

    def test_recommendations_reflect_the_measured_climate(self) -> None:
        selection = MaterialSelection(
            concrete=ConcreteMix(grade="M30", cement_content_kg_m3=320, water_cement_ratio=0.45),
            walling_material_id="fly_ash_brick",
        )

        coastal = assess(climate(coast_km=5.0), selection)
        inland = assess(climate(coast_km=300.0), selection)

        coastal_ids = {r.id for r in coastal.applicable_recommendations}
        inland_ids = {r.id for r in inland.applicable_recommendations}

        assert "coastal_psc_ppc" in coastal_ids
        assert "coastal_psc_ppc" not in inland_ids

    def test_detects_a_recommendation_already_followed(self) -> None:
        """Choosing PSC on a coastal site should be credited, not re-recommended."""
        selection = MaterialSelection(
            concrete=ConcreteMix(
                grade="M35",
                cement_content_kg_m3=340,
                water_cement_ratio=0.45,
                cement_type="PSC",
            ),
            walling_material_id="fly_ash_brick",
        )

        result = assess(climate(coast_km=5.0), selection)

        assert "coastal_psc_ppc" in result.followed_recommendation_ids

    def test_assessment_is_deterministic(self) -> None:
        """The Phase 4 labels depend on this being a pure function."""
        selection = MaterialSelection(
            concrete=ConcreteMix(grade="M25", cement_content_kg_m3=310, water_cement_ratio=0.48),
            walling_material_id="aac_block",
        )

        first = assess(climate(), selection)
        second = assess(climate(), selection)

        assert first.assessment.exposure.id == second.assessment.exposure.id
        assert [f.margin_ratio for f in first.findings] == [f.margin_ratio for f in second.findings]
