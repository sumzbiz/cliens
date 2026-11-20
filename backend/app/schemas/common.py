"""Shared schema primitives: GeoJSON polygon, error envelope, confidence indicator.

These are the shapes reused across more than one endpoint. Defining them once here
is what lets the generated TypeScript client share the same types on the frontend.

Polygon geometry is untrusted client input and is validated here structurally
(shape, ranges, ring closure) before any service sees it. Semantic validation that
needs a geometry engine — self-intersection, real-world area — happens in the sites
service via shapely, because it is business logic rather than schema shape.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core import constants

# A GeoJSON position is [longitude, latitude] — in that order, per RFC 7946.
# Getting this backwards is the single most common geospatial bug, so the ordering
# is enforced by the coordinate range checks below rather than left to convention.
Longitude = Annotated[
    float,
    Field(
        ge=constants.MIN_LONGITUDE,
        le=constants.MAX_LONGITUDE,
        description="WGS84 longitude",
    ),
]
Latitude = Annotated[
    float,
    Field(
        ge=constants.MIN_LATITUDE,
        le=constants.MAX_LATITUDE,
        description="WGS84 latitude",
    ),
]
Position = tuple[Longitude, Latitude]

# Resistance and damage ratios are dimensionless shares in [0, 1].
UnitInterval = Annotated[float, Field(ge=0.0, le=1.0)]

HorizonYear = Annotated[
    int,
    Field(ge=constants.HORIZON_START_YEAR, le=constants.HORIZON_END_YEAR),
]

ConfidenceLabel = Literal["high", "moderate", "low"]


class SchemaBase(BaseModel):
    """Base for every API schema.

    ``extra="forbid"`` makes unexpected fields an error rather than silently
    ignoring them, so a client sending a misspelled field is told about it instead
    of quietly getting default behaviour.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)


class PolygonGeometry(SchemaBase):
    """A GeoJSON Polygon restricted to what a building site can legitimately be.

    Only the exterior ring is accepted: a building footprint with a hole is not a
    meaningful site for this product, and supporting holes would complicate the
    area calculation without a use case.
    """

    type: Literal["Polygon"] = "Polygon"
    coordinates: Annotated[
        list[list[Position]],
        Field(
            min_length=1,
            max_length=1,
            description="Exactly one linear ring: the exterior boundary, in [lon, lat] order.",
        ),
    ]

    @model_validator(mode="after")
    def _validate_ring(self) -> Self:
        """Check ring size and closure.

        GeoJSON requires a linear ring's first and last positions to be identical.
        Many drawing libraries omit the closing point, so it is closed automatically
        rather than rejected — but only when the ring is otherwise valid.
        """
        ring = self.coordinates[0]

        if len(ring) < constants.MIN_POLYGON_RING_POINTS - 1:
            raise ValueError(
                f"a polygon ring needs at least {constants.MIN_POLYGON_RING_POINTS - 1} "
                f"distinct positions, got {len(ring)}"
            )
        if len(ring) > constants.MAX_POLYGON_RING_POINTS:
            raise ValueError(
                f"a polygon ring may have at most {constants.MAX_POLYGON_RING_POINTS} "
                f"positions, got {len(ring)}"
            )
        if ring[0] != ring[-1]:
            # Frozen model: rebuild the ring rather than mutating in place.
            object.__setattr__(self, "coordinates", [[*ring, ring[0]]])
        elif len(ring) < constants.MIN_POLYGON_RING_POINTS:
            raise ValueError(
                f"a closed polygon ring needs at least {constants.MIN_POLYGON_RING_POINTS} "
                f"positions, got {len(ring)}"
            )
        return self

    @property
    def exterior_ring(self) -> list[Position]:
        """The exterior ring, guaranteed closed by validation."""
        return self.coordinates[0]


class Centroid(SchemaBase):
    """A point location in WGS84."""

    longitude: Longitude
    latitude: Latitude


class ConfidenceInterval(SchemaBase):
    """A two-sided 95% interval around a model prediction.

    The brief forbids presenting a point estimate as certain, so every model-derived
    figure in the API carries one of these.
    """

    lower: float = Field(description="Lower bound of the 95% interval.")
    upper: float = Field(description="Upper bound of the 95% interval.")
    label: ConfidenceLabel = Field(description="Qualitative confidence in this estimate.")

    @model_validator(mode="after")
    def _ordered(self) -> Self:
        """An inverted interval indicates a calculation bug upstream."""
        if self.lower > self.upper:
            raise ValueError(f"interval lower bound {self.lower} exceeds upper bound {self.upper}")
        return self


class ErrorDetail(SchemaBase):
    """The error object inside an error response."""

    code: str = Field(description="Stable machine-readable error code.")
    message: str = Field(description="Human-readable explanation, safe to display.")
    details: dict[str, Any] | None = Field(
        default=None,
        description="Structured context. Never contains credentials or upstream payloads.",
    )
    request_id: str | None = Field(
        default=None,
        description="Correlation ID for this request; quote it when reporting a problem.",
    )


class ErrorResponse(SchemaBase):
    """The single error envelope every failing endpoint returns.

    Declared in the OpenAPI spec for all error statuses so the generated frontend
    client has one error shape to handle rather than several.
    """

    error: ErrorDetail
