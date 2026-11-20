"""Building Quality Score request and response schemas.

Both modes share one response shape. Whether the user evaluated their own
specification or asked for a recommendation, the reply carries *both* sides, so a
before/after comparison is always available to the frontend and the report.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator

from app.core import constants
from app.schemas.common import SchemaBase

ElementSituation = Literal["enclosed", "sheltered", "exposed", "buried", "tidal"]
MemberType = Literal["slab", "beam", "column", "footing"]
ScoreBand = Literal["poor", "marginal", "adequate", "good", "excellent"]

Grade = Annotated[
    str,
    Field(pattern=r"^[Mm]\s*\d{2,3}$", description="Concrete grade, e.g. 'M30'."),
]


class ConcreteMixInput(SchemaBase):
    """A proposed concrete specification."""

    grade: Grade
    cement_content_kg_m3: Annotated[float, Field(gt=0, le=800)]
    water_cement_ratio: Annotated[float, Field(gt=0, le=1.5)]
    cement_type: Annotated[str, Field(max_length=40)] = "OPC"
    admixtures: tuple[Annotated[str, Field(max_length=60)], ...] = ()

    @field_validator("grade")
    @classmethod
    def _grade_must_be_supported(cls, value: str) -> str:
        """Normalise the grade (``m 30`` becomes ``M30``) and reject unsupported ones.

        The pattern alone admitted grades such as ``M999``, which the model then
        scored — higher than a real M30 mix — by extrapolating far outside the
        grades it was trained on.
        """
        normalised = "M" + value[1:].strip()
        if normalised not in constants.SUPPORTED_CONCRETE_GRADES:
            raise ValueError(
                f"grade must be one of {', '.join(constants.SUPPORTED_CONCRETE_GRADES)}"
            )
        return normalised

    @field_validator("cement_type")
    @classmethod
    def _cement_type_must_be_supported(cls, value: str) -> str:
        """Reject cement types the rules and the model have no knowledge of."""
        if value not in constants.SUPPORTED_CEMENT_TYPES:
            raise ValueError(
                f"cement_type must be one of {', '.join(constants.SUPPORTED_CEMENT_TYPES)}"
            )
        return value


class MaterialSelectionInput(SchemaBase):
    """What the user proposes to build with."""

    concrete: ConcreteMixInput
    walling_material_id: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]*$", max_length=80)]
    nominal_cover_mm: Annotated[
        float,
        Field(
            gt=0,
            le=constants.MAX_NOMINAL_COVER_MM,
            description=(
                "Nominal concrete cover to the reinforcement, in mm. Required: it is "
                "the largest single control on how long the steel stays protected."
            ),
        ),
    ]
    element_situation: ElementSituation = "exposed"


def _require_one_situation(
    situation: ElementSituation, materials: MaterialSelectionInput | None
) -> None:
    """Reject a request whose two element situations disagree.

    The situation appears at the top level and, for compatibility, inside
    ``materials``. They used to be read separately: with the nested one omitted
    it defaulted to "exposed", so the user's specification was judged against a
    different exposure class than the recommendation and the page header in the
    same response. The top level is now the only one used; an explicit nested
    value that contradicts it is an error rather than a silent override.
    """
    if (
        materials is not None
        and "element_situation" in materials.model_fields_set
        and materials.element_situation != situation
    ):
        raise ValueError(
            f"materials.element_situation ({materials.element_situation!r}) contradicts "
            f"element_situation ({situation!r}); send it once, at the top level"
        )


class ScoreRequest(SchemaBase):
    """Score a district.

    ``materials`` is optional: omitting it is recommend-only mode, and the reply
    then compares the recommendation against a conventional baseline so the
    "before" side is still meaningful.
    """

    district: Annotated[str, Field(min_length=1, max_length=80)]
    materials: MaterialSelectionInput | None = None
    element_situation: ElementSituation = "exposed"
    member: MemberType = Field(
        default="beam", description="The reinforced-concrete member, which sets its cover."
    )

    @model_validator(mode="after")
    def _situations_agree(self) -> ScoreRequest:
        _require_one_situation(self.element_situation, self.materials)
        return self


class ComplianceFindingResponse(SchemaBase):
    """One requirement checked against one proposed value."""

    parameter: str
    label: str
    required: float
    provided: float
    compliant: bool
    margin_ratio: float = Field(
        description="Signed fractional margin: positive exceeds the requirement."
    )
    standard: str
    message: str


class RecommendationResponse(SchemaBase):
    """An applicable reference-table recommendation."""

    id: str
    condition_label: str
    material: str
    purpose: str
    standard: str
    followed: bool = Field(description="Whether the selection already satisfies this.")


class ServiceLifeResponse(SchemaBase):
    """How long this specification implies the concrete will serve.

    Anchored on the design life IS 456's durability provisions are written to
    deliver, then adjusted by how far the mix sits from those provisions. It is
    not a prediction fitted to observed failures — no such dataset exists for this
    — which is why a range is returned rather than a single year, and why
    ``basis`` travels with it rather than living only in the documentation.
    """

    years: float = Field(description="Point estimate, in years.")
    lower_years: float = Field(description="Lower bound of the plausible band.")
    upper_years: float = Field(description="Upper bound of the plausible band.")
    baseline_years: float = Field(
        description="The design life a specification meeting the code exactly would give."
    )
    basis: str = Field(description="One line stating what the estimate is derived from.")


class ScoredSelectionResponse(SchemaBase):
    """One specification, scored and explained."""

    concrete: ConcreteMixInput
    walling_material_id: str
    nominal_cover_mm: float
    member: MemberType
    score: float = Field(
        ge=0, le=100, description="Headline 0-100 score, computed by the IS 456 rules engine."
    )
    model_score: float = Field(
        ge=0,
        le=100,
        description="The ML model's estimate of the same score, returned as a cross-check.",
    )
    band: ScoreBand
    compliant: bool
    findings: tuple[ComplianceFindingResponse, ...]
    service_life: ServiceLifeResponse


class ClimateProfileResponse(SchemaBase):
    """The measured climate a score was based on."""

    district: str
    distance_to_coast_km: float
    mean_relative_humidity_percent: float
    mean_max_temperature_c: float
    max_wind_gust_ms: float
    wet_hours_fraction: float = Field(
        description=(
            "Fraction of sampled hours with rainfall. Used instead of an annual "
            "depth because the source accumulates over one hour per day."
        )
    )
    wet_dry_cycles_per_year: float
    observation_days: int


class ScoreResponse(SchemaBase):
    """Before and after, with the reasoning behind both."""

    district: str
    climate: ClimateProfileResponse
    exposure_class: str
    exposure_label: str
    exposure_reasons: tuple[str, ...]

    proposed: ScoredSelectionResponse
    recommended: ScoredSelectionResponse
    improvement: float = Field(description="Points the recommendation adds.")

    recommendations: tuple[RecommendationResponse, ...]
    model_version: str
    data_source: dict[str, str] = Field(
        description="Provenance of the climate data behind this score."
    )
    climate_provenance: ClimateProvenanceResponse | None = Field(
        default=None,
        description=(
            "How the climate was derived. Null for a named district, whose reading "
            "is measured directly. Always populated for a drawn area."
        ),
    )


class DistrictLocation(SchemaBase):
    """Where a supported district's climate is actually measured.

    These are the coordinates of the climate grid CELL, not of the district
    headquarters. That is deliberate: the cell is where the reading comes from, so
    a marker placed here sits on the data rather than on a town that merely falls
    inside it. Several districts legitimately share one cell.
    """

    name: str
    grid_latitude: float = Field(description="Latitude of the climate grid cell, WGS84.")
    grid_longitude: float = Field(description="Longitude of the climate grid cell, WGS84.")


Latitude = Annotated[float, Field(ge=-90, le=90, description="WGS84 latitude.")]
Longitude = Annotated[float, Field(ge=-180, le=180, description="WGS84 longitude.")]


class PinRequest(SchemaBase):
    """A point dropped on a map or globe."""

    latitude: Latitude
    longitude: Longitude


class PinResolutionResponse(SchemaBase):
    """Which grid cell a dropped pin falls in.

    ``distance_km`` is returned so the interface can be honest about what was
    actually resolved: a pin 20 km from the node is answered by that node's reading,
    not by a reading taken where the user clicked.
    """

    district: str
    grid_latitude: float
    grid_longitude: float
    distance_km: float = Field(
        description="Great-circle distance from the pin to the grid node it resolved to."
    )


class AreaBoundsInput(SchemaBase):
    """A site boundary drawn on the map.

    Ordering is validated rather than silently corrected: a reversed rectangle means
    the client computed it wrongly, and quietly swapping the corners would hide that
    bug behind a plausible-looking score.
    """

    south: Latitude
    north: Latitude
    west: Longitude
    east: Longitude

    @model_validator(mode="after")
    def _check_ordering(self) -> AreaBoundsInput:
        if self.south >= self.north:
            raise ValueError("south must be less than north")
        if self.west >= self.east:
            raise ValueError("west must be less than east")
        return self


class AreaScoreRequest(SchemaBase):
    """Score a drawn area rather than a named district."""

    area: AreaBoundsInput
    materials: MaterialSelectionInput | None = None
    element_situation: ElementSituation = "exposed"
    member: MemberType = Field(
        default="beam", description="The reinforced-concrete member, which sets its cover."
    )

    @model_validator(mode="after")
    def _situations_agree(self) -> AreaScoreRequest:
        _require_one_situation(self.element_situation, self.materials)
        return self


class ClimateProvenanceResponse(SchemaBase):
    """How the climate behind a score was arrived at.

    Present only for area scoring, and always present there. An interpolated value
    must never be presentable as a measured one, so the flag travels with the score
    rather than being something the interface can forget to ask for.
    """

    interpolated: bool = Field(
        description=(
            "True when no measured grid node fell inside the drawn area and the "
            "climate was inverse-distance weighted from surrounding nodes."
        )
    )
    enclosed_node_count: int = Field(
        description="Measured grid nodes that fell inside the drawn area."
    )
    source_districts: tuple[str, ...] = Field(
        description="The measured cells the value was built from."
    )
    nearest_source_km: float = Field(
        description="Distance from the area's centre to the nearest contributing cell."
    )


class CoverageBounds(SchemaBase):
    """The rectangle the observed climate record actually covers.

    Published so a globe can draw the supported region rather than letting the user
    discover it by being refused. Derived from the loaded profiles, never hardcoded,
    so it cannot drift from the data.
    """

    south: float
    north: float
    west: float
    east: float


class DistrictListResponse(SchemaBase):
    """Districts that have a measured climate profile."""

    districts: tuple[str, ...]
    locations: tuple[DistrictLocation, ...] = Field(
        description="Coordinates for each supported district, for placing map markers."
    )
    grid_resolution_km: float = Field(
        description=(
            "Width of one climate grid cell. A picker must not imply finer precision "
            "than this, because every point inside one cell shares a single reading."
        )
    )
    coverage: CoverageBounds = Field(description="The region a dropped pin can be scored inside.")
    max_pin_distance_km: float = Field(
        description=(
            "How far a pin may sit from a grid node and still resolve. Beyond this "
            "the request is refused rather than answered from a distant node."
        )
    )
    observation_start: str
    observation_end: str
    source: str
