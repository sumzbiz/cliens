"""Integration tests for the basemap capability and tile endpoints.

Every Mapbox request is intercepted by respx; the app itself is reached in-process.
"""

from __future__ import annotations

import httpx
import pytest
import respx
from fastapi import FastAPI
from httpx import AsyncClient

from app.core import constants
from app.core.config import Settings, get_settings

pytestmark = pytest.mark.integration

MAPBOX_PREFIX = "https://api.mapbox.com/"
#: Not a credential: every Mapbox request in this module is intercepted by respx.
MAPBOX_TEST_KEY = "pk.test"


def use_settings(app: FastAPI, settings: Settings, mapbox_token: str | None) -> None:
    """Serve requests with the given Mapbox token, whatever the developer's .env holds."""
    configured = settings.model_copy(update={"mapbox_access_token": mapbox_token})
    app.dependency_overrides[get_settings] = lambda: configured


class TestCapabilities:
    """The zoom ceiling must follow working imagery, not merely configured keys."""

    async def test_without_a_token_the_map_stops_at_esri_depth(
        self, app: FastAPI, settings: Settings, client: AsyncClient
    ) -> None:
        use_settings(app, settings, None)

        body = (await client.get("/api/basemap")).json()

        assert body["max_zoom"] == constants.MAX_TILE_ZOOM_ESRI
        assert body["deep_imagery_available"] is False
        assert "Mapbox" not in body["attribution"]

    @respx.mock
    async def test_a_working_token_unlocks_deep_zoom(
        self, app: FastAPI, settings: Settings, client: AsyncClient
    ) -> None:
        use_settings(app, settings, MAPBOX_TEST_KEY)
        respx.get(url__startswith=MAPBOX_PREFIX).mock(return_value=httpx.Response(200))

        body = (await client.get("/api/basemap")).json()

        assert body["max_zoom"] == constants.MAX_TILE_ZOOM_MAPBOX
        assert body["deep_imagery_available"] is True
        assert "Mapbox" in body["attribution"]

    @pytest.mark.parametrize("status", [403, 429])
    @respx.mock
    async def test_a_rejected_token_falls_back_to_esri_depth(
        self, app: FastAPI, settings: Settings, client: AsyncClient, status: int
    ) -> None:
        """Advertising zoom 22 here put "Map data not yet available" tiles on screen."""
        use_settings(app, settings, MAPBOX_TEST_KEY)
        respx.get(url__startswith=MAPBOX_PREFIX).mock(return_value=httpx.Response(status))

        body = (await client.get("/api/basemap")).json()

        assert body["max_zoom"] == constants.MAX_TILE_ZOOM_ESRI
        assert body["deep_imagery_available"] is False
        assert "Mapbox" not in body["attribution"]

    @respx.mock
    async def test_tiles_deeper_than_working_imagery_are_refused(
        self, app: FastAPI, settings: Settings, client: AsyncClient
    ) -> None:
        use_settings(app, settings, MAPBOX_TEST_KEY)
        respx.get(url__startswith=MAPBOX_PREFIX).mock(return_value=httpx.Response(403))

        response = await client.get(f"/api/tiles/{constants.MAX_TILE_ZOOM_ESRI + 1}/0/0")

        assert response.status_code == 422
        details = response.json()["error"]["details"]
        assert details["max_zoom"] == constants.MAX_TILE_ZOOM_ESRI
        assert details["deep_imagery_available"] is False
