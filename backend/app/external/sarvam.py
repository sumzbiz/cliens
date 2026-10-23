"""Sarvam AI text-to-speech client with automatic key failover.

WHY THE FAILOVER IS SHAPED THIS WAY
The brief is two keys from two accounts, switching with no delay the user can
notice. The switch therefore triggers on the *first* response that says the key is
spent — not on a timeout, and not after a retry budget. Waiting for either would
put exactly the pause into the narration that the requirement rules out.

Which responses count is deliberately narrow. Only 402, 403 and 429 mean "this key
is done"; every other 4xx is a fault in our own request, and retrying that on the
second key would burn a second quota to produce the same error twice.

Once switched, the active key stays switched for the process lifetime. Ping-ponging
back to a rate-limited key mid-session would rediscover the limit on some later
request — probably mid-sentence — which is worse than simply staying on the key
that works.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
from dataclasses import dataclass

import httpx

from app.core import constants
from app.core.exceptions import ExternalServiceError, ExternalServiceTimeoutError
from app.core.logging import get_logger
from app.external.http import get_client

logger = get_logger(__name__)


class VoiceUnavailableError(ExternalServiceError):
    """No configured key could synthesise this audio.

    Distinct from a generic upstream failure because the interface treats it as a
    reason to fall back to text silently, not as an error worth interrupting the
    user over. Voice is an enhancement; losing it must never block a form.
    """

    code = "VOICE_UNAVAILABLE"
    http_status = 503


@dataclass(slots=True)
class _KeyRing:
    """The configured keys and which one is currently in use.

    Mutable and process-wide on purpose: the point of the switch is that it
    persists across requests, so a single exhausted key is discovered once rather
    than on every narration.
    """

    keys: tuple[str, ...]
    active_index: int = 0

    @property
    def active(self) -> str | None:
        """The key to try first, or None when none are configured."""
        if self.active_index >= len(self.keys):
            return None
        return self.keys[self.active_index]

    def order_from_active(self) -> list[tuple[int, str]]:
        """Keys to try, active first, then the remaining ones as fallbacks."""
        return [(index, self.keys[index]) for index in range(self.active_index, len(self.keys))]


class SarvamTtsClient:
    """Synthesises speech, transparently failing over between keys."""

    def __init__(self, keys: tuple[str, ...], *, speaker: str, language: str) -> None:
        """Bind the client to its keys and voice settings."""
        self._ring = _KeyRing(keys=keys)
        self._speaker = speaker
        self._language = language

    @property
    def configured(self) -> bool:
        """Whether any key is available."""
        return bool(self._ring.keys)

    async def synthesise(self, text: str) -> bytes:
        """Return WAV audio for one chunk of text.

        Raises:
            VoiceUnavailableError: If every configured key is exhausted or the
                service cannot be reached.
        """
        if not self.configured:
            raise VoiceUnavailableError("No Sarvam API key is configured.", service="sarvam")

        last_status: int | None = None

        for index, key in self._ring.order_from_active():
            try:
                audio = await self._request(key, text)
            except _KeyExhausted as exhausted:
                last_status = exhausted.status
                # Promote the next key for every future request, not just this
                # one. Rediscovering the same exhausted key on the next sentence
                # is what would produce an audible stall.
                self._ring.active_index = index + 1
                logger.warning(
                    "sarvam_key_exhausted",
                    key_position=index,
                    status_code=exhausted.status,
                    remaining_keys=len(self._ring.keys) - (index + 1),
                )
                continue

            if index != self._ring.active_index:
                self._ring.active_index = index
            return audio

        logger.error("sarvam_all_keys_exhausted", keys=len(self._ring.keys))
        raise VoiceUnavailableError(
            "Voice narration is temporarily unavailable.",
            service="sarvam",
            details={"last_status": last_status},
        )

    async def _request(self, key: str, text: str) -> bytes:
        """One synthesis call with one key.

        Raises:
            _KeyExhausted: If this key is rate limited or out of quota.
            VoiceUnavailableError: For any other failure.
        """
        client = get_client()
        try:
            response = await client.post(
                constants.SARVAM_TTS_ENDPOINT,
                json={
                    "text": text,
                    "target_language_code": self._language,
                    "model": constants.SARVAM_TTS_MODEL,
                    "speaker": self._speaker,
                },
                headers={"api-subscription-key": key},
                timeout=constants.EXTERNAL_REQUEST_TIMEOUT_SECONDS,
            )
        except httpx.TimeoutException as error:
            raise ExternalServiceTimeoutError(
                "The voice service did not respond in time.", service="sarvam"
            ) from error
        except httpx.HTTPError as error:
            raise VoiceUnavailableError(
                "The voice service could not be reached.",
                service="sarvam",
                details={"cause": str(error)},
            ) from error

        if response.status_code in constants.SARVAM_KEY_EXHAUSTED_STATUSES:
            raise _KeyExhausted(response.status_code)

        if response.status_code != httpx.codes.OK:
            # A 4xx that is not an exhausted key is our bug — a bad speaker name,
            # text in the wrong script, text over the length limit. Logging the
            # body is what makes that diagnosable; it contains no key material.
            logger.error(
                "sarvam_request_rejected",
                status_code=response.status_code,
                body=response.text[:300],
            )
            raise VoiceUnavailableError(
                "The voice service rejected the request.",
                service="sarvam",
                details={"status_code": response.status_code},
            )

        return _decode_audio(response)


class _KeyExhausted(Exception):
    """Internal signal that one key is spent and the next should be tried."""

    def __init__(self, status: int) -> None:
        super().__init__(f"key exhausted with status {status}")
        self.status = status


def _decode_audio(response: httpx.Response) -> bytes:
    """Pull WAV bytes out of a Sarvam response.

    Raises:
        VoiceUnavailableError: If the body is not the documented shape.
    """
    try:
        payload = response.json()
        encoded = payload["audios"][0]
    except (ValueError, KeyError, IndexError, TypeError) as error:
        raise VoiceUnavailableError(
            "The voice service returned an unexpected response.", service="sarvam"
        ) from error

    try:
        return base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as error:
        raise VoiceUnavailableError(
            "The voice service returned audio that could not be decoded.",
            service="sarvam",
        ) from error


async def synthesise_all(client: SarvamTtsClient, chunks: list[str]) -> list[bytes]:
    """Synthesise several chunks concurrently, preserving their order.

    Concurrent because a narration of ten options is several chunks and doing them
    in sequence would make the user wait for the sum of every round trip before
    hearing the first word. `gather` keeps the results in argument order, which is
    what lets the client play them back as one continuous reading.
    """
    return list(await asyncio.gather(*(client.synthesise(chunk) for chunk in chunks)))
