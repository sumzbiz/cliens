"""Integration tests for the health endpoints and the cross-cutting middleware.

These run against the real test database, so readiness genuinely exercises the
PostGIS connection rather than a mock.
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import Settings
from app.core.logging import REQUEST_ID_HEADER
from app.main import create_app

pytestmark = pytest.mark.integration


class TestLiveness:
    """Liveness must not depend on anything that can be down."""

    async def test_reports_ok(self, client: AsyncClient) -> None:
        response = await client.get("/api/health/live")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


class TestReadiness:
    """Readiness reflects whether the app can actually do useful work."""

    async def test_reports_every_dependency_available_once_seeded(
        self, client: AsyncClient, seeded_catalogue: None
    ) -> None:
        response = await client.get("/api/health/ready")
        assert response.status_code == 200

        body = response.json()
        assert body["ready"] is True

        by_name = {dependency["name"]: dependency for dependency in body["dependencies"]}
        assert by_name["database"]["ready"] is True
        assert by_name["postgis"]["ready"] is True
        assert by_name["material_catalogue"]["ready"] is True
        assert by_name["ml_models"]["ready"] is True
        # Model versions are reported so a score can be tied to its artifacts.
        assert "quality_model=" in by_name["ml_models"]["detail"]
        # The schema depends on PostGIS, so the version is reported for diagnosis.
        assert "PostGIS" in by_name["postgis"]["detail"]

    async def test_reports_not_ready_when_the_catalogue_is_unseeded(
        self, client: AsyncClient
    ) -> None:
        """A migrated-but-unseeded database cannot score, so it is not ready."""
        response = await client.get("/api/health/ready")

        assert response.status_code == 503
        body = response.json()
        assert body["ready"] is False

        by_name = {dependency["name"]: dependency for dependency in body["dependencies"]}
        assert by_name["database"]["ready"] is True
        assert by_name["material_catalogue"]["ready"] is False
        # The detail must say what to actually do about it.
        assert "db:seed" in by_name["material_catalogue"]["detail"]


class TestCorrelationId:
    """A single request must be traceable end to end."""

    async def test_generates_an_id_when_the_client_sends_none(self, client: AsyncClient) -> None:
        response = await client.get("/api/health/live")
        assert response.headers[REQUEST_ID_HEADER]

    async def test_echoes_a_client_supplied_id(self, client: AsyncClient) -> None:
        """Lets a trace span the frontend and the backend."""
        supplied = "trace-me-12345"
        response = await client.get("/api/health/live", headers={REQUEST_ID_HEADER: supplied})
        assert response.headers[REQUEST_ID_HEADER] == supplied

    async def test_ids_differ_between_requests(self, client: AsyncClient) -> None:
        first = await client.get("/api/health/live")
        second = await client.get("/api/health/live")
        assert first.headers[REQUEST_ID_HEADER] != second.headers[REQUEST_ID_HEADER]


class TestErrorEnvelope:
    """Every failure returns the same shape, so the client handles one format."""

    async def test_unknown_path_returns_the_standard_envelope(self, client: AsyncClient) -> None:
        response = await client.get("/api/no-such-endpoint")
        assert response.status_code == 404

        error = response.json()["error"]
        assert error["code"] == "NOT_FOUND"
        assert error["message"]
        assert error["request_id"]

    async def test_wrong_method_returns_the_standard_envelope(self, client: AsyncClient) -> None:
        response = await client.post("/api/health/live")
        assert response.status_code == 405
        assert response.json()["error"]["code"] == "METHOD_NOT_ALLOWED"


class TestRateLimiting:
    """Public endpoints are protected by a per-IP budget; health probes are not."""

    async def test_health_endpoints_are_exempt(self, client: AsyncClient) -> None:
        """An orchestrator polling liveness must never be throttled."""
        for _ in range(30):
            response = await client.get("/api/health/live")
            assert response.status_code == 200

    async def test_exceeding_the_budget_returns_429_with_retry_after(
        self, settings: Settings, database: object
    ) -> None:
        """Uses its own app instance so the tiny budget cannot affect other tests."""
        strict = settings.model_copy(
            update={"rate_limit_requests": 2, "rate_limit_window_seconds": 60}
        )
        app = create_app(strict)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as strict_client:
            # A non-exempt path is required; the docs path is exempt, so an
            # unrouted path is used — it still passes through the limiter.
            first = await strict_client.get("/api/anything")
            second = await strict_client.get("/api/anything")
            third = await strict_client.get("/api/anything")

        assert first.status_code == 404
        assert second.status_code == 404
        assert third.status_code == 429

        error = third.json()["error"]
        assert error["code"] == "RATE_LIMIT_EXCEEDED"
        assert int(third.headers["Retry-After"]) >= 1

    async def test_remaining_budget_is_reported_on_allowed_requests(
        self, client: AsyncClient
    ) -> None:
        response = await client.get("/api/anything")
        assert "X-RateLimit-Remaining" in response.headers


class TestOpenApiSpec:
    """The spec is the source of the frontend's generated types."""

    async def test_spec_is_served(self, client: AsyncClient) -> None:
        response = await client.get("/openapi.json")
        assert response.status_code == 200

        spec = response.json()
        assert spec["info"]["title"] == "Building Quality Score API"
        assert "/api/health/live" in spec["paths"]
