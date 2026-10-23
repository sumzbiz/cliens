"""Every named threshold, weight and physical constant, each with its source documented.

No numeric literal may appear in a service, repository or model wrapper. Everything
lives here with a comment stating where it came from.

Provenance is labelled explicitly on each block:

* ``CODIFIED``   — taken from a published standard or an official classification.
* ``LITERATURE`` — taken from peer-reviewed work, cited inline.
* ``CALIBRATED`` — a product judgement chosen by us. These are the numbers most
  worth challenging, and they are listed in the README's "Known limitations".

Units follow the canonical set in CLAUDE.md: wind m/s, rainfall mm, temperature °C,
area sq ft, coordinates WGS84 (lon, lat).
"""

from __future__ import annotations

from typing import Final

# ---------------------------------------------------------------------------
# Scoring horizon
#
# CALIBRATED. The product's stated window. 2025 is "today" for a permit decision
# and 2055 is a 30-year horizon, which matches the term of a typical Indian home
# loan — the period over which a lender or insurer carries the risk.
# ---------------------------------------------------------------------------
HORIZON_START_YEAR: Final[int] = 2025
HORIZON_END_YEAR: Final[int] = 2055
HORIZON_YEARS: Final[tuple[int, ...]] = tuple(range(HORIZON_START_YEAR, HORIZON_END_YEAR + 1))

# ---------------------------------------------------------------------------
# Hazard reference intensities
#
# Each hazard is normalised to a dimensionless intensity by dividing the projected
# value by its reference. An intensity of 1.0 means "at the reference severity".
# ---------------------------------------------------------------------------

# CODIFIED. IS 875 (Part 3): 2015, Wind Loads on Buildings and Structures — basic
# wind speed for the Chennai / north coastal Tamil Nadu zone, in m/s (3-second gust
# at 10 m above ground, 50-year return period). Structures in this zone are designed
# to this speed, so it is the natural point at which design margin is exhausted.
WIND_REFERENCE_MS: Final[float] = 50.0

# CODIFIED. IMD rainfall classification: "extremely heavy rainfall" is >= 204.5 mm
# in 24 hours. Used as the reference for pluvial flood loading.
RAINFALL_REFERENCE_MM_PER_DAY: Final[float] = 204.5

# CODIFIED. IMD heat wave criteria for the plains: a heat wave is declared when the
# maximum temperature reaches 40 °C. Used as the reference for heat loading.
HEAT_REFERENCE_MAX_TEMP_C: Final[float] = 40.0

# LITERATURE. Sherwood & Huber (2010), "An adaptability limit to climate change due
# to heat stress", PNAS 107(21):9552-9555 — sustained wet-bulb temperature above
# 35 °C exceeds human thermoregulation, i.e. unlivable regardless of construction.
# This is a hard override on the score: no material choice defeats it.
WET_BULB_SURVIVABILITY_LIMIT_C: Final[float] = 35.0

# CALIBRATED. Normalised hazard intensity is clamped to this ceiling. Beyond roughly
# twice the design reference the damage relationship is no longer meaningfully
# resolved by the calibration data, so extrapolating further would imply precision
# the model does not have.
MAX_NORMALISED_HAZARD_INTENSITY: Final[float] = 2.0

# ---------------------------------------------------------------------------
# Building component weights
#
# CALIBRATED, informed by post-cyclone damage surveys, which consistently find that
# envelope failure (roof covering, then roof structure) initiates the damage chain in
# wind events, while foundation and lower-wall condition dominates flood loss. The
# weights must sum to 1.0; `validate_constants()` enforces this at import time.
# ---------------------------------------------------------------------------
COMPONENT_WEIGHTS: Final[dict[str, float]] = {
    "roofing": 0.45,
    "walls": 0.35,
    "foundation": 0.20,
}

# ---------------------------------------------------------------------------
# Per-component hazard sensitivity
#
# CALIBRATED. How much each hazard acts on each component. Rows sum to 1.0.
# Roofing is dominated by wind uplift; foundations by flood scour and saturation;
# walls sit between the two and carry most of the heat-transfer burden.
# ---------------------------------------------------------------------------
COMPONENT_HAZARD_SENSITIVITY: Final[dict[str, dict[str, float]]] = {
    "roofing": {"wind": 0.70, "flood": 0.05, "heat": 0.25},
    "walls": {"wind": 0.30, "flood": 0.35, "heat": 0.35},
    "foundation": {"wind": 0.05, "flood": 0.85, "heat": 0.10},
}

HAZARDS: Final[tuple[str, ...]] = ("wind", "flood", "heat")
BUILDING_COMPONENTS: Final[tuple[str, ...]] = ("foundation", "walls", "roofing")

# ---------------------------------------------------------------------------
# Damage and insurability thresholds
# ---------------------------------------------------------------------------

# CALIBRATED, aligned to catastrophe-modelling practice. A mean damage ratio of 0.40
# corresponds to the point at which repair cost approaches the economic write-off
# point for light residential construction, which is where cover is withdrawn or
# repriced beyond reach. This is the single most consequential number in the product
# and is called out in the README as a product threshold, not a regulatory one.
UNINSURABLE_DAMAGE_RATIO: Final[float] = 0.40

# CALIBRATED. Damage ratio is a physical quantity bounded to [0, 1]; predictions from
# the calibration model are clamped to this range.
MIN_DAMAGE_RATIO: Final[float] = 0.0
MAX_DAMAGE_RATIO: Final[float] = 1.0

# ---------------------------------------------------------------------------
# Exposure scaling by floor area
#
# CALIBRATED. Larger footprints present more envelope to wind and more slab to
# flooding, but loss ratio scales far more weakly than area. A logarithmic term
# anchored at a reference footprint captures that without letting a large building
# dominate the score.
# ---------------------------------------------------------------------------
# Median independent-house plot area in urban Tamil Nadu, in sq ft (a 30x40 ft plot).
REFERENCE_FLOOR_AREA_SQ_FT: Final[float] = 1200.0
AREA_EXPOSURE_COEFFICIENT: Final[float] = 0.08
MIN_FLOOR_AREA_SQ_FT: Final[float] = 100.0
MAX_FLOOR_AREA_SQ_FT: Final[float] = 1_000_000.0

# ---------------------------------------------------------------------------
# Geometry validation
#
# CALIBRATED bounds for untrusted polygon input.
# ---------------------------------------------------------------------------
# A closed GeoJSON linear ring repeats its first point, so a triangle has 4 entries.
MIN_POLYGON_RING_POINTS: Final[int] = 4
# Guards against a client posting a multi-megabyte traced coastline.
MAX_POLYGON_RING_POINTS: Final[int] = 1_000
# Polygon area is bounded by MIN/MAX_FLOOR_AREA_SQ_FT above. A second pair of
# bounds in square metres would be a duplicate that could drift out of agreement
# with the database CHECK constraint, so there deliberately isn't one.

# WGS84 valid coordinate ranges (EPSG:4326).
MIN_LONGITUDE: Final[float] = -180.0
MAX_LONGITUDE: Final[float] = 180.0
MIN_LATITUDE: Final[float] = -90.0
MAX_LATITUDE: Final[float] = 90.0

# The spatial reference the whole system stores and exchanges geometry in.
WGS84_SRID: Final[int] = 4326

# ---------------------------------------------------------------------------
# Unit conversions
#
# CODIFIED. Exact by international definition (1 inch = 25.4 mm exactly).
# ---------------------------------------------------------------------------
SQ_METRES_PER_SQ_FOOT: Final[float] = 0.09290304
SQ_FEET_PER_SQ_METRE: Final[float] = 1.0 / SQ_METRES_PER_SQ_FOOT

# CODIFIED. IMD publishes wind speeds in km/h; internal calculations use m/s.
MS_PER_KMPH: Final[float] = 1000.0 / 3600.0

# CODIFIED. Exact by definition of the Celsius scale. CMIP6 temperature bands are
# published in kelvin; the internal unit is degrees Celsius.
KELVIN_TO_CELSIUS_OFFSET: Final[float] = 273.15

# CODIFIED. CMIP6 precipitation is a flux in kg m-2 s-1, numerically equal to mm/s
# for liquid water. Multiplying by the seconds in a day gives mm/day.
SECONDS_PER_DAY: Final[float] = 86_400.0

# CODIFIED. ERA5 publishes total precipitation as a depth in metres.
MM_PER_METRE: Final[float] = 1_000.0

# LITERATURE. Coefficients of the August-Roche-Magnus saturation vapour pressure
# approximation, in the refined form of Alduchov & Eskridge (1996), "Improved
# Magnus Form Approximation of Saturation Vapor Pressure", Journal of Applied
# Meteorology 35(4):601-609. Accurate to better than 0.4% over -40 to +50 C, which
# covers every temperature this product encounters.
MAGNUS_COEFFICIENT_A: Final[float] = 17.625
MAGNUS_COEFFICIENT_B_C: Final[float] = 243.04

# ---------------------------------------------------------------------------
# Earth Engine datasets
#
# CODIFIED dataset identifiers, CALIBRATED choices of scenario and band.
# ---------------------------------------------------------------------------
# NASA Earth Exchange Global Daily Downscaled Projections. Daily, ~25 km, and the
# standard downscaled CMIP6 product for local impact work.
EARTH_ENGINE_CMIP6_DATASET: Final[str] = "NASA/GDDP-CMIP6"

# CALIBRATED. SSP2-4.5 is the "middle of the road" pathway. A permit decision needs
# a central estimate rather than a worst case: scoring every site against SSP5-8.5
# would declare almost everything uninsurable and make the tool useless for
# comparing material choices, which is its actual purpose.
EARTH_ENGINE_CMIP6_SCENARIO: Final[str] = "ssp245"

# CALIBRATED. A multi-model subset rather than one model, because single-model
# projections carry structural bias. The spread across these members is what the
# reported confidence interval is derived from.
EARTH_ENGINE_CMIP6_MODELS: Final[tuple[str, ...]] = (
    "ACCESS-CM2",
    "MPI-ESM1-2-HR",
    "MRI-ESM2-0",
    "NorESM2-MM",
)

# CODIFIED. Band names as published in NASA/GDDP-CMIP6.
EARTH_ENGINE_BAND_MAX_TEMPERATURE: Final[str] = "tasmax"  # kelvin
EARTH_ENGINE_BAND_PRECIPITATION: Final[str] = "pr"  # kg m-2 s-1
EARTH_ENGINE_BAND_WIND_SPEED: Final[str] = "sfcWind"  # m/s at 10 m
EARTH_ENGINE_BAND_RELATIVE_HUMIDITY: Final[str] = "hurs"  # percent

# CALIBRATED. Radius in metres over which band values are reduced around the site
# centroid. Smaller than one CMIP6 grid cell, so the value reflects the cell the
# site sits in rather than averaging neighbouring cells.
EARTH_ENGINE_SAMPLE_RADIUS_M: Final[float] = 1_000.0

# ---------------------------------------------------------------------------
# IMD cyclone intensity classification
#
# CODIFIED. India Meteorological Department cyclone categories, defined by
# 3-minute sustained surface wind in km/h. Stored as lower bounds, ascending.
# Used to interpret IMD historical records and to label projected intensities.
# ---------------------------------------------------------------------------
# CALIBRATED. Tolerance applied when comparing a speed against a category bound.
# Internal wind speeds are metres per second, so classifying one means converting
# back to km/h — and that round trip is not exact in binary floating point (31 km/h
# returns as 30.999999999999996). Without this tolerance a speed sitting exactly on
# a boundary would be classified one category too low. A micro-km/h is far below any
# meaningful measurement precision, so it cannot mask a real difference.
CYCLONE_CATEGORY_BOUNDARY_TOLERANCE_KMPH: Final[float] = 1e-6

IMD_CYCLONE_CATEGORIES_KMPH: Final[tuple[tuple[str, float], ...]] = (
    ("Depression", 31.0),
    ("Deep Depression", 51.0),
    ("Cyclonic Storm", 62.0),
    ("Severe Cyclonic Storm", 89.0),
    ("Very Severe Cyclonic Storm", 118.0),
    ("Extremely Severe Cyclonic Storm", 166.0),
    ("Super Cyclonic Storm", 222.0),
)

# ---------------------------------------------------------------------------
# External data caching
#
# CALIBRATED. Cache entries key on the site centroid rounded to this precision, so
# two sites a few metres apart reuse one upstream response. Five decimal places is
# roughly 1.1 m at the equator — finer than any climate grid cell, so rounding
# cannot merge genuinely different climate conditions.
# ---------------------------------------------------------------------------
CACHE_COORDINATE_PRECISION_DP: Final[int] = 5

# CALIBRATED. CMIP6 projections are republished on a multi-year cadence and IMD
# historical records are appended seasonally, so a 30-day life keeps results stable
# within a permit cycle while still picking up upstream revisions.
CACHE_TTL_DAYS: Final[int] = 30

# ---------------------------------------------------------------------------
# External call policy
#
# CALIBRATED. Earth Engine aggregations are slow, so it gets a longer budget than a
# plain REST call. Retries use exponential backoff and apply only to transient
# failures (timeouts, 5xx, 429) — never to a 4xx, which would just fail again.
# ---------------------------------------------------------------------------
EXTERNAL_REQUEST_TIMEOUT_SECONDS: Final[float] = 10.0
EARTH_ENGINE_TIMEOUT_SECONDS: Final[float] = 60.0
GEMINI_TIMEOUT_SECONDS: Final[float] = 30.0
# CALIBRATED. The prompt caps the report at 400 words; this token ceiling leaves
# comfortable headroom above that while bounding cost and latency.
GEMINI_MAX_OUTPUT_TOKENS: Final[int] = 1_200
EXTERNAL_MAX_RETRY_ATTEMPTS: Final[int] = 3
EXTERNAL_RETRY_INITIAL_BACKOFF_SECONDS: Final[float] = 0.5
EXTERNAL_RETRY_MAX_BACKOFF_SECONDS: Final[float] = 8.0
RETRYABLE_HTTP_STATUS_CODES: Final[frozenset[int]] = frozenset({408, 429, 500, 502, 503, 504})

# ---------------------------------------------------------------------------
# Damage vulnerability curve
#
# CALIBRATED. The relationship between resistance-weighted stress and expected
# damage ratio follows the exponential vulnerability form used throughout
# catastrophe modelling:
#
#     damage = 1 - exp(-k * stress^alpha)
#
# The two coefficients are fixed by two anchor points we chose deliberately:
#
#   stress 1.0 (the full design load reaches the structure) -> damage 0.35
#   stress 2.0 (twice the design load)                      -> damage 0.75
#
# Below the uninsurability threshold at exactly the design load, above it well
# before twice the design load. These generate the synthetic training data in
# /ml, so the damage model learns this curve — see the README's honest note about
# what that does and does not demonstrate.
# ---------------------------------------------------------------------------
DAMAGE_CURVE_SCALE_K: Final[float] = 0.4308
DAMAGE_CURVE_SHAPE_ALPHA: Final[float] = 1.6861

# CALIBRATED. Multiplicative lognormal spread applied when generating synthetic
# damage observations, representing the scatter real post-event damage surveys show
# around any fitted vulnerability curve.
DAMAGE_OBSERVATION_NOISE_SIGMA: Final[float] = 0.15

# CALIBRATED. Size of the synthetic training set. Large enough for the ensemble to
# converge, small enough to retrain in seconds on a laptop.
SYNTHETIC_TRAINING_SAMPLES: Final[int] = 6_000
TRAIN_TEST_SPLIT_FRACTION: Final[float] = 0.2

# CALIBRATED. Random forest hyperparameters. The ensemble is deliberately shallow:
# the underlying relationship is smooth and low-dimensional, so deeper trees would
# fit noise without improving held-out error, and the per-tree spread is what the
# reported confidence interval is derived from.
DAMAGE_MODEL_N_ESTIMATORS: Final[int] = 200
DAMAGE_MODEL_MAX_DEPTH: Final[int] = 8
DAMAGE_MODEL_MIN_SAMPLES_LEAF: Final[int] = 5

RANKER_MODEL_N_ESTIMATORS: Final[int] = 150
RANKER_MODEL_MAX_DEPTH: Final[int] = 6

# ---------------------------------------------------------------------------
# IS 456 exposure classification
#
# IS 456 Table 3 defines exposure conditions in words ("exposed to severe rain",
# "alternate wetting and drying", "sea water spray"). Turning a measured climate
# record into one of those classes needs numeric thresholds, which the standard
# does not supply. These are ours, chosen to match the wording, and are the main
# judgement in the rules engine — listed in the README as such.
# ---------------------------------------------------------------------------

# CALIBRATED. Salt-laden air is the mechanism behind the "coastal" exposure
# wording. Its influence is generally treated as reaching a few tens of kilometres
# inland, so a site within this distance is classified as at least Severe.
COASTAL_INFLUENCE_KM: Final[float] = 25.0

# CALIBRATED. "Concrete surfaces exposed to sea water spray" implies effectively
# shoreline proximity. Within this distance the class rises to Very Severe.
DIRECT_SEA_SPRAY_KM: Final[float] = 1.0

# CALIBRATED. Fraction of sampled hours that must be wet for the site to count as
# a wet regime, satisfying "exposed to severe rain" on an exposed element.
#
# Expressed as an index rather than an annual depth because the GRIB accumulates
# rainfall over a single hour at 00:00 UTC; deriving "mm per year" from that would
# mean inventing the diurnal cycle. Every district is sampled identically, so the
# index compares them faithfully. Set near the wetter end of the inland Tamil Nadu
# districts observed in the 2016-2026 record.
WET_REGIME_INDEX: Final[float] = 0.30

# CALIBRATED. Sustained relative humidity at or above this level is the condition
# under which reinforcement corrosion proceeds materially faster, which is what the
# "severe condensation" wording is protecting against.
HIGH_HUMIDITY_PERCENT: Final[float] = 75.0

# CALIBRATED. A day is "wet" above this rainfall depth. Counting transitions
# between wet and dry days is how "alternate wetting and drying" is measured.
WET_DAY_RAINFALL_MM: Final[float] = 2.5

# CALIBRATED. This many wet/dry transitions a year means the surface is cycling
# often enough for the Severe wording to apply.
WET_DRY_CYCLES_SEVERE_PER_YEAR: Final[float] = 60.0

# ---------------------------------------------------------------------------
# Building Quality Score
#
# CALIBRATED. The 0-100 score is defined by these weights, applied to the rules
# engine's compliance margins. They are the product's own scale, not a published
# one, and are stated as such wherever the score is shown.
# ---------------------------------------------------------------------------
# A fully compliant build starts here rather than at 100, leaving headroom so that
# exceeding the minimums is visibly better than merely meeting them.
COMPLIANT_BASE_SCORE: Final[float] = 78.0

# CALIBRATED. Any failed required check caps the score at the top of the
# marginal band, so an ML estimate cannot present a non-compliant design as good.
NONCOMPLIANT_SCORE_CAP: Final[float] = 60.0

# Points per unit of fractional shortfall. Large enough that a materially
# non-compliant build cannot reach a passing-looking score.
SCORE_SHORTFALL_WEIGHT: Final[float] = 55.0

# Points per unit of fractional headroom, and the cap on any single requirement's
# contribution — over-specifying one parameter should not mask another's weakness.
SCORE_HEADROOM_WEIGHT: Final[float] = 18.0
SCORE_HEADROOM_CAP: Final[float] = 6.0

# Awarded in proportion to how many applicable reference-table recommendations the
# selection already follows.
SCORE_RECOMMENDATION_WEIGHT: Final[float] = 10.0

# CODIFIED. IS 1077 caps water absorption for common burnt clay brick at 20% by
# weight; used as the reference against which a walling material's absorption
# headroom is measured.
REFERENCE_WATER_ABSORPTION_PERCENT: Final[float] = 20.0

# CALIBRATED. Penalty applied when a walling material is used in a climate the
# reference table warns against.
WALLING_MISMATCH_PENALTY: Final[float] = -0.25

# CALIBRATED. Margins the recommendation adds above each IS 456 minimum.
# Specifying exactly at the limit leaves nothing for batching variation on site,
# so the advice sits a little clear of it.
RECOMMENDED_CEMENT_MARGIN_KG_M3: Final[float] = 20.0
RECOMMENDED_WATER_CEMENT_MARGIN: Final[float] = 0.03

# CALIBRATED. Score bands used for the plain-language verdict in the report.
SCORE_BAND_THRESHOLDS: Final[tuple[tuple[str, float], ...]] = (
    ("poor", 40.0),
    ("marginal", 60.0),
    ("adequate", 75.0),
    ("good", 88.0),
    ("excellent", 100.0),
)

# CODIFIED. The bundled ERA5 grid is 0.25 degrees, which is about 27 km at this
# latitude. Published so the UI can cap a map or globe picker at a zoom that
# matches it: every point inside one cell shares a single climate reading, and six
# districts already resolve to the same node. Offering street-level zoom would
# imply a per-building reading the data cannot support.
CLIMATE_GRID_RESOLUTION_KM: Final[float] = 27.0

# Mean Earth radius (IUGG), used to turn an angular separation into kilometres
# when resolving a dropped pin to the nearest grid node.
EARTH_MEAN_RADIUS_KM: Final[float] = 6371.0088

# How far a dropped pin may sit from the nearest grid node and still be scored.
#
# The nodes are one grid cell apart, so any point genuinely inside the observed
# region is within half a cell diagonal of one — 0.25 degrees square is about
# 19 km corner-to-centre at this latitude. Rounding up to 30 km covers the coastal
# nodes, whose cells are partly sea, without reaching a neighbouring region.
#
# This limit is the entire reason the pin cannot lie: nearest-node lookup alone
# would happily return a Tamil Nadu district for a pin dropped in Brazil. Beyond
# this distance the request is refused rather than answered with a number that
# describes somewhere else.
MAX_PIN_TO_GRID_DISTANCE_KM: Final[float] = 30.0

# ---------------------------------------------------------------------------
# Area selection and spatial interpolation
# ---------------------------------------------------------------------------
#
# When a selected area contains no grid node, its climate is interpolated from
# surrounding nodes. This is the one place interpolation is permitted, and only
# under the conditions below — a value produced this way is always flagged so it is
# never silently merged with a directly measured reading.
#
# How far a source node may be from the selected area's centre and still
# contribute. Three grid cells. Beyond roughly this distance the Western Ghats and
# the coastline change the regime enough that a neighbouring reading stops being
# evidence about this location and becomes a guess dressed as one.
MAX_INTERPOLATION_DISTANCE_KM: Final[float] = 85.0

# Inverse-distance weighting exponent. Two is the standard choice for meteorological
# fields: it falls off fast enough that a node three cells away barely competes with
# one in the adjacent cell, without the near-discontinuity that higher powers give.
INTERPOLATION_DISTANCE_POWER: Final[float] = 2.0

# At most this many nodes contribute to one interpolated value. Averaging over the
# whole region would flatten every location toward a regional mean, which reads as
# confident and is worse than a coarse but local answer.
MAX_INTERPOLATION_SOURCES: Final[int] = 4

# Distance below which a node is treated as coincident with the query point, taken
# directly instead of weighted. Prevents a division by zero and reflects that a
# reading 100 m away is the reading.
COINCIDENT_NODE_DISTANCE_KM: Final[float] = 0.1

# ---------------------------------------------------------------------------
# Basemap tiles and place search
# ---------------------------------------------------------------------------
#
# JPEG quality for a composited map tile. Chosen by measurement rather than taste:
# at 95 with chroma subsampling disabled, the mean error on label pixels of a real
# tile was 7.6, against 17.7 at the more usual quality 92, for 5 KB more.
TILE_IMAGE_QUALITY: Final[int] = 95

# Chroma subsampling mode: 0 means 4:4:4, i.e. none.
#
# This is the single setting that decides whether place names are readable. The
# tile is a photograph with thin coloured type drawn on top, and JPEG's default
# 4:2:0 discards three quarters of the colour resolution — unnoticeable on
# vegetation, ruinous for coloured glyph edges. WebP was tried as an alternative
# and measured worse on text at every quality level, at a larger size.
TILE_CHROMA_SUBSAMPLING: Final[int] = 0

# Deepest zoom the tile endpoint will serve from the keyless Esri sources.
#
# Verified by probe: past this Esri returns a placeholder rather than photography.
# At z19 one pixel is roughly 0.3 m at the equator — enough to see a building's
# outline, not enough to read its roof.
MAX_TILE_ZOOM_ESRI: Final[int] = 19

# Deepest zoom when a Mapbox token is configured. Mapbox Satellite publishes to 22
# in populated areas, roughly 0.04 m per pixel, which is the level at which roof
# structure and individual trees resolve.
MAX_TILE_ZOOM_MAPBOX: Final[int] = 22

# The hard ceiling accepted by the route. The per-provider limit is enforced above
# this, but the path parameter needs one fixed bound to validate against.
MAX_TILE_ZOOM: Final[int] = MAX_TILE_ZOOM_MAPBOX

# How long a composited tile stays in the process cache. Satellite basemaps change
# on a scale of months, so this is about avoiding a repeat round trip while panning,
# not about freshness.
TILE_CACHE_SECONDS: Final[int] = 86_400

# Composited tiles held in memory. At roughly 40 KB each this is a few tens of MB,
# which buys smooth panning without growing without bound.
TILE_CACHE_ENTRIES: Final[int] = 512

# Nominatim's usage policy requires an identifying User-Agent naming the
# application. Requests without one are refused.
GEOCODER_USER_AGENT: Final[str] = "BuildingQualityScore/0.1 (climate-materials scoring tool)"

# Matches returned by a place search. Enough to disambiguate a common place name
# without turning the picker into a list to read.
GEOCODER_RESULT_LIMIT: Final[int] = 6

# ---------------------------------------------------------------------------
# Rate limiting
#
# CALIBRATED. How often the limiter sweeps expired per-client windows out of memory.
# Sweeping on every request would rescan the map under load; sweeping too rarely
# lets it grow. Thirty seconds keeps the map small without measurable overhead.
# ---------------------------------------------------------------------------
RATE_LIMIT_PRUNE_INTERVAL_SECONDS: Final[float] = 30.0

# ---------------------------------------------------------------------------
# Determinism
#
# CALIBRATED. A fixed seed for every stochastic operation (model training, synthetic
# data generation, any sampled uncertainty), so identical inputs always produce
# identical outputs as the brief requires.
# ---------------------------------------------------------------------------
RANDOM_SEED: Final[int] = 20231204  # Cyclone Michaung's Chennai landfall, 4 Dec 2023

# ---------------------------------------------------------------------------
# Model confidence reporting
#
# CALIBRATED. Predictions are reported with a confidence band derived from the
# ensemble's prediction spread. These bounds keep the reported band honest: never
# claimed tighter than the model's own test-set error, never so wide as to be
# useless.
# ---------------------------------------------------------------------------
MIN_CONFIDENCE_INTERVAL_WIDTH: Final[float] = 0.02
MAX_CONFIDENCE_INTERVAL_WIDTH: Final[float] = 0.50
CONFIDENCE_INTERVAL_Z_SCORE: Final[float] = 1.96  # two-sided 95% interval, normal approx.

# CALIBRATED. Qualitative confidence labels attached to a score, by the width of the
# uncertainty band on the crossing year in years.
CONFIDENCE_LABEL_THRESHOLDS_YEARS: Final[tuple[tuple[str, float], ...]] = (
    ("high", 3.0),
    ("moderate", 7.0),
    ("low", float("inf")),
)


def validate_constants() -> None:
    """Assert the internal consistency this module's callers rely on.

    Called at application startup. A weight table that silently stopped summing to
    1.0 would bias every score in a way no test of a single function would catch.

    Raises:
        ValueError: If any weighting table is inconsistent.
    """
    component_total = sum(COMPONENT_WEIGHTS.values())
    if abs(component_total - 1.0) > 1e-9:
        raise ValueError(f"COMPONENT_WEIGHTS must sum to 1.0, got {component_total}")

    if set(COMPONENT_WEIGHTS) != set(BUILDING_COMPONENTS):
        raise ValueError("COMPONENT_WEIGHTS keys must match BUILDING_COMPONENTS")

    if set(COMPONENT_HAZARD_SENSITIVITY) != set(BUILDING_COMPONENTS):
        raise ValueError("COMPONENT_HAZARD_SENSITIVITY keys must match BUILDING_COMPONENTS")

    for component, sensitivities in COMPONENT_HAZARD_SENSITIVITY.items():
        if set(sensitivities) != set(HAZARDS):
            raise ValueError(f"COMPONENT_HAZARD_SENSITIVITY[{component!r}] must cover all hazards")
        total = sum(sensitivities.values())
        if abs(total - 1.0) > 1e-9:
            raise ValueError(
                f"COMPONENT_HAZARD_SENSITIVITY[{component!r}] must sum to 1.0, got {total}"
            )

    if HORIZON_START_YEAR >= HORIZON_END_YEAR:
        raise ValueError("HORIZON_START_YEAR must be before HORIZON_END_YEAR")

    if not MIN_DAMAGE_RATIO < UNINSURABLE_DAMAGE_RATIO < MAX_DAMAGE_RATIO:
        raise ValueError("UNINSURABLE_DAMAGE_RATIO must lie strictly within the damage range")


# ---------------------------------------------------------------------------
# Sarvam AI text-to-speech
# ---------------------------------------------------------------------------
#
# The model to synthesise with. Its speaker list is NOT the same as the general
# list in Sarvam's docs — `anushka`, which the docs show prominently, is rejected
# by this model. Verified live: kavitha, shruti, ritu, roopa, anand, vijay all
# work for ta-IN.
SARVAM_TTS_MODEL: Final[str] = "bulbul:v3"

SARVAM_TTS_ENDPOINT: Final[str] = "https://api.sarvam.ai/text-to-speech"

# Hard limit the REST endpoint enforces, confirmed by its own validation error.
# Narrating a question plus every option routinely exceeds it, so text is split
# into chunks below this and the pieces are played back-to-back.
SARVAM_MAX_TEXT_CHARACTERS: Final[int] = 2500

# Leaves room for the sentence-boundary search when chunking, so a split never
# lands mid-word and never overshoots the hard limit above.
SARVAM_CHUNK_TARGET_CHARACTERS: Final[int] = 1800

# HTTP statuses that mean "this key is spent", as opposed to a bad request. 429 is
# the documented rate limit; 402 and 403 cover an exhausted plan or a revoked key.
# Anything else is a fault in our request and retrying on another key would only
# produce the same error twice.
SARVAM_KEY_EXHAUSTED_STATUSES: Final[frozenset[int]] = frozenset({402, 403, 429})

# Synthesised audio held in memory, keyed by the hash of text, speaker and
# language. Narration is a small fixed set of questions, so this reaches a steady
# state quickly and makes every repeat visit free and instant.
VOICE_CACHE_ENTRIES: Final[int] = 256

# ---------------------------------------------------------------------------
# Estimated service life
#
# What this is, and what it is not. There is no dataset of "this building was
# specified like that and lasted N years", so nothing here is fitted to observed
# survival. This is a code-anchored estimate: it starts from the design life the
# IS 456 durability provisions are written to deliver, and adjusts it by how far
# the proposed mix sits from those provisions, using the established physics of
# how deterioration actually proceeds. It answers "how does this specification
# compare to the one the code says lasts 50 years", not "when will this fall
# down". The API returns it as a range for that reason.
# ---------------------------------------------------------------------------

# CODIFIED. IS 456:2000 clause 8 and Table 5 set minimum grade, minimum cement
# content and maximum water/cement ratio per exposure class. Those provisions are
# written to deliver a design service life of 50 years for ordinary structures,
# which is also the figure IS 456's own durability commentary and the National
# Building Code work to. A specification sitting exactly on the class minimums
# therefore scores exactly this.
DESIGN_SERVICE_LIFE_YEARS: Final[float] = 50.0

# LITERATURE. Reinforcement corrosion dominates the deterioration of RC in these
# exposures, and its onset is governed by chloride and CO2 ingress, which is
# diffusion-controlled. The apparent diffusion coefficient rises steeply and
# approximately exponentially with the water/cement ratio, because the capillary
# pore network that carries the ions is what excess water leaves behind.
#
# fib Bulletin 34 (Model Code for Service Life Design, 2006) and Papadakis,
# Vayenas & Fardis (1991), "Physical and chemical characteristics affecting the
# durability of concrete", ACI Materials Journal 88(2), both express the
# relationship in this form. Published exponents span roughly 5 to 9; 6.0 is at
# the conservative end, so an improvement in w/c buys less extra life here than
# the middle of that range would claim.
INGRESS_WATER_CEMENT_SENSITIVITY: Final[float] = 6.0

# CALIBRATED. Bounds on the estimate.
#
# The lower bound is not "the building falls down at 5 years" — it is the point
# below which this model stops discriminating usefully, because a mix that bad
# fails on workmanship and structural grounds long before diffusion physics is
# the binding constraint. The upper bound exists because past roughly a century
# the limit on a building's life stops being the concrete and becomes the
# foundation, the seismic standard it was built to, and whether anyone maintains
# it — none of which this model sees.
MIN_ESTIMATED_SERVICE_LIFE_YEARS: Final[float] = 5.0
MAX_ESTIMATED_SERVICE_LIFE_YEARS: Final[float] = 100.0

# CALIBRATED. Falling short of the minimum grade or cement content means the
# concrete does not meet the assumptions the 50-year target rests on — cover
# quality, binder available to bind chlorides, permeability. This is the fraction
# of service life lost per unit of relative shortfall on those parameters, taking
# the worst one rather than compounding them, because the weakest link governs.
SERVICE_LIFE_SHORTFALL_PENALTY: Final[float] = 1.5

# CALIBRATED. Service life models of this kind carry large scatter — real
# structures with identical specifications differ by decades depending on
# workmanship, curing and cover accuracy. Reporting a single year would imply a
# precision this cannot support, so the API returns this fractional band either
# side and the interface shows the range.
SERVICE_LIFE_UNCERTAINTY_FRACTION: Final[float] = 0.30
