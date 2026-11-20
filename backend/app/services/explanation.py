"""Plain-language explanations of a score, written by Gemini from the engine's figures.

Gemini never computes anything here. It is handed the assessment the rules engine
already produced — the checks, the score, the service life and the advised
changes — and asked to say what they mean for the person building. Every number
in what comes back is then checked against that assessment; an explanation
containing a figure that cannot be traced to it is discarded, not shown. In a
permit context a fluent sentence with an invented number is worse than none.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any

from app.core import constants
from app.core.exceptions import ExternalServiceError
from app.core.logging import get_logger
from app.external import gemini
from app.services.area_climate import AreaBounds
from app.services.rules_engine import ElementSituation, MaterialSelection, MemberType
from app.services.scoring import QualityScoringService, ScoreComparison, ScoredSelection

logger = get_logger(__name__)

NUMBER = re.compile(r"\d+(?:\.\d+)?")

RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "OBJECT",
    "properties": {
        "summary": {"type": "STRING"},
        "points": {"type": "ARRAY", "items": {"type": "STRING"}},
    },
    "required": ["summary", "points"],
}

PROMPT = """You explain a concrete durability assessment to a builder in Tamil Nadu.
The assessment below was computed by an IS 456:2000 rules engine. Do not compute,
estimate or introduce anything: use only the facts given, and use no number that
does not appear in them. Write plain English for someone who is not an engineer.

Return JSON with:
- "summary": two or three sentences on what the result means for this build.
- "points": up to five short bullet points, most important first: each failed check
  and why it matters, then each recommended change and what it buys.

Assessment:
{facts}
"""


@dataclass(frozen=True, slots=True)
class Explanation:
    """A generated explanation, verified against the assessment it explains."""

    summary: str
    points: tuple[str, ...]
    model: str


_CACHE: OrderedDict[str, Explanation] = OrderedDict()


class ExplanationService:
    """Scores a specification, then has Gemini explain the result."""

    def __init__(self, *, scoring: QualityScoringService, api_key: str | None, model: str) -> None:
        """Bind the service to the scoring engine and the Gemini configuration."""
        self._scoring = scoring
        self._api_key = api_key
        self._model = model

    async def explain_district(
        self,
        *,
        district: str,
        proposed: MaterialSelection | None,
        situation: ElementSituation,
        member: MemberType,
    ) -> Explanation:
        """Explain the score for a named district."""
        comparison = self._scoring.compare(
            district=district, proposed=proposed, situation=situation, member=member
        )
        return await self.explain(comparison, situation=situation, member=member)

    async def explain_area(
        self,
        *,
        area: AreaBounds,
        proposed: MaterialSelection | None,
        situation: ElementSituation,
        member: MemberType,
    ) -> Explanation:
        """Explain the score for a drawn area."""
        comparison, _ = self._scoring.compare_area(
            area=area, proposed=proposed, situation=situation, member=member
        )
        return await self.explain(comparison, situation=situation, member=member)

    async def explain(
        self,
        comparison: ScoreComparison,
        *,
        situation: ElementSituation,
        member: MemberType,
    ) -> Explanation:
        """Explain one comparison, from cache when it has been explained before.

        Raises:
            ExternalServiceUnconfiguredError: If Gemini has no API key.
            ExternalServiceError: If Gemini fails, or its explanation contains a
                figure that is not in the assessment.
        """
        facts = assessment_facts(comparison, situation=situation, member=member)
        encoded = json.dumps(facts, sort_keys=True)
        key = hashlib.sha256(f"{self._model}\n{encoded}".encode()).hexdigest()
        cached = _CACHE.get(key)
        if cached is not None:
            _CACHE.move_to_end(key)
            return cached

        reply = await gemini.generate_json(
            api_key=self._api_key,
            model=self._model,
            prompt=PROMPT.format(facts=json.dumps(facts, indent=2)),
            response_schema=RESPONSE_SCHEMA,
        )
        explanation = _verified(reply, facts, model=self._model)

        _CACHE[key] = explanation
        while len(_CACHE) > constants.EXPLANATION_CACHE_ENTRIES:
            _CACHE.popitem(last=False)
        logger.info(
            "explanation_generated", district=comparison.district, points=len(explanation.points)
        )
        return explanation


def assessment_facts(
    comparison: ScoreComparison, *, situation: ElementSituation, member: MemberType
) -> dict[str, Any]:
    """The figures an explanation may use: exactly what the engine computed."""
    proposed, recommended = comparison.proposed, comparison.recommended
    return {
        "site": comparison.district,
        "exposure_class": comparison.exposure.label,
        "element_situation": situation,
        "member": member,
        "your_score_out_of_100": round(proposed.score, 1),
        "recommended_score_out_of_100": round(recommended.score, 1),
        "points_gained_by_recommendation": comparison.improvement,
        "your_estimated_service_life_years": round(proposed.service_life_years, 1),
        "recommended_estimated_service_life_years": round(recommended.service_life_years, 1),
        "code_design_life_years": constants.DESIGN_SERVICE_LIFE_YEARS,
        "checks": [
            {
                "check": finding.label,
                "required": finding.required,
                "provided": finding.provided,
                "met": finding.compliant,
                "standard": finding.standard,
                "finding": finding.message,
            }
            for finding in proposed.assessment.findings
        ],
        "recommended_changes": _changes(proposed, recommended),
    }


def _changes(proposed: ScoredSelection, recommended: ScoredSelection) -> list[dict[str, str]]:
    """Each parameter the recommendation changes, as builder-readable text."""
    yours, ours = proposed.selection, recommended.selection
    pairs = [
        ("concrete grade", yours.concrete.grade, ours.concrete.grade),
        (
            "cement content",
            f"{yours.concrete.cement_content_kg_m3:.0f} kg/m3",
            f"{ours.concrete.cement_content_kg_m3:.0f} kg/m3",
        ),
        (
            "water/cement ratio",
            f"{yours.concrete.water_cement_ratio:.2f}",
            f"{ours.concrete.water_cement_ratio:.2f}",
        ),
        ("cement type", yours.concrete.cement_type, ours.concrete.cement_type),
        (
            "admixtures",
            ", ".join(yours.concrete.admixtures) or "none",
            ", ".join(ours.concrete.admixtures) or "none",
        ),
        ("concrete cover", f"{yours.nominal_cover_mm:.0f} mm", f"{ours.nominal_cover_mm:.0f} mm"),
        (
            "walling",
            yours.walling_material_id.replace("_", " "),
            ours.walling_material_id.replace("_", " "),
        ),
    ]
    return [{"parameter": name, "from": a, "to": b} for name, a, b in pairs if a != b]


def _numbers_in(value: object) -> list[float]:
    """Every number appearing anywhere in a JSON-like value, including inside text."""
    if isinstance(value, bool):
        return []
    if isinstance(value, int | float):
        return [float(value)]
    if isinstance(value, str):
        return [float(match) for match in NUMBER.findall(value)]
    if isinstance(value, dict):
        return [n for item in value.values() for n in _numbers_in(item)]
    if isinstance(value, list | tuple):
        return [n for item in value for n in _numbers_in(item)]
    return []


def _verified(reply: dict[str, Any], facts: dict[str, Any], *, model: str) -> Explanation:
    """Check the reply's shape and that every number in it comes from the facts.

    Raises:
        ExternalServiceError: If the reply is malformed or cites an untraced figure.
    """
    summary = reply.get("summary")
    points = reply.get("points")
    if not isinstance(summary, str) or not isinstance(points, list):
        raise ExternalServiceError("Gemini's explanation had the wrong shape.", service="gemini")
    if not all(isinstance(point, str) for point in points):
        raise ExternalServiceError("Gemini's explanation had the wrong shape.", service="gemini")

    allowed = _numbers_in(facts)
    untraced = sorted(
        {
            number
            for number in _numbers_in([summary, *points])
            if not any(
                abs(number - known) <= constants.EXPLANATION_NUMBER_TOLERANCE for known in allowed
            )
        }
    )
    if untraced:
        logger.warning("explanation_rejected_untraced_numbers", untraced=untraced)
        raise ExternalServiceError(
            "The generated explanation cited figures that are not in the assessment, "
            "so it was discarded.",
            service="gemini",
            details={"untraced_numbers": untraced},
        )
    return Explanation(summary=summary, points=tuple(points), model=model)
