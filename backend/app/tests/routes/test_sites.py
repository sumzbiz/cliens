"""Integration tests for site persistence.

Runs against the real bundled database — nothing here is stubbed — so a broken
PostGIS extension or a schema drift fails the suite rather than only failing in
production. The area figure is the thing that matters: it must be computed by the
server, not merely accepted, it must be geodesically accurate rather than a flat
approximation, and it must follow the outline actually drawn rather than a box
around it.
"""

from __future__ import annotations

import math

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.models import Site

pytestmark = pytest.mark.integration


async def _site_count(session: AsyncSession) -> int:
    return int((await session.execute(select(func.count()).select_from(Site))).scalar_one())


def _square(south: float, north: float, west: float, east: float) -> list[list[float]]:
    """A closed rectangular ring in GeoJSON (lon, lat) order."""
    return [[west, south], [east, south], [east, north], [west, north], [west, south]]


def _rectangle_area_sq_m(south: float, north: float, west: float, east: float) -> float:
    """Local equirectangular reference, independent of the server's own maths."""
    mid_lat = math.radians((south + north) / 2)
    height_m = (north - south) * 111_320
    width_m = (east - west) * 111_320 * math.cos(mid_lat)
    return height_m * width_m


SQ_FT_PER_SQ_M = 10.7639104167


class TestSaveSite:
    """A drawn outline, saved and returned with its authoritative area."""

    async def test_saves_a_square_and_returns_its_area(self, client: AsyncClient) -> None:
        response = await client.post(
            "/api/sites",
            json={
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [_square(11.0, 11.001, 77.0, 77.001)],
                }
            },
        )
        assert response.status_code == 201

        body = response.json()
        assert body["id"]
        assert body["created_at"]

        # Checked against an independent reference calculation, not a hardcoded
        # figure — the server's geodesic area and this planar approximation should
        # agree to well within 1% at this size and this close to the equator, so a
        # wider drift would mean the wrong unit or the wrong axis got used.
        expected = _rectangle_area_sq_m(11.0, 11.001, 77.0, 77.001) * SQ_FT_PER_SQ_M
        assert body["area_sq_ft"] == pytest.approx(expected, rel=0.01)

    async def test_a_triangle_is_half_its_bounding_box(self, client: AsyncClient) -> None:
        """The whole reason polygons replaced rectangles.

        Boxing this plot would claim double its real size, and that inflated
        figure is what the user would be told their site measures.
        """
        square = (
            await client.post(
                "/api/sites",
                json={
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [_square(11.0, 11.001, 77.0, 77.001)],
                    }
                },
            )
        ).json()["area_sq_ft"]

        triangle = (
            await client.post(
                "/api/sites",
                json={
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [
                            [
                                [77.0, 11.0],
                                [77.001, 11.0],
                                [77.0, 11.001],
                                [77.0, 11.0],
                            ]
                        ],
                    }
                },
            )
        ).json()["area_sq_ft"]

        assert triangle == pytest.approx(square / 2, rel=0.01)

    async def test_centroid_comes_from_the_geometry(self, client: AsyncClient) -> None:
        """A triangle's centroid is not its bounding box's midpoint."""
        body = (
            await client.post(
                "/api/sites",
                json={
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [
                            [
                                [76.0, 10.0],
                                [76.0003, 10.0],
                                [76.0, 10.0003],
                                [76.0, 10.0],
                            ]
                        ],
                    }
                },
            )
        ).json()

        # Centroid of a right triangle is the mean of its vertices, which sits at
        # one third of the legs — not the halfway point a bounding box would give.
        assert body["centroid_longitude"] == pytest.approx(76.0001, abs=1e-6)
        assert body["centroid_latitude"] == pytest.approx(10.0001, abs=1e-6)

    async def test_accepts_a_five_sided_outline(self, client: AsyncClient) -> None:
        response = await client.post(
            "/api/sites",
            json={
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [
                        [
                            [77.0, 11.0],
                            [77.0008, 11.0],
                            [77.001, 11.0005],
                            [77.0004, 11.0009],
                            [77.0, 11.0005],
                            [77.0, 11.0],
                        ]
                    ],
                }
            },
        )
        assert response.status_code == 201
        assert response.json()["area_sq_ft"] > 0

    async def test_closes_an_unclosed_ring(self, client: AsyncClient) -> None:
        """Drawing libraries routinely omit the repeated closing vertex."""
        response = await client.post(
            "/api/sites",
            json={
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [
                        [[77.0, 11.0], [77.001, 11.0], [77.001, 11.001], [77.0, 11.001]]
                    ],
                }
            },
        )
        assert response.status_code == 201

    async def test_saves_an_optional_label(self, client: AsyncClient) -> None:
        body = (
            await client.post(
                "/api/sites",
                json={
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [_square(11.0, 11.001, 77.0, 77.001)],
                    },
                    "label": "Plot behind the school",
                },
            )
        ).json()

        assert body["label"] == "Plot behind the school"


class TestRejectsUnusableOutlines:
    """A drawing error must surface as a clear 422, not a raw database failure."""

    async def test_rejects_a_self_intersecting_outline(self, client: AsyncClient) -> None:
        """PostGIS would still return an area for a bowtie; it means nothing."""
        response = await client.post(
            "/api/sites",
            json={
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [
                        [
                            [77.0, 11.0],
                            [77.001, 11.001],
                            [77.001, 11.0],
                            [77.0, 11.001],
                            [77.0, 11.0],
                        ]
                    ],
                }
            },
        )

        assert response.status_code == 422
        assert response.json()["error"]["code"] == "INVALID_GEOMETRY"

    async def test_rejects_a_collinear_outline(self, client: AsyncClient) -> None:
        """Three points on a line enclose nothing, however valid the ring looks."""
        response = await client.post(
            "/api/sites",
            json={
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[77.0, 11.0], [77.001, 11.0], [77.002, 11.0], [77.0, 11.0]]],
                }
            },
        )

        assert response.status_code == 422
        assert response.json()["error"]["code"] == "INVALID_GEOMETRY"

    async def test_rejects_a_boundary_too_large_to_be_a_site(self, client: AsyncClient) -> None:
        response = await client.post(
            "/api/sites",
            json={
                "geometry": {"type": "Polygon", "coordinates": [_square(10.0, 15.0, 76.0, 81.0)]}
            },
        )

        assert response.status_code == 422
        body = response.json()
        assert body["error"]["code"] == "INVALID_GEOMETRY"
        # The message names the actual figure, not a generic rejection — the user
        # needs to know how far off they are, not just that they were wrong.
        assert body["error"]["details"]["area_sq_ft"] > body["error"]["details"]["max_area_sq_ft"]

    async def test_rejects_a_sliver_too_small_to_be_a_site(self, client: AsyncClient) -> None:
        response = await client.post(
            "/api/sites",
            json={
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [_square(11.0, 11.0 + 1e-7, 77.0, 77.0 + 1e-7)],
                }
            },
        )

        assert response.status_code == 422
        assert response.json()["error"]["code"] == "INVALID_GEOMETRY"

    async def test_an_oversized_boundary_is_never_written(
        self, client: AsyncClient, session: AsyncSession
    ) -> None:
        """The area check must run before the insert, not merely alongside it."""
        before = await _site_count(session)

        response = await client.post(
            "/api/sites",
            json={
                "geometry": {"type": "Polygon", "coordinates": [_square(10.0, 15.0, 76.0, 81.0)]}
            },
        )
        assert response.status_code == 422

        # `client` and `session` are different connections, so the row count is
        # only trustworthy once the rejecting request's own transaction has
        # concluded — which it has, since the response already came back.
        assert await _site_count(session) == before, "a rejected save must not leave a row behind"


class TestValidation:
    """Structural checks come from `PolygonGeometry` — no separate copy to drift."""

    async def test_rejects_too_few_vertices(self, client: AsyncClient) -> None:
        response = await client.post(
            "/api/sites",
            json={"geometry": {"type": "Polygon", "coordinates": [[[77.0, 11.0], [77.001, 11.0]]]}},
        )
        assert response.status_code == 422

    async def test_rejects_out_of_range_coordinates(self, client: AsyncClient) -> None:
        response = await client.post(
            "/api/sites",
            json={
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [_square(11.0, 200.0, 77.0, 77.001)],
                }
            },
        )
        assert response.status_code == 422
