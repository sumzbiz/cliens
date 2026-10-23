"""Tests for the tile compositor and the geocoding client.

Every upstream call is mocked with respx — the suite never touches Esri or
Nominatim. The behaviour that matters here is what happens when one of two tile
layers fails, because that decides whether the user sees a labelled map, an
unlabelled one, or a hole.
"""

from __future__ import annotations

from io import BytesIO

import httpx
import pytest
import respx
from PIL import Image

from app.core.exceptions import ExternalServiceError
from app.external import basemap

pytestmark = pytest.mark.anyio


def _png(colour: tuple[int, int, int, int], size: int = 256) -> bytes:
    """A solid PNG, standing in for a tile."""
    buffer = BytesIO()
    Image.new("RGBA", (size, size), colour).save(buffer, format="PNG")
    return buffer.getvalue()


IMAGERY_TILE = _png((10, 60, 20, 255))


#: Half transparent, half opaque red — the opaque half stands for label ink.
def _label_tile() -> bytes:
    image = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
    for x in range(128):
        for y in range(256):
            image.putpixel((x, y), (255, 0, 0, 255))
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


LABEL_TILE = _label_tile()


class TestTileCompositing:
    """Imagery is required; labels are a bonus that must never break the tile."""

    @respx.mock
    async def test_labels_are_burned_onto_the_imagery(self) -> None:
        respx.get(url__startswith="https://clarity.maptiles.arcgis.com").mock(
            return_value=httpx.Response(200, content=IMAGERY_TILE)
        )
        respx.get(url__startswith="https://server.arcgisonline.com").mock(
            return_value=httpx.Response(200, content=LABEL_TILE)
        )

        payload = await basemap.fetch_composited_tile(x=1, y=2, z=3)
        image = Image.open(BytesIO(payload)).convert("RGB")

        # Left half carries the label ink, right half is untouched imagery. If the
        # overlay were skipped or pasted without its alpha mask, one of these fails.
        left = image.getpixel((10, 128))
        right = image.getpixel((200, 128))
        assert isinstance(left, tuple) and isinstance(right, tuple)
        assert left[0] > left[1], "label ink should dominate the left half"
        assert right[1] > right[0], "imagery should survive on the right half"

    @respx.mock
    async def test_a_missing_labels_layer_still_returns_imagery(self) -> None:
        """Esri has no label tiles at the deepest zooms; that is not an error."""
        respx.get(url__startswith="https://clarity.maptiles.arcgis.com").mock(
            return_value=httpx.Response(200, content=IMAGERY_TILE)
        )
        respx.get(url__startswith="https://server.arcgisonline.com").mock(
            return_value=httpx.Response(404)
        )

        payload = await basemap.fetch_composited_tile(x=1, y=2, z=3)
        assert Image.open(BytesIO(payload)).size == (256, 256)

    @respx.mock
    async def test_a_corrupt_labels_layer_still_returns_imagery(self) -> None:
        respx.get(url__startswith="https://clarity.maptiles.arcgis.com").mock(
            return_value=httpx.Response(200, content=IMAGERY_TILE)
        )
        respx.get(url__startswith="https://server.arcgisonline.com").mock(
            return_value=httpx.Response(200, content=b"this is not a png")
        )

        payload = await basemap.fetch_composited_tile(x=1, y=2, z=3)
        assert Image.open(BytesIO(payload)).size == (256, 256)

    @respx.mock
    async def test_falls_back_to_the_standard_layer_when_clarity_has_no_tile(
        self,
    ) -> None:
        """Clarity coverage is patchier; a gap there must not be a hole in the map."""
        respx.get(url__startswith="https://clarity.maptiles.arcgis.com").mock(
            return_value=httpx.Response(404)
        )
        respx.get(url__startswith="https://server.arcgisonline.com").mock(
            side_effect=[
                httpx.Response(200, content=LABEL_TILE),
                httpx.Response(200, content=IMAGERY_TILE),
            ]
        )

        payload = await basemap.fetch_composited_tile(x=1, y=2, z=3)
        assert Image.open(BytesIO(payload)).size == (256, 256)

    @respx.mock
    async def test_falls_back_when_clarity_times_out(self) -> None:
        """A slow provider is a reason to try the other one, not to fail."""
        respx.get(url__startswith="https://clarity.maptiles.arcgis.com").mock(
            side_effect=httpx.TimeoutException("too slow")
        )
        respx.get(url__startswith="https://server.arcgisonline.com").mock(
            side_effect=[
                httpx.Response(200, content=LABEL_TILE),
                httpx.Response(200, content=IMAGERY_TILE),
            ]
        )

        payload = await basemap.fetch_composited_tile(x=1, y=2, z=3)
        assert Image.open(BytesIO(payload)).size == (256, 256)

    @respx.mock
    async def test_errors_only_when_every_source_fails(self) -> None:
        """A silently empty tile would render as ocean and mislead the user."""
        respx.get(url__startswith="https://clarity.maptiles.arcgis.com").mock(
            return_value=httpx.Response(503)
        )
        respx.get(url__startswith="https://server.arcgisonline.com").mock(
            side_effect=[httpx.Response(200, content=LABEL_TILE), httpx.Response(503)]
        )

        with pytest.raises(ExternalServiceError):
            await basemap.fetch_composited_tile(x=1, y=2, z=3)


class TestGeocoding:
    """Matches must survive a partly malformed response."""

    @respx.mock
    async def test_parses_matches_with_and_without_bounds(self) -> None:
        respx.get(url__startswith="https://nominatim.openstreetmap.org").mock(
            return_value=httpx.Response(
                200,
                json=[
                    {
                        "lat": "11.0",
                        "lon": "77.0",
                        "display_name": "Coimbatore",
                        "boundingbox": ["10.9", "11.1", "76.9", "77.1"],
                    },
                    {"lat": "12.0", "lon": "78.0", "display_name": "Somewhere"},
                ],
            )
        )

        results = await basemap.geocode("coimbatore", limit=5)

        assert len(results) == 2
        assert results[0].bounds == (10.9, 11.1, 76.9, 77.1)
        assert results[1].bounds is None, "no box means no box, not an invented one"

    @respx.mock
    async def test_skips_unusable_rows_without_losing_good_ones(self) -> None:
        """One odd entry must not cost the user their other matches."""
        respx.get(url__startswith="https://nominatim.openstreetmap.org").mock(
            return_value=httpx.Response(
                200,
                json=[
                    {"lat": "not a number", "lon": "77.0", "display_name": "Broken"},
                    "a bare string",
                    {"lat": "11.0", "lon": "77.0", "display_name": "Good"},
                ],
            )
        )

        results = await basemap.geocode("anything", limit=5)

        assert [result.label for result in results] == ["Good"]

    @respx.mock
    async def test_an_upstream_failure_is_typed(self) -> None:
        respx.get(url__startswith="https://nominatim.openstreetmap.org").mock(
            return_value=httpx.Response(500)
        )

        with pytest.raises(ExternalServiceError):
            await basemap.geocode("anything", limit=5)

    @respx.mock
    async def test_a_non_list_body_is_rejected(self) -> None:
        """Guards against a future API change silently yielding zero matches."""
        respx.get(url__startswith="https://nominatim.openstreetmap.org").mock(
            return_value=httpx.Response(200, json={"error": "unexpected shape"})
        )

        with pytest.raises(ExternalServiceError):
            await basemap.geocode("anything", limit=5)
