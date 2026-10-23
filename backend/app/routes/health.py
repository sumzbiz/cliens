"""Liveness and readiness endpoints, including database and model-registry status.

Liveness answers "is the process up"; readiness answers "can it do useful work".
Only readiness touches dependencies, so a monitoring system can distinguish a
crashed process from a healthy one whose database is unreachable.
"""

from __future__ import annotations

from fastapi import APIRouter, Response, status

from app.core.database import get_database
from app.ml.registry import get_registry, registry_is_loaded
from app.routes.dependencies import MaterialServiceDep
from app.schemas.health import DependencyStatus, LivenessResponse, ReadinessResponse

router = APIRouter(prefix="/health", tags=["health"])


@router.get(
    "/live",
    response_model=LivenessResponse,
    summary="Liveness probe",
)
async def liveness() -> LivenessResponse:
    """Report that the process is running.

    Deliberately checks nothing else: a liveness probe that fails on a dependency
    outage causes an orchestrator to restart a process that was never broken.
    """
    return LivenessResponse()


@router.get(
    "/ready",
    response_model=ReadinessResponse,
    summary="Readiness probe",
    responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"model": ReadinessResponse}},
)
async def readiness(response: Response, materials: MaterialServiceDep) -> ReadinessResponse:
    """Report whether every dependency needed to serve requests is available.

    Returns HTTP 503 when anything required is down, so callers can act on the
    status code alone.
    """
    database = get_database()

    database_ready = await database.check_connection()
    postgis_version = await database.postgis_version() if database_ready else None

    # A database that migrated but was never seeded cannot score anything, so
    # reporting "ready" would be misleading. See README "Setup instructions".
    catalogue_size = await materials.catalogue_size() if database_ready else 0

    # Scoring is impossible without artifacts, so this is a required dependency
    # even though the app still starts and serves other endpoints without them.
    models_loaded = registry_is_loaded()

    dependencies = (
        DependencyStatus(
            name="database",
            ready=database_ready,
            detail=None if database_ready else "cannot connect",
        ),
        DependencyStatus(
            name="postgis",
            ready=postgis_version is not None,
            detail=(
                f"PostGIS {postgis_version}"
                if postgis_version is not None
                else "extension not installed"
            ),
        ),
        DependencyStatus(
            name="material_catalogue",
            ready=catalogue_size > 0,
            detail=(
                f"{catalogue_size} materials"
                if catalogue_size > 0
                else "not seeded; run `npm run db:seed`"
            ),
        ),
        DependencyStatus(
            name="ml_models",
            ready=models_loaded,
            detail=(
                ", ".join(f"{name}={version}" for name, version in get_registry().versions.items())
                if models_loaded
                else "not trained; run `npm run train:models`"
            ),
        ),
    )

    ready = all(dependency.ready for dependency in dependencies)
    if not ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return ReadinessResponse(ready=ready, dependencies=dependencies)
