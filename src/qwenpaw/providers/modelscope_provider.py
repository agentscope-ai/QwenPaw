# -*- coding: utf-8 -*-
"""ModelScope provider with chat-catalog filtering."""

from __future__ import annotations

from typing import List

from .openai_provider import OpenAIProvider
from .provider import ModelInfo


class ModelScopeProvider(OpenAIProvider):
    """Exclude catalog entries that clearly cannot use chat completions."""

    @staticmethod
    def _is_non_chat_model(model_id: str) -> bool:
        normalized = model_id.strip().lower()
        leaf = normalized.rsplit("/", maxsplit=1)[-1]
        non_chat_markers = (
            "embedding",
            "rerank",
            "speech",
            "asr",
            "tts",
            "text-to-speech",
            "audio-generation",
            "image-edit",
            "image-generation",
            "text-to-image",
            "qwen-image",
            "judger",
            "xiyansql",
        )
        return leaf.endswith("-pt") or any(
            marker in normalized for marker in non_chat_markers
        )

    async def fetch_models(self, timeout: float = 5) -> List[ModelInfo]:
        models = await super().fetch_models(timeout)
        return [
            model for model in models if not self._is_non_chat_model(model.id)
        ]
