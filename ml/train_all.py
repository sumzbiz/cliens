"""Runs every training script in order; the entry point behind ``npm run train:models``.

Both models are trained from the same seeded generator, so a full retrain is
reproducible: the same code on the same day produces identical artifacts.
"""

from __future__ import annotations

import sys

import train_damage_calibration
import train_material_ranker

TRAINERS = (
    ("damage calibration", train_damage_calibration.main),
    ("material ranker", train_material_ranker.main),
)


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
