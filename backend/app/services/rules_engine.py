"""IS-code compliance rules engine for construction materials.

Given a district's measured climate and a set of chosen materials, this answers
three questions the brief asks for:

a. which IS 456 exposure class applies, and why;
b. whether the chosen mix meets that class's minimums, and by how much;
c. which reference-table recommendations apply, and which are being followed.

Deliberately deterministic and fully explainable. Every verdict carries the clause
it came from and the numbers behind it, because this is the layer a reviewer would
challenge. The Phase 4 model learns from *these* labels — it does not replace them.

The one judgement here is turning IS 456 Table 3's prose ("exposed to severe rain",
"alternate wetting and drying") into numeric thresholds. Those live in
``core/constants.py`` with their reasoning, and are flagged in the README.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

from app.core import calculations, constants
from app.core.logging import get_logger
from app.repositories.knowledge_base import (
    ExposureClass,
    KnowledgeBase,
    MaterialRecommendation,
    load_knowledge_base,
)

logger = get_logger(__name__)

# How a structural element sits relative to the weather. IS 456's exposure classes
# are defined on the element's situation first and the region's climate second, so
# this is a required input rather than something inferred from the district.
ElementSituation = Literal["enclosed", "sheltered", "exposed", "buried", "tidal"]

# Baseline severity implied by the situation alone, before climate escalation.
# Mirrors IS 456 Table 3: protected surfaces are Mild; buried or continuously
# submerged concrete is Moderate; a tidal zone is Extreme regardless of anything else.
SITUATION_BASELINE_SEVERITY: dict[str, int] = {
    "enclosed": 1,
    "sheltered": 2,
    "buried": 2,
    "exposed": 2,
    "tidal": 5,
}

GRADE_PATTERN = re.compile(r"^M\s*(\d{2,3})$", re.IGNORECASE)


def parse_grade_mpa(grade: str) -> int:
    """Convert a concrete grade label to its characteristic strength.

    ``"M30"`` denotes 30 N/mm2. Parsing rather than string-matching lets the engine
    compare grades numerically, so an M45 mix correctly passes an M35 requirement.

    Raises:
        ValueError: If the label is not a recognised grade.
    """
    match = GRADE_PATTERN.match(grade.strip())
    if match is None:
        raise ValueError(f"Unrecognised concrete grade {grade!r}; expected a form like 'M30'.")
    return int(match.group(1))


@dataclass(frozen=True, slots=True)
class ClimateSummary:
    """A district's measured climate, reduced to what the IS rules turn on.

    Every field traces to the GRIB-derived CSV. ``distance_to_coast_km`` is derived
    from the land/sea mask implied by the reanalysis itself, not from a lookup table.
    """

    district: str
    mean_relative_humidity_percent: float
    # Fraction of sampled hours that were wet, NOT an annual depth. The GRIB
    # accumulates rainfall over one hour at 00:00 UTC, so an annual total cannot be
    # derived without inventing the diurnal cycle. Districts stay comparable
    # because every one is sampled identically.
    wetness_index: float
    wet_dry_cycles_per_year: float
    max_wind_gust_ms: float
    mean_max_temperature_c: float
    distance_to_coast_km: float


@dataclass(frozen=True, slots=True)
class ConcreteMix:
    """A proposed concrete specification."""

    grade: str
    cement_content_kg_m3: float
    water_cement_ratio: float
    cement_type: str = "OPC"
    admixtures: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class MaterialSelection:
    """What the user proposes to build with."""

    concrete: ConcreteMix
    walling_material_id: str
    element_situation: ElementSituation = "exposed"


@dataclass(frozen=True, slots=True)
class ExposureAssessment:
    """The exposure class that applies, and the reasoning that produced it."""

    exposure: ExposureClass
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ComplianceFinding:
    """One requirement checked against one proposed value.

    Attributes:
        parameter: Machine-readable name of what was checked.
        label: Human-readable name.
        required: The minimum (or maximum) the standard demands.
        provided: What the user proposed.
        compliant: Whether the requirement is met.
        margin_ratio: Signed fractional margin. Positive is better than required,
            negative is short of it, and the magnitude is how far — which is what
            the Phase 4 model learns to interpolate over.
        standard: The clause behind the requirement.
        message: A sentence written for the person who chose the material.
    """

    parameter: str
    label: str
    required: float
    provided: float
    compliant: bool
    margin_ratio: float
    standard: str
    message: str


@dataclass(frozen=True, slots=True)
class RulesAssessment:
    """The complete verdict for one district and one material selection."""

    climate: ClimateSummary
    assessment: ExposureAssessment
    findings: tuple[ComplianceFinding, ...]
    applicable_recommendations: tuple[MaterialRecommendation, ...]
    followed_recommendation_ids: tuple[str, ...] = field(default=())

    @property
    def compliant(self) -> bool:
        """Whether every checked requirement is met."""
        return all(finding.compliant for finding in self.findings)

    @property
    def unmet(self) -> tuple[ComplianceFinding, ...]:
        """Only the requirements that are not met."""
        return tuple(finding for finding in self.findings if not finding.compliant)


def quality_score_label(assessment: RulesAssessment) -> float:
    """Reduce a rules assessment to a 0-100 Building Quality score.

    This is the *label* the Phase 4 model learns, and the definition of the score
    itself. Deliberately simple and inspectable:

    * a fully compliant selection starts at ``COMPLIANT_BASE_SCORE``, leaving room
      above for headroom rather than pinning every compliant build at 100;
    * each shortfall subtracts in proportion to how far short it falls, so a
      near-miss and a gross failure are visibly different;
    * headroom above a minimum adds a little, with diminishing effect, because
      over-specifying has real but limited value;
    * following an applicable recommendation adds a fixed credit each.

    Returns:
        A score in ``[0, 100]``.
    """
    score = constants.COMPLIANT_BASE_SCORE

    for finding in assessment.findings:
        if finding.compliant:
            # Capped: a very rich mix should not buy an unlimited score.
            score += min(
                finding.margin_ratio * constants.SCORE_HEADROOM_WEIGHT,
                constants.SCORE_HEADROOM_CAP,
            )
        else:
            score += finding.margin_ratio * constants.SCORE_SHORTFALL_WEIGHT

    applicable = len(assessment.applicable_recommendations)
    if applicable:
        followed = len(assessment.followed_recommendation_ids)
        score += (followed / applicable) * constants.SCORE_RECOMMENDATION_WEIGHT

    upper_bound = 100.0 if assessment.compliant else constants.NONCOMPLIANT_SCORE_CAP
    return round(calculations.clamp(score, 0.0, upper_bound), 1)


def climate_conditions(climate: ClimateSummary) -> set[str]:
    """Which reference-table conditions this district's climate triggers.

    Returns the condition keys used by ``material_recommendations``, so the
    recommendation lookup is driven by measured data rather than by a hardcoded
    district-to-condition map.
    """
    conditions: set[str] = set()

    if climate.distance_to_coast_km <= constants.COASTAL_INFLUENCE_KM:
        conditions.add("coastal_marine")

    if climate.max_wind_gust_ms >= constants.WIND_REFERENCE_MS:
        conditions.add("high_wind")

    if climate.wetness_index >= constants.WET_REGIME_INDEX:
        conditions.add("high_rainfall")
        conditions.add("flood_prone")

    if (
        climate.mean_relative_humidity_percent >= constants.HIGH_HUMIDITY_PERCENT
        and climate.mean_max_temperature_c >= constants.HEAT_REFERENCE_MAX_TEMP_C
    ):
        conditions.add("hot_humid")

    if climate.mean_max_temperature_c >= constants.HEAT_REFERENCE_MAX_TEMP_C:
        conditions.add("hot_climate")

    # Always offered: lower-carbon substitutions are compatible with every class.
    conditions.add("sustainability_priority")

    return conditions


def classify_exposure(
    climate: ClimateSummary,
    situation: ElementSituation,
    knowledge_base: KnowledgeBase | None = None,
) -> ExposureAssessment:
    """Determine the IS 456 exposure class, recording why.

    Starts from the severity the element's situation implies, then escalates for
    each climate condition that meets a threshold. Escalation only ever raises the
    class — a mild-looking climate never downgrades an inherently harsh situation
    such as a tidal zone.

    Args:
        climate: The district's measured climate.
        situation: How the element sits relative to the weather.
        knowledge_base: Injectable for tests; loaded from the bundle otherwise.
    """
    base = knowledge_base or load_knowledge_base()

    severity = SITUATION_BASELINE_SEVERITY[situation]
    reasons = [f"{situation.capitalize()} element: baseline exposure severity {severity}."]

    def escalate(target: int, reason: str) -> None:
        nonlocal severity
        if target > severity:
            severity = target
            reasons.append(reason)

    if climate.distance_to_coast_km <= constants.DIRECT_SEA_SPRAY_KM:
        escalate(
            4,
            f"Within {constants.DIRECT_SEA_SPRAY_KM:g} km of the coast, so the surface is "
            "subject to direct sea-water spray.",
        )
    elif climate.distance_to_coast_km <= constants.COASTAL_INFLUENCE_KM:
        escalate(
            3,
            f"{climate.distance_to_coast_km:.0f} km from the coast, inside the "
            f"{constants.COASTAL_INFLUENCE_KM:g} km band where salt-laden air drives "
            "chloride attack.",
        )

    if situation == "exposed":
        if climate.wetness_index >= constants.WET_REGIME_INDEX:
            escalate(
                3,
                f"Exposed surface wet in {climate.wetness_index:.0%} of sampled hours, "
                "which counts as severe rain exposure.",
            )
        if climate.wet_dry_cycles_per_year >= constants.WET_DRY_CYCLES_SEVERE_PER_YEAR:
            escalate(
                3,
                f"{climate.wet_dry_cycles_per_year:.0f} wet/dry transitions a year, meeting "
                "the alternate wetting and drying condition.",
            )

    exposure = base.exposure_by_severity(severity)
    reasons.append(f"Applied exposure class: {exposure.label} ({exposure.standard}).")

    logger.info(
        "exposure_classified",
        district=climate.district,
        situation=situation,
        exposure=exposure.id,
        severity=severity,
    )
    return ExposureAssessment(exposure=exposure, reasons=tuple(reasons))


def check_mix_compliance(
    exposure: ExposureClass, mix: ConcreteMix
) -> tuple[ComplianceFinding, ...]:
    """Check a proposed mix against one exposure class's minimums.

    Three requirements from IS 456 Table 5: concrete grade, cement content and the
    free water/cement ratio. Each returns a signed margin so a near-miss reads
    differently from a gross shortfall.
    """
    findings: list[ComplianceFinding] = []

    provided_grade = float(parse_grade_mpa(mix.grade))
    required_grade = float(exposure.min_grade_mpa)
    findings.append(
        ComplianceFinding(
            parameter="concrete_grade_mpa",
            label="Concrete grade",
            required=required_grade,
            provided=provided_grade,
            compliant=provided_grade >= required_grade,
            margin_ratio=(provided_grade - required_grade) / required_grade,
            standard=exposure.standard,
            message=(
                f"Your {mix.grade} meets the {exposure.min_grade} minimum for "
                f"{exposure.label} exposure."
                if provided_grade >= required_grade
                else f"Your {mix.grade} is below the {exposure.min_grade} minimum for "
                f"{exposure.label} exposure."
            ),
        )
    )

    required_cement = float(exposure.min_cement_kg_m3)
    findings.append(
        ComplianceFinding(
            parameter="cement_content_kg_m3",
            label="Cement content",
            required=required_cement,
            provided=mix.cement_content_kg_m3,
            compliant=mix.cement_content_kg_m3 >= required_cement,
            margin_ratio=(mix.cement_content_kg_m3 - required_cement) / required_cement,
            standard=exposure.standard,
            message=(
                f"Cement content {mix.cement_content_kg_m3:.0f} kg/m3 meets the "
                f"{required_cement:.0f} kg/m3 minimum."
                if mix.cement_content_kg_m3 >= required_cement
                else f"Cement content {mix.cement_content_kg_m3:.0f} kg/m3 is short of the "
                f"{required_cement:.0f} kg/m3 minimum."
            ),
        )
    )

    # Water/cement is a MAXIMUM, so the margin is inverted: lower is better.
    required_ratio = exposure.max_water_cement_ratio
    findings.append(
        ComplianceFinding(
            parameter="water_cement_ratio",
            label="Water/cement ratio",
            required=required_ratio,
            provided=mix.water_cement_ratio,
            compliant=mix.water_cement_ratio <= required_ratio,
            margin_ratio=(required_ratio - mix.water_cement_ratio) / required_ratio,
            standard=exposure.standard,
            message=(
                f"Water/cement ratio {mix.water_cement_ratio:.2f} is within the "
                f"{required_ratio:.2f} maximum."
                if mix.water_cement_ratio <= required_ratio
                else f"Water/cement ratio {mix.water_cement_ratio:.2f} exceeds the "
                f"{required_ratio:.2f} maximum, which raises permeability."
            ),
        )
    )

    return tuple(findings)


def check_walling_suitability(
    climate: ClimateSummary, walling_material_id: str, knowledge_base: KnowledgeBase | None = None
) -> ComplianceFinding | None:
    """Check a walling choice against its published climate suitability.

    Returns ``None`` when the material is not in the reference table — an unlisted
    material is reported as unassessed rather than silently passed or failed.
    """
    base = knowledge_base or load_knowledge_base()
    suitability = base.brick_by_id(walling_material_id)
    if suitability is None:
        logger.info("walling_material_not_in_reference_tables", material=walling_material_id)
        return None

    # Properties are optional. The source's technical-properties table covers only
    # four materials, so requiring both tables would silently leave concrete block
    # and engineering brick unassessed — 40% of the catalogue.
    properties = base.masonry_by_id(walling_material_id)

    humid = climate.mean_relative_humidity_percent >= constants.HIGH_HUMIDITY_PERCENT
    poor_in_humidity = suitability.best_climate == "drier_zones"
    compliant = not (humid and poor_in_humidity)

    if not compliant:
        margin = constants.WALLING_MISMATCH_PENALTY
    elif properties is not None:
        # Absorption is the mechanism; a lower-absorption material tolerates
        # humidity better, so headroom scales with it.
        margin = (
            constants.REFERENCE_WATER_ABSORPTION_PERCENT - properties.max_water_absorption_percent
        ) / constants.REFERENCE_WATER_ABSORPTION_PERCENT
    else:
        # Suitable, but no published absorption figure to size the headroom from.
        margin = 0.0

    return ComplianceFinding(
        parameter="walling_climate_suitability",
        label="Walling material suitability",
        required=constants.HIGH_HUMIDITY_PERCENT,
        provided=climate.mean_relative_humidity_percent,
        compliant=compliant,
        margin_ratio=margin,
        standard=suitability.best_climate_label,
        message=(
            f"{suitability.material} suits this climate. {suitability.why}"
            if compliant
            else f"{suitability.material} is a poor fit at "
            f"{climate.mean_relative_humidity_percent:.0f}% humidity. {suitability.why}"
        ),
    )


def followed_recommendations(
    selection: MaterialSelection, applicable: tuple[MaterialRecommendation, ...]
) -> tuple[str, ...]:
    """Which applicable recommendations the chosen materials already satisfy.

    Matching is deliberately literal — cement type and admixture names against the
    recommendation's target. A recommendation is only reported as followed when the
    selection actually names the thing it asks for.
    """
    chosen = {
        selection.concrete.cement_type.upper(),
        *(a.upper() for a in selection.concrete.admixtures),
    }
    chosen.add(selection.walling_material_id.upper())

    followed: list[str] = []
    for recommendation in applicable:
        target = recommendation.material.upper()
        if any(token in target or target in token for token in chosen if token):
            followed.append(recommendation.id)
    return tuple(followed)


def assess(
    climate: ClimateSummary,
    selection: MaterialSelection,
    knowledge_base: KnowledgeBase | None = None,
) -> RulesAssessment:
    """Run the full assessment for one district and one material selection.

    This is the function the scoring service and the Phase 4 label generator both
    call, so a score and its explanation can never disagree.
    """
    base = knowledge_base or load_knowledge_base()

    assessment = classify_exposure(climate, selection.element_situation, base)
    findings = list(check_mix_compliance(assessment.exposure, selection.concrete))

    walling = check_walling_suitability(climate, selection.walling_material_id, base)
    if walling is not None:
        findings.append(walling)

    applicable = base.recommendations_for(climate_conditions(climate))

    return RulesAssessment(
        climate=climate,
        assessment=assessment,
        findings=tuple(findings),
        applicable_recommendations=applicable,
        followed_recommendation_ids=followed_recommendations(selection, applicable),
    )
