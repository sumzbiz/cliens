"""The Building Quality Score engine.

Combines a district's measured climate with a proposed material specification to
produce a 0-100 score, and always computes both sides of the comparison:

* **evaluate** — score the materials the user proposes;
* **recommend** — derive a compliant specification for that district.

Whichever mode is asked for, the other is computed too, so a before/after is
always available. That is cheap because the recommendation is *derived* from the
exposure class rather than searched for, which also makes it compliant by
construction and its reasoning the standard itself.

The score is rules-derived. ``rules_engine.quality_score_label`` defines it; the ML
model smooths that definition and supplies the headline figure, with the rules
value returned alongside so the two can be compared. Neither is evidence about
real building outcomes.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.core import calculations, constants
from app.core.logging import get_logger
from app.ml.quality_score import QualityScoreModel
from app.repositories.district_profiles import DistrictClimateProfile
from app.repositories.knowledge_base import ExposureClass, KnowledgeBase, load_knowledge_base
from app.services.area_climate import AreaBounds, AreaClimate, AreaClimateService
from app.services.climate_data import ClimateDataService
from app.services.rules_engine import (
    ClimateSummary,
    ConcreteMix,
    ElementSituation,
    MaterialSelection,
    RulesAssessment,
    assess,
    classify_exposure,
    quality_score_label,
)

logger = get_logger(__name__)

# Cement types satisfying the marine recommendations, per IS 456's guidance on
# chloride and sulphate resistance.
MARINE_CEMENT = "PSC"
DEFAULT_CEMENT = "PPC"

# Walling preference by climate, from the reference table's "best suited climate"
# column, most preferred first.
HUMID_WALLING = ("fly_ash_brick", "concrete_solid_block", "aac_block")
HOT_WALLING = ("aac_block", "fly_ash_brick", "concrete_solid_block")


@dataclass(frozen=True, slots=True)
class ScoredSelection:
    """One material specification, scored and explained."""

    selection: MaterialSelection
    assessment: RulesAssessment
    rules_score: float
    model_score: float

    @property
    def score(self) -> float:
        """The headline figure: the model's smoothed value."""
        return self.model_score

    @property
    def band(self) -> str:
        """Plain-language verdict for the score."""
        for label, upper in constants.SCORE_BAND_THRESHOLDS:
            if self.score <= upper:
                return label
        return constants.SCORE_BAND_THRESHOLDS[-1][0]

    @property
    def service_life_years(self) -> float:
        """Estimated years of service, from the code's own 50-year baseline.

        Derived from the compliance findings rather than recomputed from the
        specification: the rules engine has already resolved which exposure class
        applies and what it demands, and asking that question twice is how the two
        answers drift apart.
        """
        # Seeded so that, if the w/c finding were ever absent, required equals
        # provided and the diffusion term is exactly 1.0 — the estimate falls back
        # to the plain design life rather than to an invented ratio that would
        # silently claim the mix is better or worse than the code's baseline.
        provided_ratio = self.selection.concrete.water_cement_ratio
        required_ratio = provided_ratio
        worst_shortfall = 0.0

        for finding in self.assessment.findings:
            if finding.parameter == "water_cement_ratio":
                required_ratio = finding.required
                provided_ratio = finding.provided
            elif not finding.compliant and finding.required > 0:
                # Shortfall as a positive fraction of what was required. The
                # walling check reports a suitability score on the same footing,
                # so it counts here too — an unsuitable wall in a wet climate is a
                # durability problem, not a cosmetic one.
                shortfall = (finding.required - finding.provided) / finding.required
                worst_shortfall = max(worst_shortfall, shortfall)

        return calculations.estimated_service_life_years(
            required_water_cement_ratio=required_ratio,
            provided_water_cement_ratio=provided_ratio,
            worst_other_shortfall_ratio=worst_shortfall,
        )

    @property
    def service_life_interval(self) -> tuple[float, float]:
        """Plausible band around ``service_life_years``."""
        return calculations.service_life_interval(self.service_life_years)


@dataclass(frozen=True, slots=True)
class ScoreComparison:
    """Before and after, always both present."""

    district: str
    climate: DistrictClimateProfile
    exposure: ExposureClass
    exposure_reasons: tuple[str, ...]
    proposed: ScoredSelection
    recommended: ScoredSelection
    provenance: dict[str, str]
    model_version: str

    @property
    def improvement(self) -> float:
        """Points the recommended specification adds over the proposed one."""
        return round(self.recommended.score - self.proposed.score, 1)


class QualityScoringService:
    """Scores material specifications against a district's measured climate."""

    def __init__(
        self,
        *,
        climate: ClimateDataService,
        model: QualityScoreModel,
        knowledge_base: KnowledgeBase | None = None,
        area: AreaClimateService | None = None,
    ) -> None:
        """Bind the engine to its climate source, model and knowledge base."""
        self._climate = climate
        self._model = model
        self._knowledge_base = knowledge_base or load_knowledge_base()
        self._area = area or AreaClimateService(climate.profile_set)

    def compare(
        self,
        *,
        district: str,
        proposed: MaterialSelection | None,
        situation: ElementSituation = "exposed",
    ) -> ScoreComparison:
        """Score a district both as proposed and as recommended.

        Args:
            district: District name; must have a measured profile.
            proposed: The user's specification. When ``None`` — recommend-only
                mode — a deliberately conventional baseline is scored instead, so
                the comparison still shows what the advice is worth.
            situation: How the element sits relative to the weather.

        Raises:
            ClimateProfileUnavailableError: If the district has no profile.
        """
        return self.compare_profile(
            profile=self._climate.get_profile(district),
            proposed=proposed,
            situation=situation,
        )

    def compare_area(
        self,
        *,
        area: AreaBounds,
        proposed: MaterialSelection | None,
        situation: ElementSituation = "exposed",
    ) -> tuple[ScoreComparison, AreaClimate]:
        """Score a drawn area both as proposed and as recommended.

        The derived ``AreaClimate`` is returned alongside the comparison rather than
        folded into it, because the caller must be able to tell the user whether the
        climate behind their score was measured inside the area or interpolated from
        outside it. Dropping that on the floor here would make the two
        indistinguishable downstream.

        Raises:
            ClimateProfileUnavailableError: If no measured node is near enough.
        """
        area_climate = self._area.for_area(area)
        comparison = self.compare_profile(
            profile=area_climate.profile,
            proposed=proposed,
            situation=situation,
        )
        return comparison, area_climate

    def compare_profile(
        self,
        *,
        profile: DistrictClimateProfile,
        proposed: MaterialSelection | None,
        situation: ElementSituation = "exposed",
    ) -> ScoreComparison:
        """Score one climate profile, however it was obtained.

        The shared core of both modes. Named-district scoring and area scoring
        differ only in where the profile came from; keeping the scoring itself in
        one place is what stops the two paths drifting apart.
        """
        summary = self._climate.to_rules_summary(profile)

        baseline = proposed if proposed is not None else self._conventional_baseline(situation)
        scored_proposed = self._score(summary, baseline)
        scored_recommended = self._score(summary, self.recommend(summary, situation))

        logger.info(
            "quality_score_compared",
            district=profile.district,
            proposed=scored_proposed.score,
            recommended=scored_recommended.score,
            exposure=scored_proposed.assessment.assessment.exposure.id,
        )

        return ScoreComparison(
            district=profile.district,
            climate=profile,
            exposure=scored_proposed.assessment.assessment.exposure,
            exposure_reasons=scored_proposed.assessment.assessment.reasons,
            proposed=scored_proposed,
            recommended=scored_recommended,
            provenance=self._climate.provenance,
            model_version=self._model.version,
        )

    def recommend(self, summary: ClimateSummary, situation: ElementSituation) -> MaterialSelection:
        """Derive a compliant specification for this climate.

        Built from the exposure class's own minimums, with a margin added above
        each because specifying exactly at the limit leaves nothing for site
        variation.
        """
        exposure = classify_exposure(summary, situation, self._knowledge_base).exposure

        coastal = summary.distance_to_coast_km <= constants.COASTAL_INFLUENCE_KM
        humid = summary.mean_relative_humidity_percent >= constants.HIGH_HUMIDITY_PERCENT
        hot = summary.mean_max_temperature_c >= constants.HEAT_REFERENCE_MAX_TEMP_C

        admixtures: list[str] = []
        if coastal:
            admixtures.append("corrosion inhibitor")
        if summary.wetness_index >= constants.WET_REGIME_INDEX:
            admixtures.append("waterproofing admixture")

        order = HOT_WALLING if hot and not humid else HUMID_WALLING
        available = {item.id for item in self._knowledge_base.brick_suitability}
        walling = next((item for item in order if item in available), order[0])

        return MaterialSelection(
            concrete=ConcreteMix(
                grade=exposure.min_grade,
                cement_content_kg_m3=float(exposure.min_cement_kg_m3)
                + constants.RECOMMENDED_CEMENT_MARGIN_KG_M3,
                water_cement_ratio=exposure.max_water_cement_ratio
                - constants.RECOMMENDED_WATER_CEMENT_MARGIN,
                cement_type=MARINE_CEMENT if coastal else DEFAULT_CEMENT,
                admixtures=tuple(admixtures),
            ),
            walling_material_id=walling,
            element_situation=situation,
        )

    def _score(self, summary: ClimateSummary, selection: MaterialSelection) -> ScoredSelection:
        """Assess a selection and score it by both routes."""
        assessment = assess(summary, selection, self._knowledge_base)
        return ScoredSelection(
            selection=selection,
            assessment=assessment,
            rules_score=quality_score_label(assessment),
            model_score=self._model.predict(summary=summary, selection=selection),
        )

    @staticmethod
    def _conventional_baseline(situation: ElementSituation) -> MaterialSelection:
        """The specification a builder would reach for without advice."""
        return MaterialSelection(
            concrete=ConcreteMix(
                grade="M20",
                cement_content_kg_m3=300.0,
                water_cement_ratio=0.55,
                cement_type="OPC",
            ),
            walling_material_id="burnt_clay_brick",
            element_situation=situation,
        )
