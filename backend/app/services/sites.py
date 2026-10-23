"""Turns a drawn boundary into a saved site.

The boundary is an arbitrary polygon, not a rectangle: a real plot is rarely
square, and forcing one into a bounding box would overstate its area — often
badly. A triangular corner plot boxed to its extent is double its true size, and
that figure is the one the user is told their site measures.

This is the only layer that turns a ring of coordinates into the WKT PostGIS
stores, and the only one that decides whether a ring is a usable site at all.
"""

from __future__ import annotations

from shapely.geometry import Polygon
from shapely.validation import explain_validity

from app.core import calculations, constants
from app.core.exceptions import InvalidGeometryError
from app.core.logging import get_logger
from app.repositories.sites import SiteRecord, SiteRepository
from app.schemas.common import PolygonGeometry

logger = get_logger(__name__)


def _validate_ring(ring: list[tuple[float, float]]) -> None:
    """Reject a ring that is not a simple, non-degenerate polygon.

    Schema validation has already checked the ring's shape — length, closure,
    coordinate ranges. What it cannot check is whether the ring describes a real
    area, because that needs a geometry engine. A self-intersecting "bowtie" is
    the case that matters: PostGIS will still compute an area for it, but the
    figure is meaningless, so it must be refused before it is ever stored.

    Raises:
        InvalidGeometryError: If the ring self-intersects or encloses no area.
    """
    polygon = Polygon(ring)

    if not polygon.is_valid:
        raise InvalidGeometryError(
            "That outline crosses itself. Draw a boundary whose edges do not " "overlap.",
            details={"reason": explain_validity(polygon)},
        )

    # A ring can be valid and still enclose nothing — three points on a straight
    # line, or every vertex clicked in one spot.
    if polygon.area <= 0:
        raise InvalidGeometryError(
            "That outline encloses no area. Place at least three corners that are "
            "not in a straight line."
        )


def _to_wkt(ring: list[tuple[float, float]]) -> str:
    """A closed WGS84 ring as WKT, in (lon, lat) order."""
    points = ", ".join(f"{longitude} {latitude}" for longitude, latitude in ring)
    return f"POLYGON(({points}))"


class SiteService:
    """Saves a drawn boundary as a site."""

    def __init__(self, repository: SiteRepository) -> None:
        """Bind the service to its repository."""
        self._repository = repository

    async def save(self, geometry: PolygonGeometry, label: str | None) -> SiteRecord:
        """Persist a drawn polygon and return its authoritative area.

        The area is computed and checked before anything is written. Rejecting it
        here produces a clear 422 naming the actual figure; letting the database's
        own bounds constraint catch it would instead surface as an opaque 500,
        because a constraint violation is a database failure as far as the session
        dependency is concerned.

        Raises:
            InvalidGeometryError: If the ring is not a usable polygon, or its area
                falls outside what a building site can plausibly be.
        """
        ring = [(longitude, latitude) for longitude, latitude in geometry.exterior_ring]
        _validate_ring(ring)

        polygon_wkt = _to_wkt(ring)
        area_sq_m = await self._repository.compute_area_sq_m(polygon_wkt)
        area_sq_ft = calculations.sq_metres_to_sq_feet(area_sq_m)

        if not (constants.MIN_FLOOR_AREA_SQ_FT <= area_sq_ft <= constants.MAX_FLOOR_AREA_SQ_FT):
            raise InvalidGeometryError(
                f"That boundary works out to {area_sq_ft:,.0f} sq ft. A site this "
                f"tool can save must be between {constants.MIN_FLOOR_AREA_SQ_FT:,.0f} "
                f"and {constants.MAX_FLOOR_AREA_SQ_FT:,.0f} sq ft — draw a closer "
                f"outline.",
                details={
                    "area_sq_ft": round(area_sq_ft, 1),
                    "min_area_sq_ft": constants.MIN_FLOOR_AREA_SQ_FT,
                    "max_area_sq_ft": constants.MAX_FLOOR_AREA_SQ_FT,
                },
            )

        # The centroid comes from the geometry rather than a bounding-box midpoint,
        # which for a concave outline can land outside the plot entirely.
        centroid = Polygon(ring).centroid

        return await self._repository.insert(
            polygon_wkt=polygon_wkt,
            area_sq_ft=area_sq_ft,
            centroid_longitude=float(centroid.x),
            centroid_latitude=float(centroid.y),
            label=label,
        )
