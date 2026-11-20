"""Runs every training script in order; the entry point behind ``npm run train:models``.

Training is seeded, so a full retrain is reproducible: the same code on the same
day produces identical artifacts.

This previously imported ``train_damage_calibration`` and
``train_material_ranker``, neither of which exists in the repository, so
``npm run train:models`` failed on import and the only model the app loads was
never retrained by it.
"""

from __future__ import annotations

import sys

import train_quality_score

TRAINERS = (("quality score", train_quality_score.main),)


def main() -> int:
    """Train every model, stopping at the first failure.

    Returns:
        0 if all models trained, 1 otherwise.
    """
    for label, trainer in TRAINERS:
        print(f"\n=== {label} ===")
        exit_code = trainer()
        if exit_code != 0:
            sys.stderr.write(f"{label} training failed with exit code {exit_code}\n")
            return exit_code

    print("\nAll models trained. Artifacts are in ml/models/.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
