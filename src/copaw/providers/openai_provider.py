# -*- coding: utf-8 -*-
"""An OpenAI provider implementation."""

from __future__ import annotations

from typing import Any, Dict, List

from openai import APIError, AsyncOpenAI

from copaw.providers.provider import ModelInfo, Provider


class OpenAIProvider(Provider):
    def _client(self, timeout: float = 5) -> AsyncOpenAI:
        return AsyncOpenAI(
            base_url=self.base_url,
            api_key=self.api_key,
            timeout=timeout,
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

    async def check_connection(self, timeout: float = 5) -> bool:
        """Check if OpenAI provider is reachable with current configuration."""
        client = self._client()
        try:
            await client.models.list(timeout=timeout)
            return True
        except APIError:
            return False

    async def fetch_models(self, timeout: float = 5) -> List[ModelInfo]:
        """Fetch available models and cache them on this provider instance."""
        try:
            client = self._client(timeout=timeout)
            payload = await client.models.list(timeout=timeout)
            models = self._normalize_models_payload(payload)
            self.models = models
            return models
        except APIError:
            return []

    async def check_model_connection(
        self,
        model_id: str,
        timeout: float = 5,
    ) -> bool:
        """Check if a specific model is reachable/usable"""
        try:
            client = self._client(timeout=timeout)
            await client.chat.completions.create(
                model=model_id,
                messages=[{"role": "user", "content": "ping"}],
                timeout=timeout,
                max_tokens=1,
            )
            return True
        except APIError:
            return False

    async def update_config(self, config: Dict) -> None:
        """Update provider configuration fields from dict."""
        if "name" in config and config["name"] is not None:
            self.name = str(config["name"])
        if "base_url" in config and config["base_url"] is not None:
            self.base_url = str(config["base_url"])
        if "api_key" in config and config["api_key"] is not None:
            self.api_key = str(config["api_key"])
        if "chat_model" in config and config["chat_model"] is not None:
            self.chat_model = str(config["chat_model"])
        if "api_key_prefix" in config and config["api_key_prefix"] is not None:
            self.api_key_prefix = str(config["api_key_prefix"])
        if (
            "base_url_env_var" in config
            and config["base_url_env_var"] is not None
        ):
            self.base_url_env_var = str(config["base_url_env_var"])

    async def add_model(
        self,
        model_info: ModelInfo,
        timeout: float = 10,
    ) -> None:
        """Add a model to the provider's model list."""
        raise NotImplementedError(
            "This provider does not support adding models.",
        )

    async def delete_model(self, model_id: str, timeout: float = 10) -> None:
        """Delete a model from the provider's model list."""
        raise NotImplementedError(
            "This provider does not support deleting models.",
        )


if __name__ == "__main__":
    import asyncio

    provider = OpenAIProvider(
        id="openai",
        name="OpenAI",
        base_url="http://101.37.165.227:8081/v1",
        api_key="sk-empty",
        chat_model="OpenAIChatModel",
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
