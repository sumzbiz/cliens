"""Loads the IS-code materials knowledge base from its bundled JSON.

Static reference data rather than database rows: it changes only when a standard
is revised, it must be identical in every deployment, and shipping it as a file
keeps it reviewable in a diff. It lives in the repository layer for the same
reason the material seed data does — loading bundled data is persistence work.

Everything here is *quoted* from published standards. That is the crucial
difference from ``materials_seed.json``, whose 0-1 resistance ratings are our own
derivation. Do not blur the two.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.core.exceptions import AppError

KNOWLEDGE_BASE_PATH = Path(__file__).parent / "data" / "materials_knowledge_base.json"


class KnowledgeBaseError(AppError):
    """The bundled knowledge base is missing or malformed.

    A deployment problem, not a user error: without it no compliance check can run.
    """

    code = "KNOWLEDGE_BASE_UNAVAILABLE"
    http_status = 503


@dataclass(frozen=True, slots=True)
class ExposureClass:
    """One IS 456 Table 5 exposure condition and its mix requirements.

    Attributes:
        id: Stable identifier, e.g. ``"severe"``.
        label: Name as IS 456 writes it.
        severity: Ordinal 1-5, so "at least Severe" is a numeric comparison.
        climate_context: When this class applies.
        min_cement_kg_m3: Minimum cement content.
        max_water_cement_ratio: Maximum free water/cement ratio.
        min_grade: Minimum concrete grade, e.g. ``"M30"``.
        min_grade_mpa: That grade as a number, for comparison.
        standard: The clause this comes from.
    """

    id: str
    label: str
    severity: int
    climate_context: str
    min_cement_kg_m3: int
    max_water_cement_ratio: float
    min_grade: str
    min_grade_mpa: int
    standard: str


@dataclass(frozen=True, slots=True)
class MaterialRecommendation:
    """A climate-conditioned material recommendation with its source standard."""

    id: str
    condition: str
    condition_label: str
    material: str
    purpose: str
    standard: str
    applies_to: str


@dataclass(frozen=True, slots=True)
class BrickSuitability:
    """Which climate a walling material suits, and why."""

    id: str
    material: str
    best_climate: str
    best_climate_label: str
    why: str


@dataclass(frozen=True, slots=True)
class MasonryProperties:
    """Published strength, absorption and conductivity for a walling material.

    Nullable fields are genuinely absent from the source table rather than zero —
    the reference gives no thermal conductivity for PFA-lime brick, for instance.
    """

    id: str
    material: str
    compressive_strength_min_mpa: float
    compressive_strength_max_mpa: float
    load_bearing_min_mpa: float | None
    max_water_absorption_percent: float
    thermal_conductivity_w_mk_min: float | None
    thermal_conductivity_w_mk_max: float | None
    note: str


@dataclass(frozen=True, slots=True)
class KnowledgeBase:
    """Every reference table, parsed and queryable."""

    exposure_classes: tuple[ExposureClass, ...]
    material_recommendations: tuple[MaterialRecommendation, ...]
    brick_suitability: tuple[BrickSuitability, ...]
    masonry_properties: tuple[MasonryProperties, ...]

    def exposure_by_id(self, exposure_id: str) -> ExposureClass:
        """Look up an exposure class.

        Raises:
            KnowledgeBaseError: If the id is not one of the five IS 456 classes.
        """
        for exposure in self.exposure_classes:
            if exposure.id == exposure_id:
                return exposure
        raise KnowledgeBaseError(
            f"Unknown exposure class {exposure_id!r}.",
            details={"known": [item.id for item in self.exposure_classes]},
        )

    def exposure_by_severity(self, severity: int) -> ExposureClass:
        """The exposure class at a given ordinal severity, clamped to the range.

        Clamping rather than raising: severity is produced by arithmetic on climate
        indicators, and a value slightly outside 1-5 should saturate at the most or
        least severe class rather than fail the whole request.
        """
        ordered = sorted(self.exposure_classes, key=lambda item: item.severity)
        lowest, highest = ordered[0].severity, ordered[-1].severity
        target = max(lowest, min(highest, severity))
        return next(item for item in ordered if item.severity == target)

    def recommendations_for(self, conditions: set[str]) -> tuple[MaterialRecommendation, ...]:
        """Every recommendation whose triggering condition is present."""
        return tuple(item for item in self.material_recommendations if item.condition in conditions)

    def masonry_by_id(self, material_id: str) -> MasonryProperties | None:
        """Published properties for a walling material, or ``None`` if unlisted."""
        for item in self.masonry_properties:
            if item.id == material_id:
                return item
        return None

    def brick_by_id(self, material_id: str) -> BrickSuitability | None:
        """Climate suitability for a walling material, or ``None`` if unlisted."""
        for item in self.brick_suitability:
            if item.id == material_id:
                return item
        return None


def _require(payload: dict[str, Any], key: str) -> list[dict[str, Any]]:
    """Read one table, failing loudly if it is absent."""
    table = payload.get(key)
    if not isinstance(table, list) or not table:
        raise KnowledgeBaseError(
            f"Knowledge base is missing the {key!r} table.",
            details={"path": str(KNOWLEDGE_BASE_PATH)},
        )
    return table


@lru_cache(maxsize=1)
def load_knowledge_base() -> KnowledgeBase:
    """Parse and cache the bundled knowledge base.

    Raises:
        KnowledgeBaseError: If the file is missing, malformed, or incomplete.
    """
    try:
        with KNOWLEDGE_BASE_PATH.open(encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError) as error:
        raise KnowledgeBaseError(
            "The bundled materials knowledge base could not be read.",
            details={"path": str(KNOWLEDGE_BASE_PATH)},
        ) from error

    return KnowledgeBase(
        exposure_classes=tuple(
            ExposureClass(**row) for row in _require(payload, "exposure_classes")
        ),
        material_recommendations=tuple(
            MaterialRecommendation(**row) for row in _require(payload, "material_recommendations")
        ),
        brick_suitability=tuple(
            BrickSuitability(**row) for row in _require(payload, "brick_suitability")
        ),
        masonry_properties=tuple(
            MasonryProperties(**row) for row in _require(payload, "masonry_properties")
        ),
    )
