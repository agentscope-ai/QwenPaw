# -*- coding: utf-8 -*-
"""An LM Studio provider implementation.

LM Studio exposes an OpenAI-compatible local server (default
http://localhost:1234/v1). This provider auto-discovers loaded models
on each get_info() call, similar to OllamaProvider."""

from __future__ import annotations

import logging

from copaw.providers.openai_provider import OpenAIProvider
from copaw.providers.provider import ProviderInfo

logger = logging.getLogger(__name__)


class LMStudioProvider(OpenAIProvider):
    """Provider for LM Studio's OpenAI-compatible local server."""

    async def get_info(self, mock_secret: bool = True) -> ProviderInfo:
        try:
            models = await self.fetch_models(timeout=1)
            self.models = models
        except Exception as exc:
            logger.debug("LM Studio model discovery failed: %s", exc)
            models = self.models
        return ProviderInfo(
            id=self.id,
            name=self.name,
            base_url=self.base_url,
            api_key=self.api_key_prefix + "*" * 6
            if mock_secret and self.api_key
            else self.api_key,
            chat_model=self.chat_model,
            models=models,
            extra_models=self.extra_models,
            api_key_prefix=self.api_key_prefix,
            is_local=self.is_local,
            is_custom=self.is_custom,
            freeze_url=self.freeze_url,
            require_api_key=self.require_api_key,
        )
