"""Persists the site boundary a user draws.

Area is always computed here from the stored geometry, on the WGS84 spheroid via
PostGIS, never trusted from the client. The frontend shows its own quick estimate
while the user is still plotting, purely for live feedback, but the figure that
gets saved — and the one shown once saving completes — is this one.
"""

from __future__ import annotations

from dataclasses import dataclass

from geoalchemy2 import WKTElement
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import constants
from app.core.logging import get_logger
from app.repositories.models import Site

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class SiteRecord:
    """A saved site, as returned to callers above this layer."""

    id: str
    area_sq_ft: float
    centroid_latitude: float
    centroid_longitude: float
    label: str | None
    created_at: str


class SiteRepository:
    """Writes drawn site boundaries."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind the repository to a session owned by the request."""
        self._session = session

    async def compute_area_sq_m(self, polygon_wkt: str) -> float:
        """The geodesic area of a WKT polygon, in square metres.

        Cast to ``geography`` rather than left as ``geometry`` — a geometry area
        would be computed in degrees², which is not a unit of area on a sphere.
        The geography cast measures on the WGS84 spheroid, which is what makes
        this the authoritative figure rather than a flat approximation.
        """
        statement = select(func.ST_Area(func.ST_GeogFromText(polygon_wkt)))
        return float((await self._session.execute(statement)).scalar_one())

    async def insert(
        self,
        *,
        polygon_wkt: str,
        area_sq_ft: float,
        centroid_longitude: float,
        centroid_latitude: float,
        label: str | None,
    ) -> SiteRecord:
        """Store one site. Area must already be validated by the caller.

        ``flush`` rather than ``commit``: the surrounding request's session
        dependency commits on a normal return, so committing here would end the
        transaction early and hide a later failure in the same request.
        """
        site = Site(
            geometry=WKTElement(polygon_wkt, srid=constants.WGS84_SRID),
            area_sq_ft=area_sq_ft,
            centroid_longitude=centroid_longitude,
            centroid_latitude=centroid_latitude,
            label=label,
        )
        self._session.add(site)
        await self._session.flush()  # populates id and created_at from the server

        logger.info("site_saved", site_id=str(site.id), area_sq_ft=round(area_sq_ft, 1))
        return self._to_record(site)

    @staticmethod
    def _to_record(site: Site) -> SiteRecord:
        return SiteRecord(
            id=str(site.id),
            area_sq_ft=site.area_sq_ft,
            centroid_latitude=site.centroid_latitude,
            centroid_longitude=site.centroid_longitude,
            label=site.label,
            created_at=site.created_at.isoformat(),
        )
