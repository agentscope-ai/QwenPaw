# -*- coding: utf-8 -*-
"""An OpenAI provider implementation."""

from __future__ import annotations

import json
from typing import Any, List

from agentscope.model import ChatModelBase
from openai import APIError, AsyncOpenAI

from copaw.providers.provider import ModelInfo, Provider
from copaw.token_usage import TokenRecordingModelWrapper

DASHSCOPE_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
CODING_DASHSCOPE_BASE_URL = "https://coding.dashscope.aliyuncs.com/v1"


class OpenAIProvider(Provider):
    """Provider implementation for OpenAI API and compatible endpoints."""

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

    async def check_connection(self, timeout: float = 5) -> tuple[bool, str]:
        """Check if OpenAI provider is reachable with current configuration."""
        if self.base_url == CODING_DASHSCOPE_BASE_URL:
            return True, ""
        client = self._client()
        try:
            await client.models.list(timeout=timeout)
            return True, ""
        except APIError:
            return False, f"API error when connecting to `{self.base_url}`"
        except Exception:
            return (
                False,
                f"Unknown exception when connecting to `{self.base_url}`",
            )

    async def fetch_models(self, timeout: float = 5) -> List[ModelInfo]:
        """Fetch available models."""
        try:
            client = self._client(timeout=timeout)
            payload = await client.models.list(timeout=timeout)
            models = self._normalize_models_payload(payload)
            return models
        except APIError:
            return []
        except Exception:
            return []

    async def check_model_connection(
        self,
        model_id: str,
        timeout: float = 5,
    ) -> tuple[bool, str]:
        """Check if a specific model is reachable/usable"""
        model_id = (model_id or "").strip()
        if not model_id:
            return False, "Empty model ID"

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
            return True, ""
        except APIError:
            return False, f"API error when connecting to model '{model_id}'"
        except Exception:
            return (
                False,
                f"Unknown exception when connecting to model '{model_id}'",
            )

    def get_chat_model_instance(self, model_id: str) -> ChatModelBase:
        from .openai_chat_model_compat import OpenAIChatModelCompat

        dashscope_base_urls = [
            DASHSCOPE_BASE_URL,
            CODING_DASHSCOPE_BASE_URL,
        ]

        client_kwargs = {"base_url": self.base_url}

        if self.base_url in dashscope_base_urls:
            client_kwargs["default_headers"] = {
                "x-dashscope-agentapp": json.dumps(
                    {
                        "agentType": "CoPaw",
                        "deployType": "UnKnown",
                        "moduleCode": "model",
                        "agentCode": "UnKnown",
                    },
                    ensure_ascii=False,
                ),
            }

        model_instance = OpenAIChatModelCompat(
            model_name=model_id,
            stream=True,
            api_key=self.api_key,
            stream_tool_parsing=False,
            client_kwargs=client_kwargs,
            generate_kwargs=self.generate_kwargs,
        )
        return TokenRecordingModelWrapper(self.id, model_instance)
