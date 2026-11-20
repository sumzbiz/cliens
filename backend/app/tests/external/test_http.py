"""Tests for the shared outbound HTTP policy.

Every external call in the application goes through ``request_json``, so its retry
and error-mapping behaviour is what determines whether an upstream problem becomes a
useful typed error or an opaque 500. All traffic is mocked with respx; the autouse
``block_network`` fixture guarantees nothing escapes to the real internet.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from app.core import constants
from app.core.exceptions import ExternalServiceError, ExternalServiceTimeoutError
from app.core.logging import REQUEST_ID_HEADER, request_context
from app.external.http import request_json

URL = "https://upstream.test/resource"


@pytest.fixture(autouse=True)
def _no_backoff_delay(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove retry backoff so retry tests do not actually sleep."""
    monkeypatch.setattr(constants, "EXTERNAL_RETRY_INITIAL_BACKOFF_SECONDS", 0.0)
    monkeypatch.setattr(constants, "EXTERNAL_RETRY_MAX_BACKOFF_SECONDS", 0.0)


class TestSuccess:
    """The straightforward path."""

    @respx.mock
    async def test_returns_the_decoded_object(self) -> None:
        respx.get(URL).mock(return_value=httpx.Response(200, json={"value": 42}))

        result = await request_json(service="test", method="GET", url=URL)

        assert result == {"value": 42}

    @respx.mock
    async def test_propagates_the_correlation_id_upstream(self) -> None:
        """Lets an upstream's logs be lined up with ours when diagnosing."""
        route = respx.get(URL).mock(return_value=httpx.Response(200, json={}))

        with request_context("trace-abc"):
            await request_json(service="test", method="GET", url=URL)

        assert route.calls.last.request.headers[REQUEST_ID_HEADER] == "trace-abc"

    @respx.mock
    async def test_sends_query_parameters(self) -> None:
        route = respx.get(URL).mock(return_value=httpx.Response(200, json={}))

        await request_json(service="test", method="GET", url=URL, params={"lon": 80.27})

        assert route.calls.last.request.url.params["lon"] == "80.27"


class TestRetryPolicy:
    """Only transient failures are retried; a 4xx is never repeated."""

    @respx.mock
    async def test_retries_a_retryable_status_then_succeeds(self) -> None:
        route = respx.get(URL).mock(
            side_effect=[
                httpx.Response(503),
                httpx.Response(200, json={"recovered": True}),
            ]
        )

        result = await request_json(service="test", method="GET", url=URL)

        assert result == {"recovered": True}
        assert route.call_count == 2

    @respx.mock
    async def test_gives_up_after_the_configured_attempts(self) -> None:
        route = respx.get(URL).mock(return_value=httpx.Response(503))

        with pytest.raises(ExternalServiceError) as caught:
            await request_json(service="test", method="GET", url=URL)

        assert route.call_count == constants.EXTERNAL_MAX_RETRY_ATTEMPTS
        assert caught.value.details["status_code"] == 503
        assert caught.value.service == "test"

    @respx.mock
    async def test_does_not_retry_a_client_error(self) -> None:
        """Repeating a rejected request just fails again, more slowly."""
        route = respx.get(URL).mock(return_value=httpx.Response(400, json={"bad": "request"}))

        with pytest.raises(ExternalServiceError):
            await request_json(service="test", method="GET", url=URL)

        assert route.call_count == 1

    @respx.mock
    async def test_retries_a_connection_error(self) -> None:
        route = respx.get(URL).mock(
            side_effect=[httpx.ConnectError("refused"), httpx.Response(200, json={"ok": 1})]
        )

        assert await request_json(service="test", method="GET", url=URL) == {"ok": 1}
        assert route.call_count == 2

    @respx.mock
    async def test_timeout_maps_to_a_timeout_error(self) -> None:
        respx.get(URL).mock(side_effect=httpx.ReadTimeout("too slow"))

        with pytest.raises(ExternalServiceTimeoutError) as caught:
            await request_json(service="test", method="GET", url=URL, timeout_seconds=1.0)

        assert caught.value.service == "test"
        assert caught.value.http_status == 504


class TestResponseValidation:
    """An upstream can return 200 with a body that is not what we asked for."""

    @respx.mock
    async def test_rejects_a_non_json_body(self) -> None:
        """IMD has been observed returning an HTML error page with status 200."""
        respx.get(URL).mock(
            return_value=httpx.Response(200, text="<html>error</html>"),
        )

        with pytest.raises(ExternalServiceError, match="not valid JSON"):
            await request_json(service="test", method="GET", url=URL)

    @respx.mock
    async def test_rejects_a_json_array_where_an_object_was_expected(self) -> None:
        respx.get(URL).mock(return_value=httpx.Response(200, json=[1, 2, 3]))

        with pytest.raises(ExternalServiceError, match="where a JSON object was expected"):
            await request_json(service="test", method="GET", url=URL)

    @respx.mock
    async def test_error_details_never_include_the_upstream_body(self) -> None:
        """Error details must not carry upstream payloads into our envelope."""
        respx.get(URL).mock(return_value=httpx.Response(403, json={"secret": "do-not-leak-this"}))

        with pytest.raises(ExternalServiceError) as caught:
            await request_json(service="test", method="GET", url=URL)

        assert "do-not-leak-this" not in str(caught.value.details)
