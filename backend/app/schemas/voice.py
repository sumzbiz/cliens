"""Voice narration schemas."""

from __future__ import annotations

from typing import Annotated

from pydantic import Field

from app.schemas.common import SchemaBase


class NarrationRequest(SchemaBase):
    """Text to be read aloud.

    The client sends finished Tamil prose rather than a question id. That keeps the
    wording beside the English it mirrors in the frontend, where a reviewer can
    check the translation against what is on screen, instead of splitting one
    sentence across two repositories.
    """

    text: Annotated[str, Field(min_length=1, max_length=8000)]


class VoiceCapabilities(SchemaBase):
    """Whether voice narration can run, and how it is configured.

    The client asks before showing any Listen button. Rendering a control that
    cannot work is worse than not offering it, because the user discovers the gap
    only after pressing it.
    """

    available: bool
    speaker: str
    language: str
