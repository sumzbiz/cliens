"""Map tile and place-search endpoints.

The tile endpoint exists because the globe renderer paints one image layer and the
imagery and its place names are published as two. See ``external/basemap.py`` for
why that flattening cannot happen in the browser.
"""

from __future__ import annotations

from collections import OrderedDict
from typing import Annotated, Any

from fastapi import APIRouter, Path, Query, Response, status

from app.core import constants
from app.core.exceptions import ValidationError
from app.external import basemap
from app.routes.dependencies import SettingsDep
from app.schemas.basemap import BasemapCapabilities, GeocodeMatch, GeocodeResponse
from app.schemas.common import ErrorResponse

router = APIRouter(tags=["basemap"])

BASEMAP_ERRORS: dict[int | str, dict[str, Any]] = {
    status.HTTP_502_BAD_GATEWAY: {
        "model": ErrorResponse,
        "description": "The upstream map or geocoding service failed.",
    },
    status.HTTP_504_GATEWAY_TIMEOUT: {
        "model": ErrorResponse,
        "description": "The upstream map or geocoding service did not respond in time.",
    },
}

#: Composited tiles, most-recently-used last.
#:
#: A plain dict rather than a cache library because the eviction rule is one line
#: and the alternative is a dependency for it. Bounded so a user panning across the
#: world cannot grow the process without limit.
_TILE_CACHE: OrderedDict[tuple[int, int, int], bytes] = OrderedDict()


@router.get(
    "/tiles/{z}/{x}/{y}",
    summary="One satellite map tile with place names composited onto it",
    responses=BASEMAP_ERRORS,
    response_class=Response,
)
async def get_tile(
    z: Annotated[int, Path(ge=0, le=constants.MAX_TILE_ZOOM)],
    x: Annotated[int, Path(ge=0)],
    y: Annotated[int, Path(ge=0)],
    settings: SettingsDep,
) -> Response:
    """Serve one composited map tile.

    The path type bounds ``z`` to the deepest level any provider reaches; the
    actual limit depends on which providers are configured, so it is checked here.
    Serving beyond it would return blank tiles that look like missing ground.
    """
    if z > _max_zoom(settings.mapbox_configured):
        raise ValidationError(
            f"Zoom {z} is deeper than the configured imagery provides.",
            details={
                "max_zoom": _max_zoom(settings.mapbox_configured),
                "mapbox_configured": settings.mapbox_configured,
            },
        )

    key = (z, x, y)
    cached = _TILE_CACHE.get(key)
    if cached is not None:
        _TILE_CACHE.move_to_end(key)
        return _tile_response(cached)

    payload = await basemap.fetch_composited_tile(
        x=x, y=y, z=z, mapbox_token=settings.mapbox_access_token
    )

    _TILE_CACHE[key] = payload
    while len(_TILE_CACHE) > constants.TILE_CACHE_ENTRIES:
        _TILE_CACHE.popitem(last=False)

    return _tile_response(payload)


def _max_zoom(mapbox_configured: bool) -> int:
    """The deepest zoom the configured providers actually publish."""
    return constants.MAX_TILE_ZOOM_MAPBOX if mapbox_configured else constants.MAX_TILE_ZOOM_ESRI


@router.get(
    "/basemap",
    response_model=BasemapCapabilities,
    summary="What the map can actually do with the imagery configured",
)
async def get_basemap_capabilities(settings: SettingsDep) -> BasemapCapabilities:
    """Report the real zoom ceiling and the attribution that must be shown.

    The client cannot hardcode either. Both change with which providers are
    configured, and a client that assumed the deeper limit would let the user zoom
    into blank tiles while crediting the wrong source.
    """
    mapbox = settings.mapbox_configured
    return BasemapCapabilities(
        max_zoom=_max_zoom(mapbox),
        deep_imagery_available=mapbox,
        attribution=(
            "Imagery © Mapbox, © Maxar. Labels © Esri"
            if mapbox
            else "Imagery © Esri, Maxar, Earthstar Geographics"
        ),
    )


def _tile_response(payload: bytes) -> Response:
    """Wrap tile bytes with caching headers.

    The browser cache is what actually keeps this fast: without it every pan
    re-requests tiles the user just looked at, through this process and on to Esri.
    """
    return Response(
        content=payload,
        media_type="image/jpeg",
        headers={"Cache-Control": f"public, max-age={constants.TILE_CACHE_SECONDS}"},
    )


@router.get(
    "/geocode",
    response_model=GeocodeResponse,
    summary="Find a place, address or postcode",
    responses=BASEMAP_ERRORS,
)
async def search_places(
    q: Annotated[str, Query(min_length=2, max_length=200)],
) -> GeocodeResponse:
    """Look up somewhere by name, address or postcode.

    Returns matches anywhere on Earth, deliberately. Whether a place has measured
    climate is a separate question, answered when an area is actually scored — a
    search that silently hid everywhere unscoreable would leave the user unable to
    navigate their own map.
    """
    results = await basemap.geocode(q, limit=constants.GEOCODER_RESULT_LIMIT)
    return GeocodeResponse(
        matches=tuple(
            GeocodeMatch(
                label=result.label,
                latitude=result.latitude,
                longitude=result.longitude,
                south=None if result.bounds is None else result.bounds[0],
                north=None if result.bounds is None else result.bounds[1],
                west=None if result.bounds is None else result.bounds[2],
                east=None if result.bounds is None else result.bounds[3],
            )
            for result in results
        )
    )
