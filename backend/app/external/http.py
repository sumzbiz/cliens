"""Shared httpx transport policy: timeouts, retry/backoff, correlation-ID propagation.

Every outbound HTTP call in the application goes through ``request_json`` here.
Centralising it means the timeout, the retry policy and the mapping from transport
failure to typed exception exist once, and no client can accidentally omit them.

Business code never imports httpx. It calls a client in this package, which calls
this module.
"""

from __future__ import annotations

from typing import Any

import httpx
from tenacity import (
    AsyncRetrying,
    RetryError,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.core import constants
from app.core.exceptions import ExternalServiceError, ExternalServiceTimeoutError
from app.core.logging import REQUEST_ID_HEADER, get_logger, get_request_id

logger = get_logger(__name__)


class _RetryableResponse(Exception):
    """Internal signal that a response should be retried.

    Raised so tenacity can drive the backoff, then unwrapped by the caller. Never
    escapes this module.
    """

    def __init__(self, status_code: int, body: str) -> None:
        super().__init__(f"retryable upstream status {status_code}")
        self.status_code = status_code
        self.body = body


# One client for the process. Building an httpx.AsyncClient constructs an SSL
# context, which loads the system CA bundle — measurably expensive, and pure waste
# if repeated per request. Sharing one also gives connection pooling and keep-alive
# across calls to the same upstream.
_client: httpx.AsyncClient | None = None


def get_client() -> httpx.AsyncClient:
    """Return the shared outbound HTTP client, creating it on first use."""
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(
            timeout=constants.EXTERNAL_REQUEST_TIMEOUT_SECONDS,
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
            follow_redirects=True,
        )
    return _client


async def close_client() -> None:
    """Close the shared client. Called at application shutdown."""
    global _client
    if _client is not None and not _client.is_closed:
        await _client.aclose()
    _client = None


def _outbound_headers(extra: dict[str, str] | None = None) -> dict[str, str]:
    """Build request headers, propagating this request's correlation ID.

    Passing the ID onward means an upstream's own logs can be lined up with ours
    when diagnosing a slow or failing call.
    """
    headers = {"Accept": "application/json"}
    request_id = get_request_id()
    if request_id is not None:
        headers[REQUEST_ID_HEADER] = request_id
    if extra:
        headers.update(extra)
    return headers


async def request_json(
    *,
    service: str,
    method: str,
    url: str,
    timeout_seconds: float = constants.EXTERNAL_REQUEST_TIMEOUT_SECONDS,
    params: dict[str, str | int | float] | None = None,
    json_body: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Perform an HTTP request and return the decoded JSON object.

    Retries only transient failures — connection errors, timeouts, and the status
    codes in ``RETRYABLE_HTTP_STATUS_CODES``. A 4xx is never retried, because
    repeating a rejected request just fails again more slowly.

    Args:
        service: Upstream identifier used in logs and errors, e.g. ``"imd"``.
        method: HTTP method.
        url: Absolute URL.
        timeout_seconds: Total budget for one attempt.
        params: Query string parameters.
        json_body: Request body, encoded as JSON.
        headers: Additional headers, merged over the defaults.

    Returns:
        The decoded JSON object.

    Raises:
        ExternalServiceTimeoutError: The upstream did not answer within the budget,
            on every attempt.
        ExternalServiceError: The upstream returned an error status, returned a
            body that was not a JSON object, or could not be reached.
    """
    attempts = 0

    try:
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(constants.EXTERNAL_MAX_RETRY_ATTEMPTS),
            wait=wait_exponential(
                multiplier=constants.EXTERNAL_RETRY_INITIAL_BACKOFF_SECONDS,
                max=constants.EXTERNAL_RETRY_MAX_BACKOFF_SECONDS,
            ),
            retry=retry_if_exception_type(
                (httpx.TimeoutException, httpx.TransportError, _RetryableResponse)
            ),
            reraise=False,
        ):
            with attempt:
                attempts += 1
                logger.info(
                    "external_request_started",
                    service=service,
                    method=method,
                    url=url,
                    attempt=attempts,
                )
                response = await get_client().request(
                    method,
                    url,
                    params=params,
                    json=json_body,
                    headers=_outbound_headers(headers),
                    timeout=timeout_seconds,
                )

                if response.status_code in constants.RETRYABLE_HTTP_STATUS_CODES:
                    raise _RetryableResponse(response.status_code, response.text[:500])

                return _decode(service=service, response=response)

    except RetryError as error:
        last = error.last_attempt.exception()
        logger.warning(
            "external_request_exhausted_retries",
            service=service,
            url=url,
            attempts=attempts,
            error_type=type(last).__name__,
        )
        if isinstance(last, httpx.TimeoutException):
            raise ExternalServiceTimeoutError(
                f"{service} did not respond within {timeout_seconds:g}s.",
                service=service,
                details={"attempts": attempts},
            ) from last
        if isinstance(last, _RetryableResponse):
            raise ExternalServiceError(
                f"{service} returned status {last.status_code} after {attempts} attempts.",
                service=service,
                details={"status_code": last.status_code, "attempts": attempts},
            ) from last
        raise ExternalServiceError(
            f"{service} could not be reached.",
            service=service,
            details={"attempts": attempts},
        ) from last

    # Unreachable: the loop either returns or raises RetryError. Present so the
    # function is total for the type checker.
    raise ExternalServiceError(  # pragma: no cover
        f"{service} produced no response.", service=service
    )


def _decode(*, service: str, response: httpx.Response) -> dict[str, Any]:
    """Turn a non-retryable response into a JSON object or a typed error.

    Raises:
        ExternalServiceError: On an error status, a non-JSON body, or a JSON body
            that is not an object.
    """
    if response.status_code >= httpx.codes.BAD_REQUEST:
        logger.warning(
            "external_request_rejected",
            service=service,
            status_code=response.status_code,
            # Truncated: an upstream error body can be an entire HTML page, and
            # may echo request content we should not copy into our logs wholesale.
            body_preview=response.text[:200],
        )
        raise ExternalServiceError(
            f"{service} rejected the request with status {response.status_code}.",
            service=service,
            details={"status_code": response.status_code},
        )

    try:
        payload = response.json()
    except ValueError as error:
        # IMD in particular has been observed returning an HTML error page with a
        # 200 status, which would otherwise surface as an opaque parsing failure.
        raise ExternalServiceError(
            f"{service} returned a body that was not valid JSON.",
            service=service,
            details={"content_type": response.headers.get("content-type", "unknown")},
        ) from error

    if not isinstance(payload, dict):
        raise ExternalServiceError(
            f"{service} returned {type(payload).__name__} where a JSON object was expected.",
            service=service,
        )

    logger.info("external_request_succeeded", service=service, status_code=response.status_code)
    return payload
