"""Tests for the explanation service: Gemini is faked, the scoring engine is real."""

from __future__ import annotations

from collections import OrderedDict
from typing import Any

import pytest

from app.core.exceptions import ExternalServiceError
from app.external import gemini
from app.routes.dependencies import get_scoring_service
from app.services import explanation
from app.services.climate_data import ClimateDataService
from app.services.explanation import Explanation, ExplanationService, assessment_facts
from app.services.rules_engine import ConcreteMix, MaterialSelection

pytestmark = pytest.mark.anyio

WEAK = MaterialSelection(
    concrete=ConcreteMix(grade="M20", cement_content_kg_m3=290, water_cement_ratio=0.58),
    walling_material_id="burnt_clay_brick",
    nominal_cover_mm=25,
)


class FakeGemini:
    """Stands in for ``gemini.generate_json`` and records each prompt."""

    def __init__(self, reply: dict[str, Any]) -> None:
        self.reply = reply
        self.prompts: list[str] = []

    async def __call__(self, **kwargs: object) -> dict[str, Any]:
        self.prompts.append(str(kwargs["prompt"]))
        return self.reply


@pytest.fixture(autouse=True)
def fresh_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    """Each test starts with an empty explanation cache."""
    monkeypatch.setattr(explanation, "_CACHE", OrderedDict())


def _install(monkeypatch: pytest.MonkeyPatch, reply: dict[str, Any]) -> FakeGemini:
    fake = FakeGemini(reply)
    monkeypatch.setattr(gemini, "generate_json", fake)
    return fake


def _service() -> ExplanationService:
    return ExplanationService(
        scoring=get_scoring_service(ClimateDataService()), api_key="key", model="m"
    )


async def _explain(service: ExplanationService) -> Explanation:
    return await service.explain_district(
        district="Coimbatore", proposed=WEAK, situation="exposed", member="beam"
    )


class TestNumbersAreVerified:
    """Every figure in the text must come from the engine's assessment."""

    async def test_figures_from_the_assessment_are_accepted(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _install(
            monkeypatch,
            {"summary": "A 25 mm cover is short of the code.", "points": ["Use M30 or better."]},
        )

        result = await _explain(_service())

        assert result.summary.startswith("A 25 mm")
        assert result.points == ("Use M30 or better.",)

    async def test_an_invented_figure_discards_the_explanation(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _install(monkeypatch, {"summary": "This will last 137 years.", "points": []})

        with pytest.raises(ExternalServiceError) as caught:
            await _explain(_service())
        assert caught.value.details["untraced_numbers"] == [137.0]

    async def test_the_wrong_shape_is_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _install(monkeypatch, {"summary": "fine", "points": "not a list"})

        with pytest.raises(ExternalServiceError):
            await _explain(_service())


class TestDeterminism:
    """Asking twice returns the same text without asking Gemini twice."""

    async def test_a_repeat_is_served_from_cache(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake = _install(monkeypatch, {"summary": "Short of the code.", "points": []})
        service = _service()

        first = await _explain(service)
        second = await _explain(service)

        assert first == second
        assert len(fake.prompts) == 1


class TestFacts:
    """The prompt carries the engine's figures and the advised changes."""

    def test_facts_list_every_check_and_each_change(self) -> None:
        comparison = get_scoring_service(ClimateDataService()).compare(
            district="Coimbatore", proposed=WEAK, situation="exposed", member="beam"
        )

        facts = assessment_facts(comparison, situation="exposed", member="beam")

        assert len(facts["checks"]) == len(comparison.proposed.assessment.findings)
        changed = {change["parameter"] for change in facts["recommended_changes"]}
        assert {"concrete grade", "water/cement ratio", "concrete cover"} <= changed
        assert facts["your_score_out_of_100"] == round(comparison.proposed.score, 1)


class TestScoreScale:
    """The scale a score is out of is a fact, so prose may name it."""

    async def test_out_of_100_is_traceable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _install(monkeypatch, {"summary": "Your mix scores near 0 out of 100.", "points": []})

        result = await _explain(_service())

        assert "out of 100" in result.summary
