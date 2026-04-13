# -*- coding: utf-8 -*-
"""An OpenAI provider implementation."""

from __future__ import annotations

import os
from typing import Any

from agentscope.model import ChatModelBase
from openai import AsyncOpenAI

from qwenpaw.providers.provider import ModelInfo
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
        return AsyncOpenAI(
            base_url=self._openai_compatible_base_url(),
            api_key=self.api_key,
            timeout=timeout,
        )

    async def add_model(
        self,
        model_info: ModelInfo,
        target: str = "models",
        timeout: float = 36000,
    ) -> tuple[bool, str]:
        raise NotImplementedError(
            "Please add models directly in Ollama or use "
            "`ollama pull <model>` CLI command.",
        )

    async def delete_model(
        self,
        model_id: str,
        timeout: float = 60,
    ) -> tuple[bool, str]:
        raise NotImplementedError(
            "Please delete models directly in Ollama or use "
            "`ollama rm <model>` CLI command.",
        )

    def get_chat_model_instance(self, model_id: str) -> ChatModelBase:
        from .openai_chat_model_compat import OpenAIChatModelCompat

        return OpenAIChatModelCompat(
            model_name=model_id,
            stream=True,
            api_key=self.api_key,
            stream_tool_parsing=False,
            client_kwargs={"base_url": self._openai_compatible_base_url()},
            generate_kwargs=self.get_effective_generate_kwargs(model_id),
        )
