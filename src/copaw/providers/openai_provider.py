# -*- coding: utf-8 -*-
"""An OpenAI provider implementation."""

from __future__ import annotations

import json
import logging
import subprocess
from typing import Any, List

from agentscope.model import ChatModelBase
import httpx
from openai import APIError, AsyncOpenAI
from pydantic import Field

from copaw.providers.auth_helper_registry import refresh_provider_auth
from copaw.providers.openai_auth import (
    get_chatgpt_headers,
    is_oauth_authorized,
)
from copaw.providers.provider import ModelInfo, Provider

DASHSCOPE_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
CODING_DASHSCOPE_BASE_URL = "https://coding.dashscope.aliyuncs.com/v1"
CODEX_BACKEND_BASE_URL = "https://chatgpt.com/backend-api/codex"
DEFAULT_CODEX_CLIENT_VERSION = "0.115.0"

logger = logging.getLogger(__name__)


class OpenAIProvider(Provider):
    """Provider implementation for OpenAI API and compatible endpoints."""

    oauth_models: List[ModelInfo] = Field(
        default_factory=list,
        description=(
            "Models discovered from ChatGPT/Codex browser auth."
            " Only used when auth.mode == 'oauth_browser'."
        ),
    )

    def _client(self, timeout: float = 5) -> AsyncOpenAI:
        return AsyncOpenAI(
            base_url=self.base_url,
            api_key=self.api_key,
            timeout=timeout,
        )

    @staticmethod
    def _codex_client_version() -> str:
        try:
            output = subprocess.check_output(
                ["codex", "-V"],
                text=True,
                stderr=subprocess.DEVNULL,
            ).strip()
            parts = output.split()
            if len(parts) >= 2:
                version = parts[-1].split("-")[0]
                if version.count(".") == 2:
                    return version
        except Exception:
            pass
        return DEFAULT_CODEX_CLIENT_VERSION

    def _is_codex_oauth(self) -> bool:
        return self.auth.mode == "oauth_browser" and (
            self.auth_helper == "openai"
            or (self.id == "openai" and not self.auth_helper)
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

    @staticmethod
    def _normalize_codex_models_payload(payload: Any) -> List[ModelInfo]:
        rows = payload.get("models", []) if isinstance(payload, dict) else []
        models: List[ModelInfo] = []
        for row in rows:
            model_id = str(row.get("slug", "") or "").strip()
            if not model_id:
                continue
            model_name = (
                str(
                    row.get("display_name", "") or model_id,
                ).strip()
                or model_id
            )
            models.append(ModelInfo(id=model_id, name=model_name))
        return models

    async def _refresh_oauth(self) -> None:
        await refresh_provider_auth(self, lambda current: current.persist())

    async def check_connection(self, timeout: float = 5) -> tuple[bool, str]:
        # pylint: disable=too-many-return-statements
        """Check if OpenAI provider is reachable with current configuration."""
        if self._is_codex_oauth():
            if not is_oauth_authorized(self):
                return False, "ChatGPT login required"
            try:
                await self._refresh_oauth()
                async with httpx.AsyncClient(timeout=timeout) as client:
                    response = await client.get(
                        f"{CODEX_BACKEND_BASE_URL}/models",
                        headers=get_chatgpt_headers(self),
                        params={
                            "client_version": self._codex_client_version(),
                        },
                    )
                if response.status_code >= 400:
                    return False, response.text[:300]
                return True, ""
            except Exception as exc:
                return False, str(exc)
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
        if self._is_codex_oauth():
            if not is_oauth_authorized(self):
                logger.debug("fetch_models: not OAuth authorized")
                return []
            try:
                await self._refresh_oauth()
                async with httpx.AsyncClient(timeout=timeout) as client:
                    response = await client.get(
                        f"{CODEX_BACKEND_BASE_URL}/models",
                        headers=get_chatgpt_headers(self),
                        params={
                            "client_version": self._codex_client_version(),
                        },
                    )
                response.raise_for_status()
                models = self._normalize_codex_models_payload(response.json())
                self.oauth_models = models
                logger.info(
                    "fetch_models: fetched %d OAuth models for openai",
                    len(models),
                )
                return models
            except Exception as exc:
                logger.warning(
                    "fetch_models: failed to fetch OAuth models: %s",
                    exc,
                    exc_info=True,
                )
                return []
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
        # pylint: disable=too-many-return-statements
        """Check if a specific model is reachable/usable"""
        model_id = (model_id or "").strip()
        if not model_id:
            return False, "Empty model ID"

        if self._is_codex_oauth():
            if not is_oauth_authorized(self):
                return False, "ChatGPT login required"
            if not self.oauth_models:
                try:
                    await self.fetch_models(timeout=timeout)
                except Exception:
                    pass
            if self.oauth_models and not any(
                model.id == model_id for model in self.oauth_models
            ):
                return (
                    False,
                    "Model is not available for ChatGPT Sign In."
                    " Use Discover Models to refresh the available list.",
                )
            payload = {
                "model": model_id,
                "instructions": "You are a concise assistant.",
                "input": [
                    {
                        "type": "message",
                        "role": "user",
                        "content": [
                            {
                                "type": "input_text",
                                "text": "ping",
                            },
                        ],
                    },
                ],
                "stream": True,
                "store": False,
            }
            try:
                await self._refresh_oauth()
                async with httpx.AsyncClient(timeout=timeout) as client:
                    async with client.stream(
                        "POST",
                        f"{CODEX_BACKEND_BASE_URL}/responses",
                        headers={
                            **get_chatgpt_headers(self),
                            "Accept": "text/event-stream",
                            "Content-Type": "application/json",
                        },
                        json=payload,
                    ) as response:
                        response.raise_for_status()
                        async for line in response.aiter_lines():
                            if line:
                                return True, ""
                return True, ""
            except Exception as exc:
                return False, str(exc)

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

    def has_model(self, model_id: str) -> bool:
        if self._is_codex_oauth():
            return any(model.id == model_id for model in self.oauth_models)
        return super().has_model(model_id)

    def on_auth_reset(self) -> None:
        self.oauth_models = []

    async def get_info(self, mock_secret: bool = True):
        info = await super().get_info(mock_secret=mock_secret)
        if self._is_codex_oauth():
            info.models = list(self.oauth_models)
            info.extra_models = []
            info.support_model_discovery = True
        return info

    def get_chat_model_instance(self, model_id: str) -> ChatModelBase:
        if self._is_codex_oauth():
            if self.oauth_models and not self.has_model(model_id):
                raise ValueError(
                    "Model "
                    f"'{model_id}' is not available for ChatGPT Sign In."
                    " Use Discover Models to refresh the available list.",
                )
            from .codex_chat_model import CodexResponsesChatModel

            return CodexResponsesChatModel(
                model_name=model_id,
                stream=True,
                access_token=self.auth.access_token,
                account_id=self.auth.account_id,
                base_url=CODEX_BACKEND_BASE_URL,
                generate_kwargs=self.generate_kwargs,
                provider=self,
            )

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

        return OpenAIChatModelCompat(
            model_name=model_id,
            stream=True,
            api_key=self.api_key,
            stream_tool_parsing=False,
            client_kwargs=client_kwargs,
            generate_kwargs=self.generate_kwargs,
        )
