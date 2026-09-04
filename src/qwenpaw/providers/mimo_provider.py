# -*- coding: utf-8 -*-
"""Xiaomi MiMo provider with chat-catalog filtering.

MiMo's ``/v1/models`` returns both chat models and non-chat speech
models (``mimo-v2.5-asr``, ``mimo-v2.5-tts``, ``mimo-v2.5-tts-voiceclone``,
``mimo-v2.5-tts-voicedesign``) under the same ``object: "model"`` type, so
dynamic discovery must filter out the non-chat entries before they surface
as chat candidates. We reuse OpenAIProvider's ``_is_non_chat_model`` (which
already flags ``asr``/``tts`` tokens), matching the filter-first approach
used by ``DashScopeProvider`` and ``ModelScopeProvider``.
"""

from __future__ import annotations

from typing import List

from pydantic import Field

from .capping_formatter import MIMO_MEDIA_BYTES
from .openai_provider import OpenAIProvider, _is_non_chat_model
from .provider import ModelInfo


class MiMoProvider(OpenAIProvider):
    """Exclude non-chat (ASR/TTS) models from MiMo discovery results."""

    max_inline_media_bytes: int = Field(default=MIMO_MEDIA_BYTES, ge=0)
    max_image_bytes: int | None = Field(default=MIMO_MEDIA_BYTES, ge=0)
    max_video_bytes: int | None = Field(default=MIMO_MEDIA_BYTES, ge=0)
    max_audio_bytes: int | None = Field(default=MIMO_MEDIA_BYTES, ge=0)

    async def fetch_models(self, timeout: float = 5) -> List[ModelInfo]:
        """Fetch only catalog entries compatible with chat completions."""
        models = await super().fetch_models(timeout)
        return [model for model in models if not _is_non_chat_model(model.id)]
