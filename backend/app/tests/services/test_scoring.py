"""Tests for the scoring service's derived figures.

The model is stubbed out: these tests pin down what the service computes from the
rules assessment itself — the service-life estimate and the recommended
specification — which must not depend on any trained artifact.
"""

from __future__ import annotations

import random
from dataclasses import replace
from typing import cast, get_args

import pytest

from app.core import constants
from app.ml.quality_score import ADMIXTURE_FEATURES, WALLING_FEATURE_IDS, QualityScoreModel
from app.repositories.knowledge_base import load_knowledge_base
from app.routes.dependencies import get_scoring_service
from app.services.climate_data import ClimateDataService
from app.services.rules_engine import (
    ClimateSummary,
    ConcreteMix,
    ElementSituation,
    MaterialSelection,
    MemberType,
    assess,
    classify_exposure,
    parse_grade_mpa,
)
from app.services.scoring import QualityScoringService, ScoredSelection

SITUATIONS: tuple[ElementSituation, ...] = get_args(ElementSituation)
MEMBERS: tuple[MemberType, ...] = get_args(MemberType)

HUMID_INLAND = ClimateSummary(
    district="Karur",
    mean_relative_humidity_percent=85.0,
    wetness_index=0.09,
    wet_dry_cycles_per_year=44.0,
    max_wind_gust_ms=15.0,
    mean_max_temperature_c=34.0,
    distance_to_coast_km=176.0,
)


def scored(selection: MaterialSelection, climate: ClimateSummary = HUMID_INLAND) -> ScoredSelection:
    """Score a selection by the rules alone; the model score is irrelevant here."""
    return ScoredSelection(
        selection=selection,
        assessment=assess(climate, selection),
        rules_score=0.0,
        model_score=0.0,
    )


class TestServiceLife:
    """The estimate must respond to every failed requirement, walling included."""

    def test_unsuitable_walling_shortens_the_estimate(self) -> None:
        """Burnt clay brick fails in a humid climate; fly ash brick does not.

        The walling finding reports humidity against a threshold rather than a
        spec against a limit, so deriving its shortfall from those two numbers
        came out negative and the mismatch never reduced the estimate.
        """
        mix = ConcreteMix(grade="M30", cement_content_kg_m3=340, water_cement_ratio=0.45)
        unsuitable = scored(
            MaterialSelection(
                concrete=mix, walling_material_id="burnt_clay_brick", nominal_cover_mm=50.0
            )
        )
        suitable = scored(
            MaterialSelection(
                concrete=mix, walling_material_id="fly_ash_brick", nominal_cover_mm=50.0
            )
        )

        assert not unsuitable.assessment.compliant
        assert suitable.assessment.compliant
        assert unsuitable.service_life_years < suitable.service_life_years

    def test_a_mix_exactly_at_the_limits_gets_the_design_life(self) -> None:
        exposure = classify_exposure(HUMID_INLAND, "exposed").exposure
        mix = ConcreteMix(
            grade=exposure.min_grade,
            cement_content_kg_m3=float(exposure.min_cement_kg_m3),
            water_cement_ratio=exposure.max_water_cement_ratio,
        )

        result = scored(
            MaterialSelection(
                concrete=mix,
                walling_material_id="fly_ash_brick",
                nominal_cover_mm=float(exposure.nominal_cover_mm),
            )
        )

        assert result.service_life_years == pytest.approx(constants.DESIGN_SERVICE_LIFE_YEARS)


class _UnusedModel:
    """Stands in for the trained model, which `recommend` never consults."""

    version = "unused"

    def predict(self, *, summary: ClimateSummary, selection: MaterialSelection) -> float:
        raise AssertionError("recommend() must not depend on the model")


@pytest.fixture
def service() -> QualityScoringService:
    return QualityScoringService(
        climate=ClimateDataService(),
        model=cast(QualityScoreModel, _UnusedModel()),
    )


class TestRecommendation:
    """The recommended specification must clear the class that actually applies."""

    @pytest.mark.parametrize("situation", ["enclosed", "sheltered", "exposed", "buried", "tidal"])
    def test_recommendation_is_compliant_in_every_situation(
        self, service: QualityScoringService, situation: ElementSituation
    ) -> None:
        recommended = service.recommend(HUMID_INLAND, situation)

        assert assess(HUMID_INLAND, recommended).compliant

    def test_indoor_recommendation_is_leaner_than_outdoor(
        self, service: QualityScoringService
    ) -> None:
        """With the situation now mattering, advice for an enclosed column must
        not demand the same mix as an exposed facade."""
        indoor = service.recommend(HUMID_INLAND, "enclosed")
        outdoor = service.recommend(HUMID_INLAND, "exposed")

        assert indoor.concrete.grade == "M20"
        assert outdoor.concrete.grade == "M30"


class TestConventionalBaseline:
    """Recommend-only mode compares the advice against the code's own floor."""

    def test_baseline_is_the_is456_mild_minimum(self) -> None:
        """The constants cite IS 456 Table 5's Mild row; hold them to it, so the
        citation cannot go stale if the transcribed table is ever corrected."""
        mild = load_knowledge_base().exposure_by_id("mild")

        assert constants.CONVENTIONAL_BASELINE_GRADE == mild.min_grade
        assert constants.CONVENTIONAL_BASELINE_CEMENT_KG_M3 == mild.min_cement_kg_m3
        assert constants.CONVENTIONAL_BASELINE_WATER_CEMENT_RATIO == pytest.approx(
            mild.max_water_cement_ratio
        )
        assert constants.CONVENTIONAL_BASELINE_COVER_MM == mild.nominal_cover_mm


class TestCoverRecommendation:
    """The recommendation must clear the cover each member needs, not one figure."""

    @pytest.mark.parametrize("member", constants.MEMBER_TYPES)
    @pytest.mark.parametrize("situation", ["enclosed", "sheltered", "exposed", "buried", "tidal"])
    def test_recommendation_meets_cover_for_every_member(
        self, service: QualityScoringService, situation: ElementSituation, member: MemberType
    ) -> None:
        recommended = service.recommend(HUMID_INLAND, situation, member)

        assert assess(HUMID_INLAND, recommended).compliant
        assert recommended.member == member

    def test_footing_cover_follows_the_member_minimum(self, service: QualityScoringService) -> None:
        """Buried is Moderate (30 mm), but IS 456 cl. 26.4.2.1 needs 50 mm for footings."""
        footing = service.recommend(HUMID_INLAND, "buried", "footing")
        slab = service.recommend(HUMID_INLAND, "buried", "slab")

        assert footing.nominal_cover_mm == 50.0
        assert slab.nominal_cover_mm == 30.0


def spec(
    grade: str,
    cement: float,
    ratio: float,
    cover: float,
    *,
    cement_type: str = "PPC",
    admixtures: tuple[str, ...] = (),
    walling: str = "fly_ash_brick",
) -> MaterialSelection:
    return MaterialSelection(
        concrete=ConcreteMix(
            grade=grade,
            cement_content_kg_m3=cement,
            water_cement_ratio=ratio,
            cement_type=cement_type,
            admixtures=admixtures,
        ),
        walling_material_id=walling,
        nominal_cover_mm=cover,
    )


@pytest.fixture
def real_service() -> QualityScoringService:
    """The production wiring, real model included, for headline-score properties."""
    return get_scoring_service(ClimateDataService())


class TestRecommendationUpgradesTheUsersSpecification:
    """Advice raises a specification where it falls short and never lowers it."""

    def test_an_over_specified_mix_comes_back_unchanged(
        self, service: QualityScoringService
    ) -> None:
        """It used to be "improved" from M45 at 60 mm to M30 at 45 mm."""
        mine = spec("M45", 380.0, 0.35, 60.0)

        assert service.recommend(HUMID_INLAND, "exposed", "beam", base=mine) == mine

    def test_only_what_falls_short_is_raised(self, service: QualityScoringService) -> None:
        mine = spec("M45", 380.0, 0.35, 30.0)

        advised = service.recommend(HUMID_INLAND, "exposed", "beam", base=mine)

        assert advised.concrete == mine.concrete, "a strong mix must not be downgraded"
        assert advised.nominal_cover_mm == 45.0

    def test_no_parameter_moves_the_wrong_way(self, service: QualityScoringService) -> None:
        mine = spec("M25", 300.0, 0.50, 25.0, cement_type="OPC", walling="burnt_clay_brick")

        advised = service.recommend(HUMID_INLAND, "exposed", "beam", base=mine)

        assert parse_grade_mpa(advised.concrete.grade) >= parse_grade_mpa(mine.concrete.grade)
        assert advised.concrete.cement_content_kg_m3 >= mine.concrete.cement_content_kg_m3
        assert advised.concrete.water_cement_ratio <= mine.concrete.water_cement_ratio
        assert advised.nominal_cover_mm >= mine.nominal_cover_mm

    def test_admixtures_are_added_never_removed(self, service: QualityScoringService) -> None:
        mine = spec("M30", 340.0, 0.42, 45.0, admixtures=("waterproofing admixture",))
        coastal = ClimateSummary(
            district="Coast",
            mean_relative_humidity_percent=80.0,
            wetness_index=0.1,
            wet_dry_cycles_per_year=40.0,
            max_wind_gust_ms=20.0,
            mean_max_temperature_c=33.0,
            distance_to_coast_km=5.0,
        )

        advised = service.recommend(coastal, "exposed", "beam", base=mine)

        assert "waterproofing admixture" in advised.concrete.admixtures
        assert "corrosion inhibitor" in advised.concrete.admixtures

    def test_a_suitable_choice_is_kept(self, service: QualityScoringService) -> None:
        """AAC block is not the climate's first pick here, but it is not worse."""
        mine = spec("M30", 340.0, 0.42, 45.0, walling="aac_block")

        advised = service.recommend(HUMID_INLAND, "exposed", "beam", base=mine)

        assert advised.walling_material_id == "aac_block"

    def test_an_unsuitable_choice_is_replaced(self, service: QualityScoringService) -> None:
        """Burnt clay brick fails the humidity check, so the advice swaps it."""
        mine = spec("M30", 340.0, 0.42, 45.0, walling="burnt_clay_brick")

        advised = service.recommend(HUMID_INLAND, "exposed", "beam", base=mine)

        assert advised.walling_material_id != "burnt_clay_brick"

    def test_advice_never_scores_below_the_users_specification(
        self, real_service: QualityScoringService
    ) -> None:
        """Seeded sweep over the input space, on both the rules and the headline score."""
        rng = random.Random(constants.RANDOM_SEED)  # noqa: S311 — a seeded test sweep, not crypto
        climate = ClimateDataService()
        for _ in range(300):
            situation = rng.choice(SITUATIONS)
            member = rng.choice(MEMBERS)
            mine = replace(
                spec(
                    rng.choice(constants.SUPPORTED_CONCRETE_GRADES),
                    rng.choice([250.0, 300.0, 340.0, 400.0, 450.0]),
                    rng.choice([0.32, 0.40, 0.45, 0.55, 0.65]),
                    rng.choice([15.0, 25.0, 40.0, 50.0, 75.0]),
                    cement_type=rng.choice(constants.SUPPORTED_CEMENT_TYPES),
                    admixtures=tuple(
                        rng.sample(list(ADMIXTURE_FEATURES.values()), rng.randint(0, 2))
                    ),
                    walling=rng.choice(list(WALLING_FEATURE_IDS)),
                ),
                element_situation=situation,
                member=member,
            )
            result = real_service.compare(
                district=rng.choice(climate.available_districts),
                proposed=mine,
                situation=situation,
                member=member,
            )

            assert result.recommended.rules_score >= result.proposed.rules_score, mine
            assert result.improvement >= 0, mine
