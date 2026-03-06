# -*- coding: utf-8 -*-
"""An OpenAI provider implementation."""

from __future__ import annotations

import os
from typing import Any, Dict, List

try:
    import ollama
except ImportError:
    ollama = None  # type: ignore

from copaw.providers.provider import ModelInfo, Provider


class OllamaProvider(Provider):
    """Provider implementation for Ollama local LLM hosting platform."""

    def model_post_init(self, __context: Any) -> None:
        if not self.base_url:  # type: ignore
            self.base_url = (
                os.environ.get("OLLAMA_HOST") or "http://localhost:11434"
            )

    def _client(self, timeout: float = 5):
        if ollama is None:
            raise ImportError(
                "The 'ollama' Python package is required. You may have "
                "installed Ollama via their CLI or desktop app, but you "
                "also need the Python SDK to manage models from CoPaw. "
                "Please install it with: pip install 'copaw[ollama]'",
            )
        return ollama.AsyncClient(host=self.base_url, timeout=timeout)

    @staticmethod
    def _normalize_models_payload(payload: Any) -> List[ModelInfo]:
        rows = payload.get("models", [])
        models: List[ModelInfo] = []
        for row in rows or []:
            model_id = str(
                getattr(row, "model", ""),
            ).strip()
            model_name = model_id
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
        """Check if Ollama provider is reachable with current configuration."""
        try:
            client = self._client(timeout=timeout)
            await client.list()
            return True
        except (ImportError, ConnectionError, OSError, RuntimeError):
            return False

    async def fetch_models(self, timeout: float = 5) -> List[ModelInfo]:
        """Fetch available models and cache them on this provider instance."""
        try:
            client = self._client(timeout=timeout)
            payload = await client.list()
            models = self._normalize_models_payload(payload)
            self.models = models
            return models
        except (ImportError, ConnectionError, OSError, RuntimeError):
            return []

    async def check_model_connection(
        self,
        model_id: str,
        timeout: float = 10,
    ) -> bool:
        """Check if a specific model is reachable/usable."""
        target = (model_id or "").strip()
        if not target:
            return False

        try:
            client = self._client(timeout=timeout)
            await client.chat(
                model=target,
                messages=[{"role": "user", "content": "ping"}],
                options={"num_predict": 1},
            )
            return True
        except (ImportError, ConnectionError, OSError, RuntimeError):
            return False

    async def add_model(
        self,
        model_info: ModelInfo,
        timeout: float = 7200,
    ) -> None:
        client = self._client(timeout=timeout)
        await client.pull(model=model_info.id)
        self.models = await self.fetch_models()

    async def delete_model(self, model_id: str, timeout: float = 60) -> None:
        client = self._client(timeout=timeout)
        await client.delete(model=model_id)
        self.models = await self.fetch_models()


if __name__ == "__main__":
    import asyncio

    provider = OllamaProvider(
        id="ollama",
        name="Ollama",
        base_url="http://localhost:11434",
        api_key="EMPTY",
        chat_model="OllamaChatModel",
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
