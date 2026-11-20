"""Singleton model registry: loads versioned artifacts once at application startup.

Loading is deliberately eager. An artifact that is missing or was built by a
different scikit-learn version must fail at startup, not on the first user request
— unpickling across versions is unsupported and can silently change predictions.

Training code in ``/ml`` is never imported here. Only the ``.pkl`` artifacts it
produces are read.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import joblib
import sklearn

from app.core.exceptions import ModelUnavailableError
from app.core.logging import get_logger

logger = get_logger(__name__)

# backend/app/ml/registry.py -> ml -> app -> backend -> repository root
REPO_ROOT = Path(__file__).resolve().parents[3]
MODELS_DIR = REPO_ROOT / "ml" / "models"

QUALITY_MODEL_NAME = "quality_score"


@dataclass(frozen=True)
class LoadedModel:
    """A model artifact plus the metadata needed to interpret and audit it.

    Attributes:
        name: Logical model name.
        version: Artifact filename stem — date and git SHA — recorded on every
            score so an old score stays interpretable.
        estimator: The fitted scikit-learn estimator.
        feature_columns: Feature order the estimator was fitted with. Estimators
            index features positionally, so this must be honoured exactly.
    """

    name: str
    version: str
    estimator: Any
    feature_columns: tuple[str, ...]


def _find_latest(model_name: str) -> Path | None:
    """Return the newest artifact for a model.

    Filenames start with a date stamp, so lexicographic order is chronological.
    """
    if not MODELS_DIR.is_dir():
        return None
    candidates = sorted(MODELS_DIR.glob(f"{model_name}_*.pkl"))
    return candidates[-1] if candidates else None


def _load(model_name: str) -> LoadedModel:
    """Load one artifact from disk.

    Raises:
        ModelUnavailableError: If no artifact exists, it cannot be read, or it was
            produced by a different scikit-learn version.
    """
    path = _find_latest(model_name)
    if path is None:
        raise ModelUnavailableError(
            f"No trained artifact found for '{model_name}'. Train the models with "
            "`npm run train:models`.",
            details={"model": model_name, "searched": str(MODELS_DIR)},
        )

    try:
        bundle = joblib.load(path)
    except Exception as error:
        # joblib surfaces a wide range of unpickling failures; all of them mean the
        # same thing operationally, so they map to one typed error.
        logger.exception("model_artifact_unreadable", model=model_name, path=str(path))
        raise ModelUnavailableError(
            f"The artifact for '{model_name}' could not be loaded.",
            details={"model": model_name, "artifact": path.name},
        ) from error

    built_with = bundle.get("sklearn_version")
    if built_with != sklearn.__version__:
        raise ModelUnavailableError(
            f"Artifact for '{model_name}' was built with scikit-learn {built_with}, "
            f"but this process runs {sklearn.__version__}. Unpickling across versions "
            "is unsupported and can change predictions silently. Retrain with "
            "`npm run train:models`.",
            details={
                "model": model_name,
                "artifact_sklearn_version": built_with,
                "runtime_sklearn_version": sklearn.__version__,
            },
        )

    loaded = LoadedModel(
        name=model_name,
        version=path.stem,
        estimator=bundle["model"],
        feature_columns=tuple(bundle["feature_columns"]),
    )
    logger.info("model_loaded", model=model_name, version=loaded.version)
    return loaded


class ModelRegistry:
    """Holds every loaded model for the lifetime of the process."""

    def __init__(self, quality: LoadedModel) -> None:
        """Bind the registry to already-loaded artifacts."""
        self.quality = quality

    @property
    def versions(self) -> dict[str, str]:
        """Artifact versions, recorded on every score for auditability."""
        return {"quality_model": self.quality.version}


_registry: ModelRegistry | None = None


def load_registry() -> ModelRegistry:
    """Load every model artifact. Called once from the application lifespan.

    Raises:
        ModelUnavailableError: If any artifact is missing or unusable.
    """
    global _registry
    _registry = ModelRegistry(quality=_load(QUALITY_MODEL_NAME))
    return _registry


def get_registry() -> ModelRegistry:
    """Return the process-wide registry.

    Raises:
        ModelUnavailableError: If the models were never loaded, which would
            otherwise surface as an opaque ``AttributeError`` on ``None``.
    """
    if _registry is None:
        raise ModelUnavailableError(
            "The model registry has not been loaded.",
            details={"hint": "load_registry() runs during application startup"},
        )
    return _registry


def registry_is_loaded() -> bool:
    """Whether models are available, for the readiness probe."""
    return _registry is not None


def try_load_registry() -> None:
    """Load the registry, logging rather than raising if artifacts are absent.

    Used at startup so the application still serves the site and material
    endpoints — and reports its own degraded state through ``/health/ready`` —
    when the models have not been trained yet. Scoring endpoints still fail
    explicitly with ``MODEL_UNAVAILABLE``.
    """
    try:
        load_registry()
    except ModelUnavailableError as error:
        logger.warning(
            "model_registry_unavailable_at_startup",
            reason=error.message,
            hint="run `npm run train:models`",
        )


def reset_registry() -> None:
    """Forget the loaded models. Used between tests only."""
    global _registry
    _registry = None


def python_version() -> str:
    """Runtime Python version, reported alongside model versions in diagnostics."""
    return f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
