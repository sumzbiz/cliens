"""Trains the composite Building Quality Score model on rules-labelled scenarios.

WHAT THIS MODEL IS, stated plainly because it is easy to overclaim.

There is no dataset of "this building survived, that one degraded". None was used
and none is implied. Labels come from the Phase 3 rules engine: for a sampled
combination of real district climate and proposed materials, the label is the
0-100 score that ``rules_engine.quality_score_label`` computes from IS 456
compliance margins.

So this is a **smooth interpolator over a deterministic rule set**, not a model
that learned survival outcomes. What it buys is a continuous, differentiable
surface instead of a step function at each threshold, and a single fast call in
place of a combinatorial sweep. What it does not buy is any evidence about real
buildings.

The climate half of every scenario is real: districts and their measured climate
come from ``district_climate_profiles.json``, which traces to ``data.grib``. Only
the *material* combinations are enumerated, which is exactly the distinction the
brief draws between fabricating climate readings (never) and generating labelled
material scenarios (fine).

    node scripts/py.mjs ../ml/train_quality_score.py
"""

from __future__ import annotations

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.model_selection import train_test_split

from common import MODELS_DIR, artifact_name, constants, evaluate, write_metrics_report

from app.ml.quality_score import ADMIXTURE_FEATURES, FEATURE_COLUMNS, build_features
from app.repositories.district_profiles import load_climate_profiles
from app.repositories.knowledge_base import load_knowledge_base
from app.services.climate_data import ClimateDataService
from app.services.rules_engine import (
    ConcreteMix,
    ElementSituation,
    MaterialSelection,
    assess,
    quality_score_label,
)

MODEL_NAME = "quality_score"
TARGET_COLUMN = "quality_score"

# Sampled material space. Deliberately wider than any sensible specification so
# the model is well fitted either side of every threshold rather than only at
# realistic values.
GRADES = ["M15", "M20", "M25", "M30", "M35", "M40", "M45"]
CEMENT_CONTENTS = [260.0, 280.0, 300.0, 320.0, 340.0, 360.0, 380.0]
WATER_CEMENT_RATIOS = [0.35, 0.40, 0.45, 0.50, 0.55, 0.60]
# Every situation the API accepts. Tidal used to be missing, so every tidal score
# was an extrapolation — measured at 22 points off the rules on average.
SITUATIONS: list[ElementSituation] = ["enclosed", "sheltered", "exposed", "buried", "tidal"]
CEMENT_TYPES = ["OPC", "PPC", "PSC"]
ADMIXTURES = list(ADMIXTURE_FEATURES.values())


def build_dataset() -> pd.DataFrame:
    """Enumerate scenarios over real districts and label each with the rules engine."""
    knowledge_base = load_knowledge_base()
    climate_service = ClimateDataService()
    profiles = load_climate_profiles().profiles
    walling_ids = [item.id for item in knowledge_base.brick_suitability]
    absorption = {
        item.id: item.max_water_absorption_percent for item in knowledge_base.masonry_properties
    }

    rng = np.random.default_rng(constants.RANDOM_SEED)
    rows: list[dict[str, float]] = []

    for profile in profiles:
        summary = climate_service.to_rules_summary(profile)
        for grade in GRADES:
            for cement in CEMENT_CONTENTS:
                for ratio in WATER_CEMENT_RATIOS:
                    # Several situation/walling/cement/admixture draws per mix rather
                    # than the full cross product: the full grid would be millions
                    # of rows, and those axes act independently of the mix.
                    for _ in range(constants.QUALITY_MODEL_DRAWS_PER_MIX):
                        selection = MaterialSelection(
                            concrete=ConcreteMix(
                                grade=grade,
                                cement_content_kg_m3=cement,
                                water_cement_ratio=ratio,
                                cement_type=str(rng.choice(CEMENT_TYPES)),
                                admixtures=tuple(
                                    admixture for admixture in ADMIXTURES if rng.random() < 0.5
                                ),
                            ),
                            walling_material_id=str(rng.choice(walling_ids)),
                            element_situation=SITUATIONS[int(rng.integers(len(SITUATIONS)))],
                        )
                        row = build_features(
                            summary=summary,
                            selection=selection,
                            absorption_by_material=absorption,
                            knowledge_base=knowledge_base,
                        )
                        row[TARGET_COLUMN] = quality_score_label(
                            assess(summary, selection, knowledge_base)
                        )
                        rows.append(row)

    return pd.DataFrame(rows)


def main() -> int:
    """Train, evaluate and persist the quality score model."""
    MODELS_DIR.mkdir(parents=True, exist_ok=True)

    frame = build_dataset()
    print(f"Generated {len(frame)} rules-labelled scenarios", flush=True)

    features = frame[list(FEATURE_COLUMNS)].to_numpy()
    target = frame[TARGET_COLUMN].to_numpy()

    features_train, features_test, target_train, target_test = train_test_split(
        features,
        target,
        test_size=constants.TRAIN_TEST_SPLIT_FRACTION,
        random_state=constants.RANDOM_SEED,
    )

    model = GradientBoostingRegressor(
        n_estimators=constants.QUALITY_MODEL_N_ESTIMATORS,
        max_depth=constants.QUALITY_MODEL_MAX_DEPTH,
        learning_rate=constants.QUALITY_MODEL_LEARNING_RATE,
        random_state=constants.RANDOM_SEED,
    )
    model.fit(features_train, target_train)

    metrics = evaluate(
        model.predict(features_test),
        target_test,
        units="quality score, 0-100",
        n_train=len(features_train),
    )

    artifact = MODELS_DIR / artifact_name(MODEL_NAME)
    joblib.dump(
        {
            "model": model,
            "feature_columns": list(FEATURE_COLUMNS),
            "sklearn_version": __import__("sklearn").__version__,
        },
        artifact,
    )

    report = write_metrics_report(
        MODEL_NAME,
        artifact,
        metrics,
        extra={
            "training_data": "rules-labelled scenarios over real district climate",
            "climate_source": "data.grib via district_climate_profiles.json",
            "honesty_note": (
                "Labels are computed by the Phase 3 IS 456 rules engine, not observed "
                "from real buildings. This model interpolates a deterministic rule set "
                "smoothly; it is not evidence about building survival."
            ),
            "feature_importances": dict(
                zip(FEATURE_COLUMNS, (float(v) for v in model.feature_importances_), strict=True)
            ),
        },
    )

    print(f"Trained {MODEL_NAME}")
    print(metrics.render())
    print(f"  artifact  {artifact.name}")
    print(f"  report    {report.name}")
    print("\n  NOTE: labels are rules-derived, not observed building outcomes.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
