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
        return await super().get_info(mock_secret=mock_secret)
