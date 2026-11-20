"""Tests for the scoring service's derived figures.

The model is stubbed out: these tests pin down what the service computes from the
rules assessment itself — the service-life estimate and the recommended
specification — which must not depend on any trained artifact.
"""

from __future__ import annotations

from typing import cast

import pytest

from app.core import constants
from app.ml.quality_score import QualityScoreModel
from app.services.climate_data import ClimateDataService
from app.services.rules_engine import (
    ClimateSummary,
    ConcreteMix,
    ElementSituation,
    MaterialSelection,
    assess,
    classify_exposure,
)
from app.services.scoring import QualityScoringService, ScoredSelection

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
        unsuitable = scored(MaterialSelection(mix, "burnt_clay_brick", "exposed"))
        suitable = scored(MaterialSelection(mix, "fly_ash_brick", "exposed"))

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

        result = scored(MaterialSelection(mix, "fly_ash_brick", "exposed"))

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
