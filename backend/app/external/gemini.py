"""Gemini API client.

A thin, typed wrapper over ``generateContent`` that asks for JSON matching a
schema. Transport, retries and timeouts come from ``external.http``; this module
only shapes the request and checks the reply. The API key travels in a header,
never in the URL, so it cannot appear in request logs.
"""

from __future__ import annotations

import json
from typing import Any

from app.core import constants
from app.core.exceptions import ExternalServiceError, ExternalServiceUnconfiguredError
from app.core.logging import get_logger
from app.external.http import request_json

logger = get_logger(__name__)

SERVICE = "gemini"


async def generate_json(
    *,
    api_key: str | None,
    model: str,
    prompt: str,
    response_schema: dict[str, Any],
) -> dict[str, Any]:
    """Generate a JSON object from a prompt, constrained to ``response_schema``.

    Raises:
        ExternalServiceUnconfiguredError: If no API key is configured.
        ExternalServiceTimeoutError: If Gemini does not answer in time.
        ExternalServiceError: If Gemini fails, or its reply is not the JSON object
            the schema asked for.
    """
    if not api_key:
        raise ExternalServiceUnconfiguredError(
            "Plain-language explanations are not configured on this server.", service=SERVICE
        )

    body = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": constants.GEMINI_TEMPERATURE,
            "maxOutputTokens": constants.GEMINI_MAX_OUTPUT_TOKENS,
            "responseMimeType": "application/json",
            "responseSchema": response_schema,
        },
    }
    payload = await request_json(
        service=SERVICE,
        method="POST",
        url=constants.GEMINI_GENERATE_URL.format(model=model),
        timeout_seconds=constants.GEMINI_TIMEOUT_SECONDS,
        json_body=body,
        headers={"x-goog-api-key": api_key},
    )
    return _parse(payload)


def _parse(payload: dict[str, Any]) -> dict[str, Any]:
    """Extract the JSON object from a generateContent reply.

    Raises:
        ExternalServiceError: If the reply has no candidate text, was cut off, or
            the text is not a JSON object.
    """
    try:
        candidate = payload["candidates"][0]
        text = candidate["content"]["parts"][0]["text"]
    except (KeyError, IndexError, TypeError) as error:
        raise ExternalServiceError(
            "Gemini returned no usable text.",
            service=SERVICE,
            details={"finish_reason": _finish_reason(payload)},
        ) from error

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as error:
        raise ExternalServiceError(
            "Gemini's reply was not valid JSON.",
            service=SERVICE,
            details={"finish_reason": _finish_reason(payload)},
        ) from error
    if not isinstance(parsed, dict):
        raise ExternalServiceError("Gemini's reply was not a JSON object.", service=SERVICE)

    logger.info("gemini_reply_parsed", finish_reason=_finish_reason(payload))
    return parsed


def _finish_reason(payload: dict[str, Any]) -> str | None:
    """The candidate's finish reason, when present, for diagnostics."""
    candidates = payload.get("candidates")
    if isinstance(candidates, list) and candidates and isinstance(candidates[0], dict):
        reason = candidates[0].get("finishReason")
        return reason if isinstance(reason, str) else None
    return None
