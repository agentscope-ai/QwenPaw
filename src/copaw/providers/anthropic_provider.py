# -*- coding: utf-8 -*-
"""An Anthropic provider implementation."""

from __future__ import annotations

from typing import Any, Dict, List

import anthropic

from copaw.providers.provider import ModelInfo, Provider


class AnthropicProvider(Provider):
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
            if isinstance(row, dict):
                model_id = str(
                    row.get("id") or row.get("name") or "",
                ).strip()
                model_name = (
                    str(
                        row.get("display_name") or row.get("name") or model_id,
                    ).strip()
                    or model_id
                )
            else:
                model_id = str(
                    getattr(row, "id", "") or getattr(row, "name", "") or "",
                ).strip()
                model_name = (
                    str(
                        getattr(row, "display_name", "")
                        or getattr(row, "name", "")
                        or model_id,
                    ).strip()
                    or model_id
                )

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
        """Fetch available models and cache them on this provider instance."""
        client = self._client(timeout=timeout)
        payload = await client.models.list()
        models = self._normalize_models_payload(payload)
        self.models = models
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

    async def update_config(self, config: Dict) -> None:
        """Update provider configuration with the given dictionary."""
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
