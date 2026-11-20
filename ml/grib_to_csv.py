"""Convert ``data.grib`` (ERA5 reanalysis) into a validated, tidy daily CSV.

This is the only path by which real historical climate data enters the pipeline.
Re-runnable and versioned: each run writes a dated CSV plus a manifest recording
exactly what was read, what was derived, and what (if anything) was gap-filled.

    node scripts/py.mjs ../ml/grib_to_csv.py

WHAT THIS DOES NOT DO
---------------------
It does not invent data. Two rules govern missing values:

1. **Ocean-only variables are excluded, not filled.** Sea-surface temperature and
   the wave fields are undefined over land by construction — roughly 70% NaN in
   this file, every one of them a land cell. "Filling" them would fabricate sea
   state on dry ground. They are dropped with the reason recorded in the manifest.

2. **Real gaps are filled only from real neighbouring data**, and always flagged.
   Short time gaps are interpolated from the same grid cell either side; anything
   longer falls back to the nearest neighbouring district's reading at the same
   timestamp. Every filled row carries ``is_interpolated`` and the method used. If
   a value cannot be grounded in real neighbouring data, the run fails rather than
   guessing.

UNITS: ERA5 publishes kelvin, metres and m/s. Everything is converted to the
canonical internal units from CLAUDE.md (degrees Celsius, millimetres, m/s) at the
point of conversion, using the shared helpers in ``app.core.calculations``.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

import numpy as np
import pandas as pd

from common import DATA_DIR, REPO_ROOT, git_commit_sha

from app.core import calculations

GRIB_PATH: Final[Path] = DATA_DIR / "data.grib"
DISTRICTS_PATH: Final[Path] = (
    REPO_ROOT / "backend" / "app" / "repositories" / "data" / "tamil_nadu_districts.json"
)

# Undefined over land by construction. Excluded rather than gap-filled; see the
# module docstring.
OCEAN_ONLY_VARIABLES: Final[dict[str, str]] = {
    "sst": "sea surface temperature is undefined over land",
    "swh": "significant wave height is undefined over land",
    "mwd": "mean wave direction is undefined over land",
    "mwp": "mean wave period is undefined over land",
}

# ecCodes reports the raw GRIB shortName ("2t"), which differs from the name cfgrib
# presents ("t2m"). Reading the file directly means using the raw names, so the two
# are mapped here explicitly. Verified against the file rather than assumed.
SHORT_NAME_ALIASES: Final[dict[str, str]] = {
    "2t": "t2m",
    "2d": "d2m",
    "10u": "u10",
    "10v": "v10",
    "10fg": "fg10",
}

# ERA5 variables kept, with the unit they arrive in. Chosen for relevance to
# building durability: thermal load, moisture, wind loading and ground conditions.
# Keys are the canonical (post-alias) names.
KEPT_VARIABLES: Final[dict[str, str]] = {
    "t2m": "K",  # 2 m air temperature -> thermal load
    "d2m": "K",  # 2 m dewpoint -> combines with t2m to give humidity
    "tp": "m",  # total precipitation -> rainfall / flood loading
    "crr": "kg m-2 s-1",  # convective rain rate -> intensity of downpours
    "u10": "m s-1",  # eastward wind
    "v10": "m s-1",  # northward wind
    "fg10": "m s-1",  # maximum wind gust -> the value wind design turns on
    "i10fg": "m s-1",  # instantaneous gust
    "sp": "Pa",  # surface pressure
    "msl": "Pa",  # mean sea level pressure -> cyclone proxy
    "e": "m",  # evaporation -> drying potential
    "swvl1": "m3 m-3",  # topsoil moisture -> foundation saturation
    "stl1": "K",  # topsoil temperature
    "slt": "code",  # soil type (static classification)
}

# CALIBRATED. A gap of up to a week can be bridged from the same cell either side
# without the interpolation carrying more weight than the real readings around it.
# Beyond that, a neighbouring district's real reading is the more defensible source.
MAX_TEMPORAL_GAP_DAYS: Final[int] = 7

# CALIBRATED. Two district nodes further apart than this are not comparable enough
# for one to stand in for the other; the run fails instead.
MAX_NEIGHBOUR_DISTANCE_KM: Final[float] = 150.0

KM_PER_DEGREE_LATITUDE: Final[float] = 111.32


def _grid_extent() -> tuple[tuple[float, float], tuple[float, float]]:
    """Latitude and longitude bounds of the file's grid, from its first message."""
    import eccodes

    with GRIB_PATH.open("rb") as handle:
        gid = eccodes.codes_grib_new_from_file(handle)
        if gid is None:
            raise ValueError(f"{GRIB_PATH} contains no GRIB messages")
        try:
            latitudes = eccodes.codes_get_array(gid, "latitudes")
            longitudes = eccodes.codes_get_array(gid, "longitudes")
        finally:
            eccodes.codes_release(gid)

    return (float(latitudes.min()), float(latitudes.max())), (
        float(longitudes.min()),
        float(longitudes.max()),
    )


def load_districts() -> pd.DataFrame:
    """Read the shared district reference table."""
    with DISTRICTS_PATH.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    return pd.DataFrame(payload["districts"])


def _grid_index_for_districts(
    latitudes: np.ndarray, longitudes: np.ndarray, districts: pd.DataFrame
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Map each district to the flat index of its nearest grid node.

    Returns the flat indices plus the matched node's own coordinates, so the output
    records which cell each district actually resolved to rather than only the town
    it was asked about.
    """
    site_lat = districts["latitude"].to_numpy()[:, None]
    site_lon = districts["longitude"].to_numpy()[:, None]

    # Great-circle distance is unnecessary at this scale; scaling longitude by
    # cos(latitude) makes a plain Euclidean comparison correct enough to pick the
    # nearest of cells 27 km apart.
    squared = (latitudes[None, :] - site_lat) ** 2 + (
        (longitudes[None, :] - site_lon) * np.cos(np.radians(site_lat))
    ) ** 2
    flat = squared.argmin(axis=1)
    return flat, latitudes[flat], longitudes[flat]


def extract_district_series(districts: pd.DataFrame) -> pd.DataFrame:
    """Read every GRIB message once, sampling only the district grid nodes.

    Uses the low-level ecCodes iterator rather than xarray. cfgrib builds a lazily
    indexed hypercube per message, and materialising ~97,000 of those to read 38
    points from each took over an hour. Walking the file sequentially and taking a
    fancy-index into each message's value array does the same job in minutes.

    ``validityDate``/``validityTime`` are read rather than ``dataDate``: the
    accumulated fields (rainfall, gusts) are stamped with a forecast reference time
    six hours before the period they describe, and ecCodes resolves that for us.
    Using the reference time would shift rainfall by a day.
    """
    import eccodes

    names = districts["name"].tolist()
    # Per-grid-shape cache: this file holds a 0.25 and a 0.5 degree grid, so the
    # index is computed once per shape rather than once per message.
    index_cache: dict[tuple[int, int], tuple[np.ndarray, np.ndarray, np.ndarray]] = {}
    records: dict[tuple[pd.Timestamp, str], dict[str, float]] = {}
    matched_coordinates: dict[str, tuple[float, float]] = {}

    wanted = set(KEPT_VARIABLES)
    message_count = 0

    with GRIB_PATH.open("rb") as handle:
        while True:
            gid = eccodes.codes_grib_new_from_file(handle)
            if gid is None:
                break
            message_count += 1
            try:
                raw_name = str(eccodes.codes_get(gid, "shortName"))
                short_name = SHORT_NAME_ALIASES.get(raw_name, raw_name)
                if short_name not in wanted:
                    continue

                columns = int(eccodes.codes_get(gid, "Ni"))
                rows = int(eccodes.codes_get(gid, "Nj"))
                shape = (rows, columns)

                if shape not in index_cache:
                    grid_lat = eccodes.codes_get_array(gid, "latitudes")
                    grid_lon = eccodes.codes_get_array(gid, "longitudes")
                    index_cache[shape] = _grid_index_for_districts(grid_lat, grid_lon, districts)

                flat_index, node_lat, node_lon = index_cache[shape]

                # ecCodes reports absent values with a sentinel; converting it to
                # NaN here means the gap-filling pass sees a real gap rather than a
                # wildly out-of-range number.
                eccodes.codes_set(gid, "missingValue", float("nan"))
                values = eccodes.codes_get_array(gid, "values")[flat_index]

                date = int(eccodes.codes_get(gid, "validityDate"))
                time_of_day = int(eccodes.codes_get(gid, "validityTime"))
                stamp = pd.Timestamp(
                    year=date // 10000,
                    month=(date // 100) % 100,
                    day=date % 100,
                    hour=time_of_day // 100,
                )

                for position, district in enumerate(names):
                    records.setdefault((stamp, district), {})[short_name] = float(values[position])
                    matched_coordinates.setdefault(
                        district, (float(node_lat[position]), float(node_lon[position]))
                    )
            finally:
                eccodes.codes_release(gid)

            if message_count % 20000 == 0:
                print(f"  {message_count} messages read ...", flush=True)

    print(f"  {message_count} messages read in total", flush=True)

    frame = pd.DataFrame.from_dict(records, orient="index")
    frame.index = pd.MultiIndex.from_tuples(frame.index, names=["valid_time", "district"])
    frame = frame.reset_index()

    frame["grid_latitude"] = frame["district"].map(lambda name: matched_coordinates[name][0])
    frame["grid_longitude"] = frame["district"].map(lambda name: matched_coordinates[name][1])
    return frame


def add_derived_columns(frame: pd.DataFrame) -> pd.DataFrame:
    """Convert ERA5 units to internal units and derive the building-relevant fields.

    Every conversion names its source and target unit, per CLAUDE.md, and reuses the
    shared helpers so the maths exists in exactly one place.
    """
    result = frame.copy()

    # kelvin -> degrees Celsius
    result["temperature_c"] = result["t2m"].map(calculations.kelvin_to_celsius)
    result["dewpoint_c"] = result["d2m"].map(calculations.kelvin_to_celsius)
    result["soil_temperature_c"] = result["stl1"].map(calculations.kelvin_to_celsius)

    # Humidity is what the IS 456 durability rules turn on, and ERA5 does not
    # publish it directly.
    result["relative_humidity_percent"] = [
        calculations.relative_humidity_from_dewpoint(temperature, dewpoint)
        for temperature, dewpoint in zip(result["temperature_c"], result["dewpoint_c"], strict=True)
    ]

    # metres -> millimetres.
    #
    # NAMED CAREFULLY. Every `tp` message in this file has step 5-6, i.e. it is
    # precipitation accumulated over a SINGLE HOUR, sampled once a day at 00:00
    # UTC. It is not a daily total, and the file contains no way to build one.
    #
    # Multiplying by 24 would look tempting and would be wrong: Indian rainfall is
    # strongly diurnal, peaking in the afternoon, so a midnight hour scaled up is a
    # fabricated number rather than a measured one. The column is therefore named
    # for what it actually is, and downstream code compares districts against each
    # other on this consistent sample rather than against an absolute annual depth.
    result["precipitation_hourly_mm"] = result["tp"].map(calculations.metres_to_millimetres)
    result["evaporation_hourly_mm"] = result["e"].map(calculations.metres_to_millimetres)

    # Orthogonal components -> scalar speed
    result["wind_speed_ms"] = [
        calculations.wind_speed_from_components(eastward, northward)
        for eastward, northward in zip(result["u10"], result["v10"], strict=True)
    ]
    result["wind_gust_ms"] = result["fg10"]
    result["instantaneous_gust_ms"] = result["i10fg"]

    result["surface_pressure_pa"] = result["sp"]
    result["mean_sea_level_pressure_pa"] = result["msl"]
    result["soil_moisture_m3_m3"] = result["swvl1"]
    result["soil_type_code"] = result["slt"]
    result["convective_rain_rate_kg_m2_s"] = result["crr"]

    return result


OUTPUT_COLUMNS: Final[list[str]] = [
    "district",
    "date",
    "grid_latitude",
    "grid_longitude",
    "temperature_c",
    "dewpoint_c",
    "relative_humidity_percent",
    "precipitation_hourly_mm",
    "convective_rain_rate_kg_m2_s",
    "evaporation_hourly_mm",
    "wind_speed_ms",
    "wind_gust_ms",
    "instantaneous_gust_ms",
    "surface_pressure_pa",
    "mean_sea_level_pressure_pa",
    "soil_moisture_m3_m3",
    "soil_temperature_c",
    "soil_type_code",
    "is_interpolated",
    "interpolation_method",
]

MEASURED_COLUMNS: Final[list[str]] = [
    column
    for column in OUTPUT_COLUMNS
    if column
    not in {
        "district",
        "date",
        "grid_latitude",
        "grid_longitude",
        "is_interpolated",
        "interpolation_method",
    }
]


def fill_gaps(frame: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, object]]:
    """Fill missing readings from real neighbouring data, flagging every fill.

    Two passes, in order of how well grounded they are:

    1. **Temporal** — linear interpolation along time within the same district, for
       gaps up to ``MAX_TEMPORAL_GAP_DAYS``. The surrounding real readings are from
       the same grid cell, so this is the closest thing to the true value.
    2. **Spatial** — the nearest other district's reading at the same timestamp,
       provided it is within ``MAX_NEIGHBOUR_DISTANCE_KM``. Real data from a real
       neighbouring cell, never a synthesised value.

    Raises:
        ValueError: If any value remains missing after both passes. The pipeline
            refuses to emit a CSV containing an ungrounded number.
    """
    result = frame.sort_values(["district", "date"]).reset_index(drop=True)
    result["is_interpolated"] = False
    result["interpolation_method"] = ""

    missing_before = int(result[MEASURED_COLUMNS].isna().sum().sum())
    if missing_before == 0:
        return result, {
            "missing_cells_before": 0,
            "filled_temporal": 0,
            "filled_spatial": 0,
            "note": "No gaps present; no interpolation performed.",
        }

    was_missing = result[MEASURED_COLUMNS].isna().any(axis=1)

    # --- Pass 1: temporal, within district -------------------------------
    # Coerced to numeric first: a column that arrived as object dtype (a None
    # among floats) makes interpolate a no-op today and an error in a future
    # pandas, either way leaving the gap silently unfilled.
    result[MEASURED_COLUMNS] = result[MEASURED_COLUMNS].apply(pd.to_numeric, errors="coerce")
    result[MEASURED_COLUMNS] = result.groupby("district", group_keys=False)[MEASURED_COLUMNS].apply(
        lambda group: group.interpolate(
            method="linear", limit=MAX_TEMPORAL_GAP_DAYS, limit_area="inside"
        )
    )

    filled_temporal = int((was_missing & ~result[MEASURED_COLUMNS].isna().any(axis=1)).sum())
    result.loc[was_missing & ~result[MEASURED_COLUMNS].isna().any(axis=1), "is_interpolated"] = True
    result.loc[
        was_missing & ~result[MEASURED_COLUMNS].isna().any(axis=1), "interpolation_method"
    ] = "temporal_linear"

    # --- Pass 2: spatial, nearest neighbouring district -------------------
    still_missing = result[MEASURED_COLUMNS].isna().any(axis=1)
    filled_spatial = 0
    if still_missing.any():
        coordinates = (
            result.groupby("district")[["grid_latitude", "grid_longitude"]].first().dropna()
        )
        for index in result.index[still_missing]:
            district = result.at[index, "district"]
            date = result.at[index, "date"]
            donor = _nearest_district(district, coordinates)
            if donor is None:
                continue
            donor_row = result[(result["district"] == donor) & (result["date"] == date)]
            if donor_row.empty:
                continue
            for column in MEASURED_COLUMNS:
                if pd.isna(result.at[index, column]):
                    result.at[index, column] = donor_row.iloc[0][column]
            result.at[index, "is_interpolated"] = True
            result.at[index, "interpolation_method"] = f"spatial_nearest:{donor}"
            filled_spatial += 1

    remaining = int(result[MEASURED_COLUMNS].isna().sum().sum())
    if remaining:
        raise ValueError(
            f"{remaining} values could not be grounded in real neighbouring data. "
            "Refusing to write a CSV containing invented values."
        )

    return result, {
        "missing_cells_before": missing_before,
        "filled_temporal": filled_temporal,
        "filled_spatial": filled_spatial,
    }


def _nearest_district(district: str, coordinates: pd.DataFrame) -> str | None:
    """Nearest other district within the allowed donor distance, or ``None``."""
    if district not in coordinates.index:
        return None
    latitude, longitude = coordinates.loc[district]

    best_name: str | None = None
    best_distance = MAX_NEIGHBOUR_DISTANCE_KM
    for other, (other_lat, other_lon) in coordinates.iterrows():
        if other == district:
            continue
        distance = (
            float(
                np.hypot(
                    other_lat - latitude,
                    (other_lon - longitude) * np.cos(np.radians(latitude)),
                )
            )
            * KM_PER_DEGREE_LATITUDE
        )
        if distance < best_distance:
            best_distance = distance
            best_name = str(other)
    return best_name


def validate(frame: pd.DataFrame) -> dict[str, object]:
    """Assert the output is fit for training, and describe it.

    Raises:
        ValueError: If any contract the model trainer relies on is broken.
    """
    problems: list[str] = []

    missing_columns = [column for column in OUTPUT_COLUMNS if column not in frame.columns]
    if missing_columns:
        problems.append(f"missing columns: {missing_columns}")

    if frame[MEASURED_COLUMNS].isna().any().any():
        problems.append("null values present in measured columns")

    duplicates = int(frame.duplicated(subset=["district", "date"]).sum())
    if duplicates:
        problems.append(f"{duplicates} duplicate (district, date) rows")

    # Every district must cover the same full date range, or a chronological split
    # would train on different periods for different places.
    per_district = frame.groupby("district")["date"].agg(["min", "max", "count"])
    if per_district["count"].nunique() != 1:
        problems.append(f"districts have differing row counts: {per_district['count'].unique()}")

    if problems:
        raise ValueError("Validation failed: " + "; ".join(problems))

    return {
        "rows": int(len(frame)),
        "districts": int(frame["district"].nunique()),
        "date_min": str(frame["date"].min()),
        "date_max": str(frame["date"].max()),
        "days_per_district": int(per_district["count"].iloc[0]),
        "interpolated_rows": int(frame["is_interpolated"].sum()),
    }


def main() -> int:
    """Run the conversion and write a dated CSV plus its manifest."""
    if not GRIB_PATH.is_file():
        print(f"GRIB file not found at {GRIB_PATH}")
        return 1

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    districts = load_districts()

    print(f"Reading {GRIB_PATH.name} ({GRIB_PATH.stat().st_size / 1e6:.0f} MB)", flush=True)

    # Grid extent decides which districts are representable at all. Read from the
    # first message so the check costs one decode rather than a full pass.
    grid_lat, grid_lon = _grid_extent()
    inside = districts["latitude"].between(grid_lat[0], grid_lat[1]) & districts[
        "longitude"
    ].between(grid_lon[0], grid_lon[1])
    outside = districts.loc[~inside, "name"].tolist()
    if outside:
        print(f"  outside grid extent, excluded: {', '.join(outside)}", flush=True)
    districts = districts[inside].reset_index(drop=True)
    print(f"  sampling {len(districts)} districts", flush=True)

    frame = extract_district_series(districts)
    frame = add_derived_columns(frame)
    frame["date"] = pd.to_datetime(frame["valid_time"]).dt.date

    frame, fill_summary = fill_gaps(frame)
    frame = frame[OUTPUT_COLUMNS].sort_values(["district", "date"]).reset_index(drop=True)

    summary = validate(frame)

    stamp = datetime.now(UTC).strftime("%Y%m%d")
    csv_path = DATA_DIR / f"climate_daily_{stamp}.csv"
    frame.to_csv(csv_path, index=False)

    manifest = {
        "generated_at": datetime.now(UTC).isoformat(),
        "git_commit": git_commit_sha(),
        "source_grib": str(GRIB_PATH.name),
        "source_grib_bytes": GRIB_PATH.stat().st_size,
        "source_description": "ECMWF ERA5 reanalysis, daily, 0.25 degree grid",
        "accumulation_note": (
            "Accumulated fields (tp, e) carry GRIB step 5-6: a one-hour accumulation "
            "sampled once daily at 00:00 UTC. They are NOT daily totals and this file "
            "provides no way to derive one. Columns are named _hourly_ accordingly."
        ),
        "excluded_variables": OCEAN_ONLY_VARIABLES,
        "districts_outside_grid": outside,
        "gap_filling": fill_summary,
        "validation": summary,
        "columns": OUTPUT_COLUMNS,
    }
    manifest_path = csv_path.with_suffix(".manifest.json")
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    print("\nWrote:")
    print(f"  {csv_path.name}  ({csv_path.stat().st_size / 1e6:.1f} MB)")
    print(f"  {manifest_path.name}")
    print(
        f"\n{summary['rows']} rows · {summary['districts']} districts · "
        f"{summary['date_min']} to {summary['date_max']}"
    )
    print(
        f"gap filling: {fill_summary['missing_cells_before']} missing cells before, "
        f"{summary['interpolated_rows']} rows flagged is_interpolated"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
