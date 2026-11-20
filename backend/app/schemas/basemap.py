"""Place-search schemas."""

from __future__ import annotations

from pydantic import Field

from app.schemas.common import SchemaBase


class BasemapCapabilities(SchemaBase):
    """What the map can do with the imagery currently configured."""

    max_zoom: int = Field(
        description=(
            "Deepest zoom that returns real photography. The client must not offer "
            "more, or the user zooms into blank tiles that read as missing ground."
        )
    )
    deep_imagery_available: bool = Field(
        description="Whether a metered high-resolution provider is configured."
    )
    attribution: str = Field(
        description="Credit line the map must display for the active providers."
    )


class GeocodeMatch(SchemaBase):
    """One place matched by a search.

    The bounding box is optional because the geocoder does not always supply one —
    a street address is a point, not an area. A client should fly to the box when it
    exists and fall back to the point when it does not, rather than inventing a box
    around the point and implying an extent the geocoder never claimed.
    """

    label: str
    latitude: float
    longitude: float
    south: float | None = None
    north: float | None = None
    west: float | None = None
    east: float | None = None


class GeocodeResponse(SchemaBase):
    """Matches for a place search, best first."""

    matches: tuple[GeocodeMatch, ...]
