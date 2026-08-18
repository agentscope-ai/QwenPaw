# -*- coding: utf-8 -*-
"""LM Studio Provider implementation."""

from qwenpaw.providers.openai_provider import OpenAIProvider
from qwenpaw.providers.provider import ModelConnectionResult


class LMStudioProvider(OpenAIProvider):
    """Provider implementation for LM Studio local LLM hosting platform."""

    async def check_model_connection(
        self,
        model_id: str,
        timeout: float = 5,
    ) -> ModelConnectionResult:
        """Check if a specific model is reachable/usable"""
        models = await self.fetch_models(timeout=timeout)
        if any(model.id == model_id for model in models):
            return ModelConnectionResult(
                success=True,
                verification="provider_only",
            )
        return ModelConnectionResult(
            success=False,
            message=f"Model '{model_id}' not found",
            error_kind="model_not_found",
            verification="provider_only",
        )
