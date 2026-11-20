"""Regression tests for the GRIB pipeline: gap-filling, schema and profiles.

The pipeline lives in ``/ml`` because it is offline tooling, but it produces the
only climate data the application ever sees, so it is tested here with the rest of
the suite rather than left unguarded.

The gap-filling rule is the one that most needs pinning down. Real gaps may be
filled only from real neighbouring data and must always be flagged; a value that
cannot be grounded must fail the run rather than be invented. The bundled file
happens to have no gaps, so these tests inject them.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pandas as pd
import pytest

from app.repositories.district_profiles import (
    ClimateProfileUnavailableError,
    load_climate_profiles,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
ML_DIR = REPO_ROOT / "ml"


def _load_ml_module(name: str) -> ModuleType:
    """Import a script from /ml, which is not an installed package.

    The scripts sit outside the app package deliberately — training code must
    never be importable at request time — so they are loaded by path here.
    """
    if str(ML_DIR) not in sys.path:
        sys.path.insert(0, str(ML_DIR))
    spec = importlib.util.spec_from_file_location(name, ML_DIR / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def grib_pipeline() -> ModuleType:
    """The GRIB-to-CSV script."""
    return _load_ml_module("grib_to_csv")


def _frame(rows: list[dict[str, object]], pipeline: ModuleType) -> pd.DataFrame:
    """Build a frame carrying every column the pipeline validates."""
    frame = pd.DataFrame(rows)
    for column in pipeline.MEASURED_COLUMNS:
        if column not in frame.columns:
            frame[column] = 1.0
    return frame


def _row(district: str, day: int, **overrides: object) -> dict[str, object]:
    """One district-day with plausible values."""
    row: dict[str, object] = {
        "district": district,
        "date": pd.Timestamp(f"2020-01-{day:02d}").date(),
        "grid_latitude": 11.0,
        "grid_longitude": 77.0,
        "temperature_c": 28.0,
        "relative_humidity_percent": 70.0,
        "precipitation_hourly_mm": 0.2,
    }
    row.update(overrides)
    return row


class TestGapFilling:
    """Missing values may only be filled from real neighbouring data."""

    def test_no_gaps_means_no_interpolation(self, grib_pipeline: ModuleType) -> None:
        frame = _frame([_row("Erode", day) for day in range(1, 6)], grib_pipeline)

        filled, summary = grib_pipeline.fill_gaps(frame)

        assert summary["missing_cells_before"] == 0
        assert not filled["is_interpolated"].any()

    def test_short_gap_is_interpolated_from_the_same_cell(self, grib_pipeline: ModuleType) -> None:
        """Values either side of the gap are from the same grid node."""
        rows = [_row("Erode", day, temperature_c=20.0 + day) for day in range(1, 6)]
        rows[2]["temperature_c"] = None
        frame = _frame(rows, grib_pipeline)

        filled, summary = grib_pipeline.fill_gaps(frame)

        assert summary["filled_temporal"] == 1
        # Linear between 22 and 24 on either side.
        assert filled.loc[2, "temperature_c"] == pytest.approx(23.0)

    def test_every_filled_row_is_flagged(self, grib_pipeline: ModuleType) -> None:
        """A filled value must never be silently merged with real readings."""
        rows = [_row("Erode", day) for day in range(1, 6)]
        rows[2]["relative_humidity_percent"] = None
        frame = _frame(rows, grib_pipeline)

        filled, _ = grib_pipeline.fill_gaps(frame)

        assert bool(filled.loc[2, "is_interpolated"]) is True
        assert filled.loc[2, "interpolation_method"] == "temporal_linear"
        # Untouched rows stay unflagged.
        assert not bool(filled.loc[0, "is_interpolated"])

    def test_ungroundable_gap_fails_rather_than_inventing(self, grib_pipeline: ModuleType) -> None:
        """A lone district with no neighbour and no surrounding days must error."""
        frame = _frame([_row("Erode", 1, temperature_c=None)], grib_pipeline)

        with pytest.raises(ValueError, match="invented"):
            grib_pipeline.fill_gaps(frame)

    def test_summary_reports_what_was_filled(self, grib_pipeline: ModuleType) -> None:
        rows = [_row("Erode", day) for day in range(1, 6)]
        rows[1]["temperature_c"] = None
        frame = _frame(rows, grib_pipeline)

        _, summary = grib_pipeline.fill_gaps(frame)

        assert summary["missing_cells_before"] == 1
        assert summary["filled_temporal"] + summary["filled_spatial"] == 1


class TestSchemaValidation:
    """The CSV contract the model trainer relies on."""

    def test_accepts_a_well_formed_frame(self, grib_pipeline: ModuleType) -> None:
        rows = [_row(d, day) for d in ("Erode", "Salem") for day in range(1, 4)]
        frame, _ = grib_pipeline.fill_gaps(_frame(rows, grib_pipeline))

        summary = grib_pipeline.validate(frame[grib_pipeline.OUTPUT_COLUMNS])

        assert summary["rows"] == 6
        assert summary["districts"] == 2

    def test_rejects_null_measured_values(self, grib_pipeline: ModuleType) -> None:
        rows = [_row("Erode", day) for day in range(1, 4)]
        frame = _frame(rows, grib_pipeline)
        frame["is_interpolated"] = False
        frame["interpolation_method"] = ""
        frame.loc[1, "temperature_c"] = None

        with pytest.raises(ValueError, match="null values"):
            grib_pipeline.validate(frame[grib_pipeline.OUTPUT_COLUMNS])

    def test_rejects_duplicate_district_days(self, grib_pipeline: ModuleType) -> None:
        rows = [_row("Erode", 1), _row("Erode", 1)]
        frame = _frame(rows, grib_pipeline)
        frame["is_interpolated"] = False
        frame["interpolation_method"] = ""

        with pytest.raises(ValueError, match="duplicate"):
            grib_pipeline.validate(frame[grib_pipeline.OUTPUT_COLUMNS])

    def test_rejects_uneven_coverage_between_districts(self, grib_pipeline: ModuleType) -> None:
        """Uneven periods would train different districts on different history."""
        rows = [_row("Erode", 1), _row("Erode", 2), _row("Salem", 1)]
        frame = _frame(rows, grib_pipeline)
        frame["is_interpolated"] = False
        frame["interpolation_method"] = ""

        with pytest.raises(ValueError, match="differing row counts"):
            grib_pipeline.validate(frame[grib_pipeline.OUTPUT_COLUMNS])


class TestExcludedVariables:
    """Ocean-only fields are dropped, never gap-filled."""

    def test_ocean_variables_are_excluded_with_a_reason(self, grib_pipeline: ModuleType) -> None:
        """Filling them would fabricate sea state over dry land."""
        for name in ("sst", "swh", "mwd", "mwp"):
            assert name in grib_pipeline.OCEAN_ONLY_VARIABLES
            assert grib_pipeline.OCEAN_ONLY_VARIABLES[name]

    def test_ocean_variables_are_not_kept(self, grib_pipeline: ModuleType) -> None:
        assert not set(grib_pipeline.OCEAN_ONLY_VARIABLES) & set(grib_pipeline.KEPT_VARIABLES)

    def test_short_name_aliases_match_the_file(self, grib_pipeline: ModuleType) -> None:
        """ecCodes reports raw GRIB names; every alias must land on a kept name."""
        for raw, canonical in grib_pipeline.SHORT_NAME_ALIASES.items():
            assert raw != canonical
            assert canonical in grib_pipeline.KEPT_VARIABLES


class TestBundledProfiles:
    """The generated profiles are what the application actually reads."""

    def test_priority_districts_are_present(self) -> None:
        names = load_climate_profiles().names()
        for district in ("Coimbatore", "Salem", "Erode"):
            assert district in names

    def test_chennai_is_absent_because_it_is_outside_the_grid(self) -> None:
        assert "Chennai" not in load_climate_profiles().names()

    def test_lookup_is_case_insensitive(self) -> None:
        assert load_climate_profiles().get("coimbatore").district == "Coimbatore"

    def test_unknown_district_names_the_alternatives(self) -> None:
        with pytest.raises(ClimateProfileUnavailableError) as caught:
            load_climate_profiles().get("Atlantis")

        assert "Coimbatore" in caught.value.details["available_districts"]

    def test_values_are_physically_plausible(self) -> None:
        """Catches a unit error in the pipeline before it reaches a score."""
        for profile in load_climate_profiles().profiles:
            assert 0 <= profile.mean_relative_humidity_percent <= 100
            assert 0 <= profile.wet_hours_fraction <= 1
            assert 10 <= profile.mean_max_temperature_c <= 50
            assert 0 <= profile.max_wind_gust_ms <= 80
            assert profile.distance_to_coast_km >= 0
            assert profile.observation_days > 3000

    def test_profiles_record_their_provenance(self) -> None:
        """A score has to be traceable to the file it came from."""
        profiles = load_climate_profiles()

        assert profiles.source_grib.endswith(".grib")
        assert profiles.observation_start.startswith("2016")

    def test_inland_districts_are_not_treated_as_coastal(self) -> None:
        """Coimbatore, Salem and Erode are well inland; a small value here would
        silently push every one of them to a marine exposure class."""
        profiles = load_climate_profiles()
        for district in ("Coimbatore", "Salem", "Erode"):
            assert profiles.get(district).distance_to_coast_km > 50


class TestManifest:
    """The manifest is the pipeline's provenance record."""

    def test_manifest_accompanies_the_csv(self) -> None:
        manifests = sorted((REPO_ROOT / "ml" / "data").glob("climate_daily_*.manifest.json"))
        assert manifests, "pipeline must emit a manifest beside the CSV"

        manifest = json.loads(manifests[-1].read_text(encoding="utf-8"))
        assert manifest["source_grib"].endswith(".grib")
        assert "accumulation_note" in manifest
        assert manifest["validation"]["rows"] > 0
