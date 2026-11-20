"""Reduce the GRIB-derived daily CSV into one climate profile per district.

This is what replaces Google Earth Engine. Every figure traces to ``data.grib``
through ``climate_daily_*.csv``; nothing is projected, modelled or invented.

The output is small (37 districts x a dozen statistics), so the backend loads it
at startup instead of reading a 36 MB CSV per request.

    node scripts/py.mjs ../ml/build_district_profiles.py

RAINFALL, READ THIS. The source ``tp`` field is a one-hour accumulation sampled at
00:00 UTC (GRIB step 5-6), not a daily total, and the file offers no way to build
one. Profiles therefore expose a *relative* wetness index rather than an absolute
annual depth: every district is measured on the identical sampling, so comparing
them is valid, while claiming "X mm per year" would not be.

DISTANCE TO COAST is derived from the land/sea mask implied by the reanalysis
itself — sea-surface temperature is defined only over water — rather than from a
hand-entered table.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

import numpy as np
import pandas as pd

from common import DATA_DIR, REPO_ROOT, git_commit_sha

from app.core import constants

GRIB_PATH: Final[Path] = DATA_DIR / "data.grib"
OUTPUT_PATH: Final[Path] = (
    REPO_ROOT / "backend" / "app" / "repositories" / "data" / "district_climate_profiles.json"
)

KM_PER_DEGREE_LATITUDE: Final[float] = 111.32

# CALIBRATED. An hour counts as "wet" above this depth. The source is an hourly
# sample, so the daily-rainfall threshold in constants would be the wrong scale.
WET_HOUR_RAINFALL_MM: Final[float] = 0.1


def latest_climate_csv() -> Path:
    """The most recent dated CSV from the GRIB pipeline.

    Raises:
        FileNotFoundError: If the pipeline has not been run.
    """
    candidates = sorted(DATA_DIR.glob("climate_daily_*.csv"))
    if not candidates:
        raise FileNotFoundError(
            f"No climate_daily_*.csv in {DATA_DIR}. Run ml/grib_to_csv.py first."
        )
    return candidates[-1]


def coast_distances(districts: pd.DataFrame) -> dict[str, float]:
    """Distance from each district's grid node to the nearest sea cell.

    Uses the land/sea mask the reanalysis already encodes: sea-surface temperature
    is present over water and absent over land. Deriving the coastline from the
    same file that supplies the climate keeps the whole profile traceable to one
    source, and avoids a hand-maintained distance table drifting out of date.
    """
    import eccodes

    sea_lat: np.ndarray | None = None
    sea_lon: np.ndarray | None = None

    with GRIB_PATH.open("rb") as handle:
        while sea_lat is None:
            gid = eccodes.codes_grib_new_from_file(handle)
            if gid is None:
                break
            try:
                if str(eccodes.codes_get(gid, "shortName")) != "sst":
                    continue
                eccodes.codes_set(gid, "missingValue", float("nan"))
                values = eccodes.codes_get_array(gid, "values")
                latitudes = eccodes.codes_get_array(gid, "latitudes")
                longitudes = eccodes.codes_get_array(gid, "longitudes")
                is_sea = ~np.isnan(values)
                sea_lat = latitudes[is_sea]
                sea_lon = longitudes[is_sea]
            finally:
                eccodes.codes_release(gid)

    if sea_lat is None or sea_lon is None or sea_lat.size == 0:
        raise ValueError("No sea cells found in the GRIB; cannot derive coast distance.")

    distances: dict[str, float] = {}
    for row in districts.itertuples():
        latitude = float(row.grid_latitude)
        longitude = float(row.grid_longitude)
        separation = (
            np.hypot(
                sea_lat - latitude,
                (sea_lon - longitude) * np.cos(np.radians(latitude)),
            )
            * KM_PER_DEGREE_LATITUDE
        )
        distances[str(row.district)] = float(separation.min())
    return distances


def build_profiles(frame: pd.DataFrame) -> list[dict[str, object]]:
    """Reduce the daily record for each district into a single climate profile.

    Statistics are chosen for what the IS 456 rules actually turn on: sustained
    humidity (corrosion), heat (thermal load and hydration), gusts (wind loading),
    wetness and wet/dry cycling (durability), and soil moisture (foundations).
    """
    frame = frame.copy()
    frame["date"] = pd.to_datetime(frame["date"])
    frame["year"] = frame["date"].dt.year

    nodes = frame.groupby("district")[["grid_latitude", "grid_longitude"]].first().reset_index()
    distances = coast_distances(nodes)

    profiles: list[dict[str, object]] = []
    for district, group in frame.groupby("district"):
        group = group.sort_values("date")
        wet = group["precipitation_hourly_mm"] >= WET_HOUR_RAINFALL_MM

        # Transitions between wet and dry days: the measurable form of IS 456's
        # "alternate wetting and drying".
        transitions = int((wet.astype(int).diff().abs() == 1).sum())
        years = max((group["date"].max() - group["date"].min()).days / 365.25, 1.0)

        profiles.append(
            {
                "district": str(district),
                "grid_latitude": float(group["grid_latitude"].iloc[0]),
                "grid_longitude": float(group["grid_longitude"].iloc[0]),
                "distance_to_coast_km": round(distances[str(district)], 1),
                "mean_relative_humidity_percent": round(
                    float(group["relative_humidity_percent"].mean()), 2
                ),
                "humid_hours_fraction": round(
                    float(
                        (
                            group["relative_humidity_percent"] >= constants.HIGH_HUMIDITY_PERCENT
                        ).mean()
                    ),
                    4,
                ),
                "mean_temperature_c": round(float(group["temperature_c"].mean()), 2),
                "mean_max_temperature_c": round(
                    float(group.groupby("year")["temperature_c"].max().mean()), 2
                ),
                "max_temperature_c": round(float(group["temperature_c"].max()), 2),
                # Relative wetness only; see the module docstring on why this is
                # not published as an annual depth.
                "mean_hourly_rainfall_mm": round(float(group["precipitation_hourly_mm"].mean()), 4),
                "max_hourly_rainfall_mm": round(float(group["precipitation_hourly_mm"].max()), 2),
                "wet_hours_fraction": round(float(wet.mean()), 4),
                "wet_dry_cycles_per_year": round(transitions / years, 1),
                "mean_wind_speed_ms": round(float(group["wind_speed_ms"].mean()), 2),
                "max_wind_gust_ms": round(float(group["wind_gust_ms"].max()), 2),
                "mean_soil_moisture_m3_m3": round(float(group["soil_moisture_m3_m3"].mean()), 4),
                "observation_days": int(len(group)),
            }
        )

    return sorted(profiles, key=lambda item: str(item["district"]))


def main() -> int:
    """Build the profiles and write them next to the other reference data."""
    csv_path = latest_climate_csv()
    print(f"Reading {csv_path.name}", flush=True)
    frame = pd.read_csv(csv_path)

    profiles = build_profiles(frame)

    payload = {
        "_readme": [
            "Per-district climate profiles, reduced from the GRIB-derived daily CSV.",
            "",
            "This file is what replaces Google Earth Engine. Every value is measured,",
            "not projected: it describes 2016-2026 as it happened.",
            "",
            "RAINFALL is expressed as an hourly sample and as fractions, never as an",
            "annual depth. The source field accumulates over one hour at 00:00 UTC, so",
            "an annual total cannot be derived from it without inventing the diurnal",
            "cycle. Districts are directly comparable because the sampling is identical.",
            "",
            "Regenerate with: node scripts/py.mjs ../ml/build_district_profiles.py",
        ],
        "generated_at": datetime.now(UTC).isoformat(),
        "git_commit": git_commit_sha(),
        "source_csv": csv_path.name,
        "source_grib": GRIB_PATH.name,
        "observation_period": {
            "start": str(pd.to_datetime(frame["date"]).min().date()),
            "end": str(pd.to_datetime(frame["date"]).max().date()),
        },
        "profiles": profiles,
    }

    OUTPUT_PATH.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    print(f"Wrote {OUTPUT_PATH.name} ({len(profiles)} districts)\n")
    header = f"{'district':16}{'coast km':>10}{'RH %':>8}{'maxT':>7}{'gust':>7}{'cycles/y':>10}"
    print(header)
    print("-" * len(header))
    for profile in profiles:
        if profile["district"] in {"Coimbatore", "Salem", "Erode"}:
            print(
                f"{profile['district']:16}"
                f"{profile['distance_to_coast_km']:>10}"
                f"{profile['mean_relative_humidity_percent']:>8}"
                f"{profile['mean_max_temperature_c']:>7}"
                f"{profile['max_wind_gust_ms']:>7}"
                f"{profile['wet_dry_cycles_per_year']:>10}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
