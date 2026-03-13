# -*- coding: utf-8 -*-
"""An OpenRouter provider implementation."""

from __future__ import annotations

from typing import Any, List

from agentscope.model import ChatModelBase
from openai import APIError, AsyncOpenAI

from copaw.providers.provider import ModelInfo, Provider


class OpenRouterProvider(Provider):
    """OpenRouter provider with required HTTP-Referer and X-Title headers."""

    def _client(self, timeout: float = 30) -> AsyncOpenAI:
        return AsyncOpenAI(
            base_url=self.base_url,
            api_key=self.api_key,
            timeout=timeout,
            default_headers={
                "HTTP-Referer": "https://copaw.ai",
                "X-Title": "CoPaw",
            },
        )

    @staticmethod
    def _normalize_models_payload(payload: Any) -> List[ModelInfo]:
        models: List[ModelInfo] = []
        rows = getattr(payload, "data", [])
        for row in rows or []:
            model_id = str(getattr(row, "id", "") or "").strip()
            if not model_id:
                continue
            model_name = (
                str(getattr(row, "name", "") or model_id).strip() or model_id
            )
            models.append(ModelInfo(id=model_id, name=model_name))

        deduped: List[ModelInfo] = []
        seen: set[str] = set()
        for model in models:
            if model.id in seen:
                continue
            seen.add(model.id)
            deduped.append(model)
        return deduped

    async def check_connection(self, timeout: float = 30) -> bool:
        """Check if OpenRouter provider is reachable."""
        client = self._client()
        try:
            await client.models.list(timeout=timeout)
            return True
        except APIError:
            return False

    async def fetch_models(self, timeout: float = 30) -> List[ModelInfo]:
        """Fetch available models."""
        try:
            client = self._client(timeout=timeout)
            payload = await client.models.list(timeout=timeout)
            models = self._normalize_models_payload(payload)
            return models
        except APIError:
            return []

    async def check_model_connection(
        self,
        model_id: str,
        timeout: float = 30,
    ) -> bool:
        """Check if a specific model is reachable/usable"""
        try:
            client = self._client(timeout=timeout)
            res = await client.chat.completions.create(
                model=model_id,
                messages=[{"role": "user", "content": "ping"}],
                timeout=timeout,
                max_tokens=1,
                stream=True,
            )
            # consume the stream to ensure the model is actually responsive
            async for _ in res:
                break
            return True
        except APIError:
            return False

    def get_chat_model_instance(self, model_id: str) -> ChatModelBase:
        from .openai_chat_model_compat import OpenAIChatModelCompat

        return OpenAIChatModelCompat(
            model_name=model_id,
            stream=True,
            api_key=self.api_key,
            client_kwargs={
                "base_url": self.base_url,
                "default_headers": {
                    "HTTP-Referer": "https://copaw.ai",
                    "X-Title": "CoPaw",
                },
            },
        )
