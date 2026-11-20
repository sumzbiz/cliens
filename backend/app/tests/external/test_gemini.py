"""Tests for the Gemini client. Every call is mocked with respx."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
import respx

from app.core import constants
from app.core.exceptions import ExternalServiceError, ExternalServiceUnconfiguredError
from app.external import gemini

pytestmark = pytest.mark.anyio

MODEL = "test-model"
URL = constants.GEMINI_GENERATE_URL.format(model=MODEL)
SCHEMA: dict[str, Any] = {"type": "OBJECT"}


def _reply(text: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={"candidates": [{"content": {"parts": [{"text": text}]}, "finishReason": "STOP"}]},
    )


async def _generate(api_key: str | None = "test-key") -> dict[str, Any]:
    return await gemini.generate_json(
        api_key=api_key, model=MODEL, prompt="explain", response_schema=SCHEMA
    )


class TestGenerateJson:
    """The client shapes the request and accepts only a JSON object back."""

    async def test_refuses_without_a_key(self) -> None:
        with pytest.raises(ExternalServiceUnconfiguredError):
            await _generate(api_key=None)

    @respx.mock
    async def test_returns_the_parsed_object(self) -> None:
        respx.post(URL).mock(return_value=_reply(json.dumps({"summary": "ok", "points": []})))

        assert await _generate() == {"summary": "ok", "points": []}

    @respx.mock
    async def test_sends_the_key_in_a_header_and_asks_for_json(self) -> None:
        route = respx.post(URL).mock(return_value=_reply("{}"))

        await _generate()

        request = route.calls.last.request
        assert request.headers["x-goog-api-key"] == "test-key"
        assert "test-key" not in str(request.url)
        config = json.loads(request.content)["generationConfig"]
        assert config["responseMimeType"] == "application/json"
        assert config["temperature"] == constants.GEMINI_TEMPERATURE
        assert config["responseSchema"] == SCHEMA

    @respx.mock
    async def test_a_reply_without_text_is_an_error(self) -> None:
        respx.post(URL).mock(
            return_value=httpx.Response(200, json={"candidates": [{"finishReason": "SAFETY"}]})
        )

        with pytest.raises(ExternalServiceError) as caught:
            await _generate()
        assert caught.value.details["finish_reason"] == "SAFETY"

    @respx.mock
    async def test_invalid_json_is_an_error(self) -> None:
        respx.post(URL).mock(return_value=_reply("not json"))

        with pytest.raises(ExternalServiceError):
            await _generate()

    @respx.mock
    async def test_a_json_array_is_an_error(self) -> None:
        respx.post(URL).mock(return_value=_reply("[1, 2]"))

        with pytest.raises(ExternalServiceError):
            await _generate()
