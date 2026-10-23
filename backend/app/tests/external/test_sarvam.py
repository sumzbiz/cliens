"""Tests for Sarvam key failover and narration assembly.

Every upstream call is mocked — the suite never spends a real quota. The behaviour
under test is the requirement that matters: when one key is spent the user must not
notice, and when both are spent the app must degrade to text rather than break.
"""

from __future__ import annotations

import base64
import io
import wave

import httpx
import pytest
import respx

from app.core import constants
from app.external.sarvam import SarvamTtsClient, VoiceUnavailableError
from app.services import narration

pytestmark = pytest.mark.anyio

KEYS = ("key-primary", "key-secondary")


def _wav(seconds: float = 0.1) -> bytes:
    """A tiny valid mono WAV, so the concatenation path has real audio to join."""
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(8000)
        writer.writeframes(b"\x00\x00" * int(8000 * seconds))
    return buffer.getvalue()


def _ok() -> httpx.Response:
    return httpx.Response(200, json={"audios": [base64.b64encode(_wav()).decode()]})


def _client() -> SarvamTtsClient:
    return SarvamTtsClient(KEYS, speaker="kavitha", language="ta-IN")


class TestKeyFailover:
    """One exhausted key must be invisible to the user."""

    @respx.mock
    async def test_uses_the_primary_key_first(self) -> None:
        route = respx.post(constants.SARVAM_TTS_ENDPOINT).mock(return_value=_ok())

        await _client().synthesise("வணக்கம்")

        assert route.calls[0].request.headers["api-subscription-key"] == KEYS[0]

    @pytest.mark.parametrize("status", sorted(constants.SARVAM_KEY_EXHAUSTED_STATUSES))
    @respx.mock
    async def test_falls_over_to_the_secondary_key(self, status: int) -> None:
        """429, 402 and 403 all mean the key is spent, not that we asked wrongly."""
        route = respx.post(constants.SARVAM_TTS_ENDPOINT).mock(
            side_effect=[httpx.Response(status), _ok()]
        )

        audio = await _client().synthesise("வணக்கம்")

        assert audio, "the user should still get audio"
        assert route.call_count == 2
        assert route.calls[1].request.headers["api-subscription-key"] == KEYS[1]

    @respx.mock
    async def test_stays_on_the_secondary_key_afterwards(self) -> None:
        """The whole point of the switch is that it is not rediscovered.

        Going back to the exhausted key would hit the limit again on a later
        sentence — an audible stall in the middle of a narration.
        """
        route = respx.post(constants.SARVAM_TTS_ENDPOINT).mock(
            side_effect=[httpx.Response(429), _ok(), _ok(), _ok()]
        )
        client = _client()

        await client.synthesise("ஒன்று")
        await client.synthesise("இரண்டு")
        await client.synthesise("மூன்று")

        used = [call.request.headers["api-subscription-key"] for call in route.calls]
        assert used == [KEYS[0], KEYS[1], KEYS[1], KEYS[1]]

    @respx.mock
    async def test_a_bad_request_does_not_burn_the_second_key(self) -> None:
        """A 400 is our bug. Retrying it elsewhere spends a quota for nothing."""
        route = respx.post(constants.SARVAM_TTS_ENDPOINT).mock(
            return_value=httpx.Response(400, json={"error": {"message": "bad speaker"}})
        )

        with pytest.raises(VoiceUnavailableError):
            await _client().synthesise("வணக்கம்")

        assert route.call_count == 1

    @respx.mock
    async def test_both_keys_exhausted_degrades_rather_than_crashes(self) -> None:
        respx.post(constants.SARVAM_TTS_ENDPOINT).mock(
            side_effect=[httpx.Response(429), httpx.Response(429)]
        )

        with pytest.raises(VoiceUnavailableError) as error:
            await _client().synthesise("வணக்கம்")

        # The typed code is what lets the interface fall back to text silently.
        assert error.value.code == "VOICE_UNAVAILABLE"

    async def test_no_keys_configured_is_reported_not_crashed(self) -> None:
        client = SarvamTtsClient((), speaker="kavitha", language="ta-IN")

        assert client.configured is False
        with pytest.raises(VoiceUnavailableError):
            await client.synthesise("வணக்கம்")


class TestChunking:
    """Narration of many options exceeds the API's hard character limit."""

    def test_short_text_is_one_chunk(self) -> None:
        assert narration.split_for_synthesis("கான்கிரீட் தரம் எது?") == ["கான்கிரீட் தரம் எது?"]

    def test_every_chunk_is_within_the_api_limit(self) -> None:
        long_text = "இது ஒரு நீண்ட வாக்கியம். " * 400

        chunks = narration.split_for_synthesis(long_text)

        assert len(chunks) > 1
        assert all(len(chunk) <= constants.SARVAM_MAX_TEXT_CHARACTERS for chunk in chunks)

    def test_splits_on_sentence_ends(self) -> None:
        """A cut mid-sentence is audible: the voice drops as if it had finished."""
        long_text = "முதல் வாக்கியம். " * 300

        for chunk in narration.split_for_synthesis(long_text):
            assert chunk.endswith("."), chunk[-40:]

    def test_no_text_is_lost_when_splitting(self) -> None:
        long_text = "வாக்கியம் ஒன்று. வாக்கியம் இரண்டு. " * 200
        joined = " ".join(narration.split_for_synthesis(long_text))

        assert joined.replace(" ", "") == long_text.replace(" ", "")


class TestConcatenation:
    """Chunks are joined server-side so playback has no gap between them."""

    def test_joined_audio_is_the_sum_of_its_parts(self) -> None:
        parts = [_wav(0.1), _wav(0.2)]

        joined = narration.concatenate_wav(parts)

        with wave.open(io.BytesIO(joined), "rb") as reader:
            assert reader.getnframes() == pytest.approx(8000 * 0.3, rel=0.01)

    def test_a_single_part_is_returned_unchanged(self) -> None:
        part = _wav()
        assert narration.concatenate_wav([part]) is part
