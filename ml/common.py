"""Shared training helpers: artifact naming, metric reporting, deterministic seeding.

Training code lives here, outside ``backend/app``, and is never imported at request
time. The application only ever loads the ``.pkl`` artifacts these scripts produce.

Artifacts are named ``<model>_<YYYYMMDD>_<gitsha>.pkl`` so any stored score can be
traced back to the exact code and data that produced its model.
"""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
from sklearn.metrics import mean_absolute_error, r2_score

# ml/common.py -> ml -> repository root
REPO_ROOT = Path(__file__).resolve().parents[1]
MODELS_DIR = REPO_ROOT / "ml" / "models"
DATA_DIR = REPO_ROOT / "ml" / "data"

# The backend package holds the single source of truth for every constant, so the
# training scripts import it rather than restating values that must agree.
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.core import constants  # noqa: E402  — requires the sys.path line above


@dataclass(frozen=True)
class ModelMetrics:
    """Held-out performance for one trained model.

    Attributes:
        r2: Coefficient of determination on the test split.
        mae: Mean absolute error on the test split, in the target's own units.
        train_samples: Rows used for fitting.
        test_samples: Rows held out.
        target_units: What the target variable measures, so MAE is interpretable.
    """

    r2: float
    mae: float
    train_samples: int
    test_samples: int
    target_units: str

    def render(self) -> str:
        """Format the metrics for the console and the training report."""
        return (
            f"  R²   {self.r2:.4f}\n"
            f"  MAE  {self.mae:.4f} ({self.target_units})\n"
            f"  train/test  {self.train_samples}/{self.test_samples}"
        )


def git_commit_sha() -> str:
    """Return the short commit SHA, or ``uncommitted`` outside a commit.

    Part of every artifact name so a model can be tied to the code that built it.
    A repository with no commits yet is a normal state during initial development,
    not an error.
    """
    try:
        result = subprocess.run(  # noqa: S603 — fixed argv, no shell, no user input
            ["git", "rev-parse", "--short", "HEAD"],  # noqa: S607
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return "uncommitted"

    sha = result.stdout.strip()
    return sha if result.returncode == 0 and sha else "uncommitted"


def artifact_name(model_name: str) -> str:
    """Build the versioned artifact filename for a model."""
    stamp = datetime.now(UTC).strftime("%Y%m%d")
    return f"{model_name}_{stamp}_{git_commit_sha()}.pkl"


def evaluate(
    predicted: np.ndarray, actual: np.ndarray, *, units: str, n_train: int
) -> ModelMetrics:
    """Compute held-out metrics."""
    return ModelMetrics(
        r2=float(r2_score(actual, predicted)),
        mae=float(mean_absolute_error(actual, predicted)),
        train_samples=n_train,
        test_samples=int(actual.shape[0]),
        target_units=units,
    )


def write_metrics_report(
    model_name: str, artifact: Path, metrics: ModelMetrics, extra: dict[str, Any]
) -> Path:
    """Write a JSON sidecar describing how this artifact was produced.

    The README quotes these numbers, so they are recorded rather than transcribed
    by hand — a metric that has to be copied manually eventually goes stale.
    """
    report = {
        "model": model_name,
        "artifact": artifact.name,
        "trained_at": datetime.now(UTC).isoformat(),
        "git_commit": git_commit_sha(),
        "random_seed": constants.RANDOM_SEED,
        "sklearn_target": "damage_ratio",
        "metrics": asdict(metrics),
        **extra,
    }
    path = artifact.with_suffix(".json")
    path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return path


def latest_artifact(model_name: str) -> Path | None:
    """Find the most recent artifact for a model, by filename order.

    Names begin with a date stamp, so lexicographic order is chronological.
    """
    candidates = sorted(MODELS_DIR.glob(f"{model_name}_*.pkl"))
    return candidates[-1] if candidates else None


def new_rng() -> np.random.Generator:
    """Return a seeded random generator.

    Every stochastic step in training draws from this, so retraining the same code
    on the same day produces a byte-identical artifact.
    """
    return np.random.default_rng(constants.RANDOM_SEED)
