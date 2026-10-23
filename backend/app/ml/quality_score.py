"""Inference wrapper for the Building Quality Score model.

The model is a smooth interpolator over the Phase 3 rules engine, so its output is
clamped to 0-100 and always returned alongside the rules value it approximates.
It is not evidence about real building outcomes; see ``ml/train_quality_score.py``.
"""

from __future__ import annotations

import numpy as np

from app.core import calculations
from app.core.logging import get_logger
from app.ml.registry import LoadedModel
from app.services.rules_engine import ClimateSummary, MaterialSelection, parse_grade_mpa

logger = get_logger(__name__)

# Must match ml/train_quality_score.py. Kept here so inference can build the
# feature row without importing training code.
SITUATION_SEVERITY: dict[str, int] = {
    "enclosed": 1,
    "sheltered": 2,
    "buried": 2,
    "exposed": 3,
    "tidal": 5,
}


class QualityScoreModel:
    """Predicts the 0-100 Building Quality Score."""

    def __init__(self, loaded: LoadedModel, absorption_by_material: dict[str, float]) -> None:
        """Bind the wrapper to a loaded artifact and the walling absorption table."""
        self._loaded = loaded
        self._absorption = absorption_by_material

    @property
    def version(self) -> str:
        """Artifact version, recorded on every score."""
        return self._loaded.version

    def predict(self, *, summary: ClimateSummary, selection: MaterialSelection) -> float:
        """Score one climate-and-materials combination.

        Raises:
            ValueError: If the concrete grade cannot be parsed.
        """
        features = {
            "mean_relative_humidity_percent": summary.mean_relative_humidity_percent,
            "wetness_index": summary.wetness_index,
            "wet_dry_cycles_per_year": summary.wet_dry_cycles_per_year,
            "max_wind_gust_ms": summary.max_wind_gust_ms,
            "mean_max_temperature_c": summary.mean_max_temperature_c,
            "distance_to_coast_km": summary.distance_to_coast_km,
            "situation_severity": float(SITUATION_SEVERITY.get(selection.element_situation, 3)),
            "grade_mpa": float(parse_grade_mpa(selection.concrete.grade)),
            "cement_content_kg_m3": selection.concrete.cement_content_kg_m3,
            "water_cement_ratio": selection.concrete.water_cement_ratio,
            # Materials absent from the published properties table fall back to the
            # IS 1077 reference absorption rather than to zero, which would read as
            # a perfect material.
            "walling_absorption_percent": self._absorption.get(selection.walling_material_id, 20.0),
        }

        # Column order is part of the artifact's contract.
        row = np.array([[features[column] for column in self._loaded.feature_columns]], dtype=float)
        prediction = float(self._loaded.estimator.predict(row)[0])
        return round(calculations.clamp(prediction, 0.0, 100.0), 1)
