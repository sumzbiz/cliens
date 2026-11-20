"""Voice narration endpoints.

The browser never sees a Sarvam key. It posts text here and receives audio, so the
credential stays server-side and the failover between keys is invisible to it.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Response, status

from app.routes.dependencies import NarrationServiceDep, SettingsDep
from app.schemas.common import ErrorResponse
from app.schemas.voice import NarrationRequest, VoiceCapabilities

router = APIRouter(prefix="/voice", tags=["voice"])

VOICE_ERRORS: dict[int | str, dict[str, Any]] = {
    status.HTTP_503_SERVICE_UNAVAILABLE: {
        "model": ErrorResponse,
        "description": "No configured key could synthesise the audio.",
    },
}


@router.get(
    "/capabilities",
    response_model=VoiceCapabilities,
    summary="Whether Tamil narration is available",
)
async def get_capabilities(
    settings: SettingsDep, narration: NarrationServiceDep
) -> VoiceCapabilities:
    """Report whether narration can run, before the client offers it."""
    return VoiceCapabilities(
        available=narration.available,
        speaker=settings.sarvam_tts_speaker,
        language=settings.sarvam_tts_language,
    )


@router.post(
    "/narrate",
    summary="Read a question and its options aloud in Tamil",
    responses=VOICE_ERRORS,
    response_class=Response,
)
async def narrate(request: NarrationRequest, narration: NarrationServiceDep) -> Response:
    """Synthesise one narration and return it as a single WAV file.

    One file rather than a list of chunks: the browser gets a single audio source,
    so a long narration plays continuously instead of gapping between pieces.
    """
    audio, cached = await narration.narrate(request.text)
    return Response(
        content=audio,
        media_type="audio/wav",
        headers={
            # Narration for a given question never changes, so let the browser keep
            # it. A replay then costs nothing and starts instantly.
            "Cache-Control": "private, max-age=86400",
            "X-Voice-Cache": "hit" if cached else "miss",
        },
    )
