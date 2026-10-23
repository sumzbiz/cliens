"""Schemas for saving a drawn site boundary."""

from __future__ import annotations

from typing import Annotated

from pydantic import Field

from app.schemas.common import PolygonGeometry, SchemaBase


class CreateSiteRequest(SchemaBase):
    """A drawn boundary to save.

    An arbitrary polygon rather than a rectangle. Real plots are rarely square,
    and a bounding box around a triangular corner plot claims roughly double its
    true area — which would then be the figure shown to the user as their site's
    size.
    """

    geometry: PolygonGeometry
    label: Annotated[str, Field(max_length=200)] | None = None


class SiteResponse(SchemaBase):
    """A saved site, with its authoritative area.

    ``area_sq_ft`` is the figure the frontend should display and cannot itself
    have supplied: it is computed by the server from the stored geometry on the
    WGS84 spheroid, which is why saving is worth a round trip even though the
    frontend already shows a quick estimate while the box is being plotted.
    """

    id: str
    area_sq_ft: float
    centroid_latitude: float
    centroid_longitude: float
    label: str | None
    created_at: str
