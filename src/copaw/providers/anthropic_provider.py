# -*- coding: utf-8 -*-
"""An Anthropic provider implementation."""

from __future__ import annotations

import json
from typing import Any, List

from agentscope.model import ChatModelBase
import anthropic

from copaw.providers.provider import ModelInfo, Provider


class AnthropicProvider(Provider):
    """Provider implementation for Anthropic API."""

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

    async def check_connection(self, timeout: float = 5) -> tuple[bool, str]:
        """Check if Anthropic provider is reachable."""
        try:
            client = self._client(timeout=timeout)
            await client.models.list()
            return True, ""
        except anthropic.APIError:
            return False, "Anthropic API error"
        except Exception:
            return (
                False,
                f"Unknown exception when connecting to `{self.base_url}`",
            )

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
    ) -> tuple[bool, str]:
        """Check if a specific model is reachable/usable."""
        target = (model_id or "").strip()
        if not target:
            return False, "Empty model ID"

        body = {
            "model": target,
            "max_tokens": 1,
            "messages": [{"role": "user", "content": "ping"}],
            "stream": True,
        }
        try:
            client = self._client(timeout=timeout)
            resp = await client.messages.create(**body)
            # consume the stream to ensure the model is actually responsive
            async for _ in resp:
                break
            return True, ""
        except anthropic.APIError:
            return False, f"Model '{model_id}' is not reachable or usable"
        except Exception:
            return (
                False,
                f"Unknown exception when connecting to model '{model_id}'",
            )

    def get_chat_model_instance(self, model_id: str) -> ChatModelBase:
        from agentscope.model import AnthropicChatModel

        dashscope_base_urls = [
            "https://dashscope.aliyuncs.com/apps/anthropic",
            "https://coding.dashscope.aliyuncs.com/apps/anthropic",
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

        return AnthropicChatModel(
            model_name=model_id,
            stream=True,
            api_key=self.api_key,
            client_kwargs=client_kwargs,
            generate_kwargs=self.generate_kwargs,
        )
