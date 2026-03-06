# -*- coding: utf-8 -*-
"""An Anthropic provider implementation."""

from __future__ import annotations

import os
from typing import Any, Dict, List

import anthropic

from copaw.providers.provider import ModelInfo, Provider


class AnthropicProvider(Provider):
    def model_post_init(self, __context: Any) -> None:
        if not self.api_key:  # type: ignore
            self.api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not self.base_url:  # type: ignore
            self.base_url = os.environ.get(
                "ANTHROPIC_BASE_URL",
                "https://api.anthropic.com",
            )

    def _client(self, timeout: float = 5) -> anthropic.AsyncAnthropic:
        return anthropic.AsyncAnthropic(
            api_key=self.api_key,
            base_url=self.base_url,
            timeout=timeout,
        )

    @staticmethod
    def _normalize_models_payload(payload: Any) -> List[ModelInfo]:
        if isinstance(payload, dict):
            rows = payload.get("data", [])
        else:
            rows = getattr(payload, "data", payload)

        models: List[ModelInfo] = []
        for row in rows or []:
            model_id = str(
                getattr(row, "id", "") or "",
            ).strip()
            model_name = str(
                getattr(row, "display_name", "") or model_id,
            ).strip()

            if not model_id:
                continue
            models.append(ModelInfo(id=model_id, name=model_name))

        deduped: List[ModelInfo] = []
        seen: set[str] = set()
        for model in models:
            if model.id in seen:
                continue
            seen.add(model.id)
            deduped.append(model)
        return deduped

    async def check_connection(self, timeout: float = 5) -> bool:
        """Check if Anthropic provider is reachable."""
        try:
            client = self._client(timeout=timeout)
            await client.models.list()
            return True
        except anthropic.APIError:
            return False

    async def fetch_models(self, timeout: float = 5) -> List[ModelInfo]:
        """Fetch available models."""
        client = self._client(timeout=timeout)
        payload = await client.models.list()
        models = self._normalize_models_payload(payload)
        return models

    async def check_model_connection(
        self,
        model_id: str,
        timeout: float = 5,
    ) -> bool:
        """Check if a specific model is reachable/usable."""
        target = (model_id or "").strip()
        if not target:
            return False

        body = {
            "model": target,
            "max_tokens": 1,
            "messages": [{"role": "user", "content": "ping"}],
        }
        try:
            client = self._client(timeout=timeout)
            await client.messages.create(**body)
            return True
        except anthropic.APIError:
            return False


if __name__ == "__main__":
    import asyncio

    provider = AnthropicProvider(
        id="anthropic",
        name="Anthropic",
        base_url="http://101.37.165.227:8081",
        api_key="EMPTY",
        chat_model="AnthropicChatModel",
    )

    async def main():
        print("Checking connection...")
        connected = await provider.check_connection()
        print("Connected:", connected)

        if connected:
            print("Fetching models...")
            models = await provider.fetch_models()
            print(f"Found {len(models)} models:")
            for model in models:
                await provider.check_model_connection(model.id)
                print(f"- {model.id}: {model.name}")

    asyncio.run(main())
