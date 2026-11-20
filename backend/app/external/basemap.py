"""Map tile and geocoding clients.

Two thin, typed clients over public services that need no API key.

WHY THE TILES ARE COMPOSITED HERE RATHER THAN IN THE BROWSER
The globe renderer paints exactly one image layer, and satellite imagery with no
place names is close to unusable for finding a specific plot — you cannot tell one
field from another. Esri publishes the imagery and the labels as two separate tile
layers, so they have to be flattened into one image before the globe sees them.
The renderer asks for a tile by URL synchronously, which rules out fetching and
compositing two tiles in the browser at request time. Doing it here turns two
layers into one URL, which is all the renderer can consume.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from io import BytesIO

import httpx
from PIL import Image

from app.core import constants
from app.core.exceptions import ExternalServiceError, ExternalServiceTimeoutError
from app.core.logging import get_logger
from app.external.http import get_client

logger = get_logger(__name__)

#: Mapbox Satellite — the deepest source, used only when a token is configured.
#:
#: Reaches zoom 22 in populated areas against Esri's 19, which is roughly an
#: eightfold gain in linear detail and the difference between seeing that a
#: building exists and seeing its roof structure. `@2x` requests 512 px tiles, so
#: each one carries four times the pixels for the same coverage.
#:
#: Metered. The free tier is generous but this is the one source in the chain that
#: can cost money, which is why it is opt-in rather than the default.
MAPBOX_IMAGERY_URL = (
    "https://api.mapbox.com/v4/mapbox.satellite/{z}/{x}/{y}@2x.jpg90" "?access_token={token}"
)

#: Esri World Imagery — the keyless source, with complete global coverage.
#:
#: Esri's separate "Clarity" endpoint used to be tried first. It has since been
#: retired: every tile now answers with two chained 301 redirects into an archived
#: Wayback release, which added well over a second per tile and, measured over
#: Coimbatore at z18-19, served older and less detailed photography than this
#: layer. Standard World Imagery is now both the faster and the sharper source.
IMAGERY_URL = (
    "https://server.arcgisonline.com/ArcGIS/rest/services/"
    "World_Imagery/MapServer/tile/{z}/{y}/{x}"
)

#: Esri boundaries, roads and place names, as a transparent overlay.
LABELS_URL = (
    "https://server.arcgisonline.com/ArcGIS/rest/services/"
    "Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}"
)

#: OpenStreetMap's geocoder. Free and keyless; its usage policy requires an
#: identifying User-Agent, which is why this goes through the server rather than
#: straight from the browser.
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"


@dataclass(frozen=True, slots=True)
class GeocodeResult:
    """One place matched by the geocoder."""

    label: str
    latitude: float
    longitude: float
    #: Bounding box as (south, north, west, east), if the geocoder supplied one.
    bounds: tuple[float, float, float, float] | None


async def fetch_composited_tile(x: int, y: int, z: int, mapbox_token: str | None = None) -> bytes:
    """One map tile with place names burned into the satellite imagery.

    The labels layer is optional in practice: it has no tiles at some zoom levels
    and over some oceans, and a missing overlay is not a failure — it just means
    there is nothing to label there. Imagery, by contrast, is the tile; if that
    cannot be fetched the caller gets an error rather than a blank square, because
    a silently empty tile would look like ocean.

    When a Mapbox token is configured the deeper Mapbox tile is preferred and Esri
    is the fallback, so a gap in one provider is not by itself a failure — it only
    becomes one when no source produced a usable image.

    Raises:
        ExternalServiceError: If no imagery source returned a usable tile.
    """
    client = get_client()

    # Every source is requested at once, so a tile costs one upstream round trip
    # rather than one per source tried. Fetching the fallback speculatively is
    # free — Esri is keyless — and is what keeps a Mapbox gap from adding a second
    # round trip to that tile.
    requests = [
        _fetch(client, IMAGERY_URL.format(x=x, y=y, z=z)),
        _fetch(client, LABELS_URL.format(x=x, y=y, z=z)),
    ]
    if mapbox_token is not None:
        requests.append(
            _fetch(client, MAPBOX_IMAGERY_URL.format(x=x, y=y, z=z, token=mapbox_token))
        )
    esri_response, labels_response, *mapbox_response = await asyncio.gather(*requests)

    # Decoding, compositing and re-encoding are CPU-bound. Run inline they stall
    # the event loop, so every other tile the map is waiting on queues behind this
    # one; on a worker thread the next tiles' network I/O keeps flowing meanwhile.
    return await asyncio.to_thread(
        _composite,
        esri_response,
        labels_response,
        mapbox_response[0] if mapbox_response else None,
        x=x,
        y=y,
        z=z,
    )


def _composite(
    esri_response: httpx.Response | BaseException,
    labels_response: httpx.Response | BaseException,
    mapbox_response: httpx.Response | BaseException | None,
    *,
    x: int,
    y: int,
    z: int,
) -> bytes:
    """Flatten the best available imagery and the labels into one JPEG.

    Raises:
        ExternalServiceError: If no imagery source returned a usable tile.
    """
    labels = (
        labels_response
        if isinstance(labels_response, httpx.Response)
        and labels_response.status_code == httpx.codes.OK
        else None
    )

    # Deepest source first when it is available. Ordering the chain by detail
    # rather than by cost is deliberate: the whole point of configuring a token is
    # to get imagery the free sources cannot supply.
    base: Image.Image | None = None
    if mapbox_response is not None:
        base = _decode_imagery(mapbox_response)
        if base is None:
            logger.info("mapbox_tile_unavailable_falling_back", z=z, x=x, y=y)

    if base is None:
        # With nothing to burn in, Esri's own JPEG is already the finished tile.
        # Passing its bytes through skips a decode and a re-encode, and avoids the
        # generation loss a second JPEG pass would add.
        if (
            labels is None
            and isinstance(esri_response, httpx.Response)
            and esri_response.status_code == httpx.codes.OK
            and esri_response.headers.get("content-type", "").startswith("image/jpeg")
        ):
            return esri_response.content
        base = _decode_imagery(esri_response)

    if base is None:
        raise ExternalServiceError(
            "No map imagery is available for that tile.",
            service="esri_world_imagery",
            details={"z": z, "x": x, "y": y},
        )

    # Label tiles are always 256 px, so a 512 px Mapbox tile has to be matched to
    # them before compositing. Scaling the labels up rather than the imagery down
    # keeps the extra detail that the deeper source was configured for.
    labels_size = base.size

    # Labels are best-effort. Anything other than a usable PNG leaves the imagery
    # unlabelled rather than failing the tile.
    if labels is not None:
        try:
            overlay = Image.open(BytesIO(labels.content)).convert("RGBA")
            if overlay.size != labels_size:
                overlay = overlay.resize(labels_size, Image.Resampling.LANCZOS)
            # The overlay is its own alpha mask, so labels land on the imagery
            # while the transparent background leaves it untouched.
            base.paste(overlay, (0, 0), overlay)
        except OSError:
            logger.info("label_tile_unusable", z=z, x=x, y=y)

    buffer = BytesIO()
    # subsampling=0 is the setting that matters here, and it is why the label text
    # was mushy before. This tile is a photograph with hard-edged coloured glyphs
    # drawn on it; JPEG's default 4:2:0 chroma subsampling throws away three
    # quarters of the colour resolution, which is invisible on foliage and
    # destroys thin coloured type. Measured on a labelled tile, turning it off cut
    # the error on label pixels from 17.7 to 7.6 — better than WebP at any quality
    # tried, and smaller.
    #
    # optimize is deliberately left off: it adds a second entropy-coding pass to
    # every tile for a few percent of size, and on a map the user is actively
    # zooming, time-to-pixels matters more than those bytes.
    base.save(
        buffer,
        format="JPEG",
        quality=constants.TILE_IMAGE_QUALITY,
        subsampling=constants.TILE_CHROMA_SUBSAMPLING,
    )
    return buffer.getvalue()


async def _fetch(client: httpx.AsyncClient, url: str) -> httpx.Response | BaseException:
    """Fetch one tile, returning the failure rather than raising it.

    Mirrors what ``asyncio.gather(..., return_exceptions=True)`` produces, so the
    fallback path and the primary path can be decoded by the same function.
    """
    try:
        return await client.get(url, timeout=constants.EXTERNAL_REQUEST_TIMEOUT_SECONDS)
    except httpx.HTTPError as error:
        return error


def _decode_imagery(response: httpx.Response | BaseException) -> Image.Image | None:
    """Decode a tile response, or ``None`` if it did not carry usable imagery.

    Returning None rather than raising is what lets the caller try the fallback
    source. A tile that is merely absent from one provider is not an error — an
    error is only correct once every source has been tried, because a silently
    blank tile would render as ocean and mislead the user about what is there.
    """
    if isinstance(response, BaseException) or response.status_code != httpx.codes.OK:
        return None
    try:
        return Image.open(BytesIO(response.content)).convert("RGB")
    except OSError:
        return None


async def geocode(query: str, limit: int) -> tuple[GeocodeResult, ...]:
    """Look up a place, address or postcode.

    Raises:
        ExternalServiceTimeoutError: If the geocoder does not respond in time.
        ExternalServiceError: If the geocoder fails or returns an unusable body.
    """
    client = get_client()
    try:
        response = await client.get(
            NOMINATIM_URL,
            params={"q": query, "format": "jsonv2", "limit": limit, "addressdetails": 0},
            headers={"User-Agent": constants.GEOCODER_USER_AGENT},
            timeout=constants.EXTERNAL_REQUEST_TIMEOUT_SECONDS,
        )
    except httpx.TimeoutException as error:
        raise ExternalServiceTimeoutError(
            "The place search did not respond in time.",
            service="nominatim",
        ) from error
    except httpx.HTTPError as error:
        raise ExternalServiceError(
            "The place search could not be reached.",
            service="nominatim",
            details={"cause": str(error)},
        ) from error

    if response.status_code != httpx.codes.OK:
        raise ExternalServiceError(
            "The place search returned an error.",
            service="nominatim",
            details={"status_code": response.status_code},
        )

    try:
        payload = response.json()
    except ValueError as error:
        raise ExternalServiceError(
            "The place search returned something that is not JSON.",
            service="nominatim",
        ) from error

    if not isinstance(payload, list):
        raise ExternalServiceError(
            "The place search returned an unexpected shape.",
            service="nominatim",
        )

    return tuple(result for row in payload if (result := _to_result(row)) is not None)


def _to_result(row: object) -> GeocodeResult | None:
    """Map one geocoder row, or ``None`` if it is unusable.

    Skipping a malformed row is right here: a single odd entry in a list of matches
    should not lose the user the other, good matches.
    """
    if not isinstance(row, dict):
        return None
    try:
        latitude = float(row["lat"])
        longitude = float(row["lon"])
        label = str(row["display_name"])
    except (KeyError, TypeError, ValueError):
        return None

    bounds: tuple[float, float, float, float] | None = None
    raw_box = row.get("boundingbox")
    if isinstance(raw_box, list) and len(raw_box) == 4:
        try:
            # Nominatim orders it (south, north, west, east).
            south, north, west, east = (float(value) for value in raw_box)
            bounds = (south, north, west, east)
        except (TypeError, ValueError):
            bounds = None

    return GeocodeResult(label=label, latitude=latitude, longitude=longitude, bounds=bounds)
