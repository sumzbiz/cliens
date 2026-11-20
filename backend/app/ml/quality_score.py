"""Inference wrapper for the Building Quality Score model.

The model is a smooth interpolator over the Phase 3 rules engine, so its output is
clamped to 0-100 and always returned alongside the rules value it approximates.
It is not evidence about real building outcomes; see ``ml/train_quality_score.py``.

The feature row is built here, by ``build_features``, and the training script
imports that same function. Training and inference previously each kept their own
copy of the feature definitions, which is how they came to disagree about what a
situation's severity meant.
"""

from __future__ import annotations

import numpy as np

from app.core import calculations, constants
from app.core.logging import get_logger
from app.ml.registry import LoadedModel
from app.repositories.knowledge_base import KnowledgeBase
from app.services.rules_engine import (
    ClimateSummary,
    MaterialSelection,
    classify_exposure,
    parse_grade_mpa,
)

logger = get_logger(__name__)

# Read only by artifacts trained before exposure severity became a feature, which
# encode the situation this way. Kept so such an artifact still loads and scores.
SITUATION_SEVERITY: dict[str, int] = {
    "enclosed": 1,
    "sheltered": 2,
    "buried": 2,
    "exposed": 3,
    "tidal": 5,
}

# Walling materials one-hot encoded. The walling verdict turns on which material
# it is, not only on its absorption: burnt clay and fly ash brick share a 20%
# absorption figure, yet one fails in a humid climate and the other passes. With
# absorption as the only walling feature the model could not tell them apart and
# scored the two identically, while the rules separated them by ~14 points.
WALLING_FEATURE_IDS: tuple[str, ...] = (
    "aac_block",
    "burnt_clay_brick",
    "concrete_solid_block",
    "engineering_brick",
    "fly_ash_brick",
)

# Cement types and admixtures, because matching them is what earns the
# recommendation credit in the rules score.
CEMENT_FEATURE_TYPES: tuple[str, ...] = ("OPC", "PPC", "PSC")
ADMIXTURE_FEATURES: dict[str, str] = {
    "has_corrosion_inhibitor": "corrosion inhibitor",
    "has_waterproofing_admixture": "waterproofing admixture",
}

FEATURE_COLUMNS: tuple[str, ...] = (
    "mean_relative_humidity_percent",
    "wetness_index",
    "wet_dry_cycles_per_year",
    "max_wind_gust_ms",
    "mean_max_temperature_c",
    "distance_to_coast_km",
    # The IS 456 class the rules engine resolves for this climate and situation.
    # Deterministic from the inputs, and the single fact every threshold below is
    # judged against, so handing it over beats asking the trees to rediscover the
    # Table 3 logic from raw climate — which, for tidal elements it had never
    # seen, they did not.
    "exposure_severity",
    "grade_mpa",
    "cement_content_kg_m3",
    "water_cement_ratio",
    "walling_absorption_percent",
    *(f"walling_{material}" for material in WALLING_FEATURE_IDS),
    *(f"cement_{cement}" for cement in CEMENT_FEATURE_TYPES),
    *ADMIXTURE_FEATURES,
)


def build_features(
    *,
    summary: ClimateSummary,
    selection: MaterialSelection,
    absorption_by_material: dict[str, float],
    knowledge_base: KnowledgeBase | None = None,
) -> dict[str, float]:
    """Every feature any quality-score artifact may ask for, by name.

    Raises:
        ValueError: If the concrete grade cannot be parsed.
    """
    exposure = classify_exposure(summary, selection.element_situation, knowledge_base).exposure
    cement_type = selection.concrete.cement_type.upper()
    admixtures = {admixture.lower() for admixture in selection.concrete.admixtures}

    features: dict[str, float] = {
        "mean_relative_humidity_percent": summary.mean_relative_humidity_percent,
        "wetness_index": summary.wetness_index,
        "wet_dry_cycles_per_year": summary.wet_dry_cycles_per_year,
        "max_wind_gust_ms": summary.max_wind_gust_ms,
        "mean_max_temperature_c": summary.mean_max_temperature_c,
        "distance_to_coast_km": summary.distance_to_coast_km,
        "exposure_severity": float(exposure.severity),
        "situation_severity": float(SITUATION_SEVERITY[selection.element_situation]),
        "grade_mpa": float(parse_grade_mpa(selection.concrete.grade)),
        "cement_content_kg_m3": selection.concrete.cement_content_kg_m3,
        "water_cement_ratio": selection.concrete.water_cement_ratio,
        # Materials absent from the published properties table fall back to the
        # IS 1077 reference absorption rather than to zero, which would read as a
        # perfect material.
        "walling_absorption_percent": absorption_by_material.get(
            selection.walling_material_id, constants.REFERENCE_WATER_ABSORPTION_PERCENT
        ),
    }
    for material in WALLING_FEATURE_IDS:
        features[f"walling_{material}"] = float(selection.walling_material_id == material)
    for cement in CEMENT_FEATURE_TYPES:
        features[f"cement_{cement}"] = float(cement_type == cement)
    for column, admixture in ADMIXTURE_FEATURES.items():
        features[column] = float(admixture in admixtures)
    return features


class QualityScoreModel:
    """Predicts the 0-100 Building Quality Score."""

    def __init__(
        self,
        loaded: LoadedModel,
        absorption_by_material: dict[str, float],
        knowledge_base: KnowledgeBase | None = None,
    ) -> None:
        """Bind the wrapper to a loaded artifact and the walling absorption table."""
        self._loaded = loaded
        self._absorption = absorption_by_material
        self._knowledge_base = knowledge_base

    @property
    def version(self) -> str:
        """Artifact version, recorded on every score."""
        return self._loaded.version

    def predict(self, *, summary: ClimateSummary, selection: MaterialSelection) -> float:
        """Score one climate-and-materials combination.

        Raises:
            ValueError: If the concrete grade cannot be parsed.
        """
        features = build_features(
            summary=summary,
            selection=selection,
            absorption_by_material=self._absorption,
            knowledge_base=self._knowledge_base,
        )

        # Column order is part of the artifact's contract.
        row = np.array([[features[column] for column in self._loaded.feature_columns]], dtype=float)
        prediction = float(self._loaded.estimator.predict(row)[0])
        return round(calculations.clamp(prediction, 0.0, 100.0), 1)
