# -*- coding: utf-8 -*-
"""An Ollama provider implementation."""

import os
from typing import Any

from agentscope.model import ChatModelBase
from openai import AsyncOpenAI

from qwenpaw.providers.openai_provider import OpenAIProvider


class OllamaProvider(OpenAIProvider):
    """Provider implementation for Ollama local LLM hosting platform."""

    @staticmethod
    def _normalize_base_url(base_url: str) -> str:
        normalized_base_url = (base_url or "").rstrip("/")
        if normalized_base_url.endswith("/v1"):
            # For backwards compatibility, if the URL ends with /v1,
            # we strip it to get the Ollama server base URL.
            normalized_base_url = normalized_base_url[:-3].rstrip("/")
        return normalized_base_url

    def _openai_compatible_base_url(self) -> str:
        return (
            self._normalize_base_url(
                self.base_url,  # type: ignore [has-type]
            )
            + "/v1"
        )

    def model_post_init(self, __context: Any) -> None:
        if not self.base_url:  # type: ignore
            self.base_url = (
                os.environ.get("OLLAMA_HOST") or "http://127.0.0.1:11434"
            )
        self.base_url = self._normalize_base_url(self.base_url)

    def update_config(self, config: dict[str, Any]) -> None:
        super().update_config(config)
        self.base_url = self._normalize_base_url(self.base_url)

    def _client(self, timeout: float = 5) -> AsyncOpenAI:
        kwargs: dict = {
            "base_url": self._openai_compatible_base_url(),
            "api_key": self.api_key,
            "timeout": timeout,
        }
        headers = self._build_default_headers()
        if headers:
            kwargs["default_headers"] = headers
        return AsyncOpenAI(**kwargs)

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

    def get_chat_model_instance(self, model_id: str) -> ChatModelBase:
        from .openai_chat_model_compat import OpenAIChatModelCompat

        client_kwargs: dict = {"base_url": self._openai_compatible_base_url()}
        headers = self._build_default_headers()
        if headers:
            client_kwargs["default_headers"] = headers
        return OpenAIChatModelCompat(
            model_name=model_id,
            stream=True,
            api_key=self.api_key,
            stream_tool_parsing=False,
            client_kwargs=client_kwargs,
            generate_kwargs=self.get_effective_generate_kwargs(model_id),
        )
