# -*- coding: utf-8 -*-
"""LM Studio Provider implementation."""

from qwenpaw.providers.openai_provider import OpenAIProvider


class LMStudioProvider(OpenAIProvider):
    """Provider implementation for LM Studio local LLM hosting platform."""

    async def check_model_connection(
        self,
        model_id: str,
        timeout: float = 5,
    ) -> tuple[bool, str]:
        """Check if a specific model is reachable/usable"""
        models = await self.fetch_models(timeout=timeout)
        if any(model.id == model_id for model in models):
            return True, ""
        return False, f"Model '{model_id}' not found"
