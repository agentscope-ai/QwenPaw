# -*- coding: utf-8 -*-
"""A Google Gemini provider implementation using AgentScope's native
GeminiChatModel."""

from __future__ import annotations

from typing import Any, List

from agentscope.model import ChatModelBase
from google import genai
from google.genai import errors as genai_errors
from google.genai import types as genai_types

from copaw.providers.provider import ModelInfo, Provider


class GeminiProvider(Provider):
    """Provider implementation for Google Gemini API."""

    def _client(self, timeout: float = 10) -> Any:
        return genai.Client(
            api_key=self.api_key,
            http_options=genai_types.HttpOptions(timeout=int(timeout * 1000)),
        )

    @staticmethod
    def _normalize_models_payload(payload: Any) -> List[ModelInfo]:
        models: List[ModelInfo] = []
        for row in payload or []:
            model_id = str(getattr(row, "name", "") or "").strip()

            if not model_id:
                continue

            # Gemini API returns model names like "models/gemini-2.5-flash"
            # Strip the "models/" prefix for cleaner IDs
            if model_id.startswith("models/"):
                model_id = model_id[len("models/") :]

            display_name = str(
                getattr(row, "display_name", "") or model_id,
            ).strip()

            if not display_name or display_name.startswith("models/"):
                display_name = model_id

            models.append(ModelInfo(id=model_id, name=display_name))

        deduped: List[ModelInfo] = []
        seen: set[str] = set()
        for model in models:
            if model.id in seen:
                continue
            seen.add(model.id)
            deduped.append(model)
        return deduped

    async def check_connection(self, timeout: float = 10) -> tuple[bool, str]:
        """Check if Google Gemini provider is reachable."""
        try:
            client = self._client(timeout=timeout)
            # Use the async list models endpoint to verify connectivity
            async for _ in await client.aio.models.list():
                break
            return True, ""
        except genai_errors.APIError:
            return (
                False,
                "Failed to connect to Google Gemini API. "
                "Check your API key.",
            )
        except Exception:
            return (
                False,
                "Unknown exception when connecting to Google Gemini API.",
            )

    async def fetch_models(self, timeout: float = 10) -> List[ModelInfo]:
        """Fetch available models from Gemini API."""
        try:
            client = self._client(timeout=timeout)
            payload = []
            async for model in await client.aio.models.list():
                payload.append(model)
            models = self._normalize_models_payload(payload)
            return models
        except genai_errors.APIError:
            return []
        except Exception:
            return []

    async def check_model_connection(
        self,
        model_id: str,
        timeout: float = 10,
    ) -> tuple[bool, str]:
        """Check if a specific Gemini model is reachable/usable."""
        target = (model_id or "").strip()
        if not target:
            return False, "Empty model ID"

        try:
            client = self._client(timeout=timeout)
            response = await client.aio.models.generate_content_stream(
                model=target,
                contents="ping",
            )
            async for _ in response:
                break
            return True, ""
        except genai_errors.APIError:
            return (
                False,
                f"Model '{model_id}' is not reachable or usable",
            )
        except Exception:
            return (
                False,
                f"Unknown exception when connecting to model '{model_id}'",
            )

    def get_chat_model_instance(self, model_id: str) -> ChatModelBase:
        from agentscope.model import GeminiChatModel

        return GeminiChatModel(
            model_name=model_id,
            stream=True,
            api_key=self.api_key,
            generate_kwargs=self.generate_kwargs,
        )
