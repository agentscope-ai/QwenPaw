# -*- coding: utf-8 -*-
"""An Anthropic provider implementation."""

from __future__ import annotations

import json
import logging
import time
from typing import Any, List

from agentscope.model import ChatModelBase
import anthropic

from copaw.providers.multimodal_prober import (
    ProbeResult,
    _PROBE_IMAGE_B64,
    _is_media_keyword_error,
)
from copaw.providers.provider import ModelInfo, Provider

logger = logging.getLogger(__name__)

DASHSCOPE_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
CODING_DASHSCOPE_BASE_URL = "https://coding.dashscope.aliyuncs.com/v1"


class AnthropicProvider(Provider):
    """Provider implementation for Anthropic API."""

    def _client(self, timeout: float = 5) -> anthropic.AsyncAnthropic:
        kwargs: dict = {
            "api_key": self.api_key,
            "base_url": self.base_url,
            "timeout": timeout,
        }
        if self.base_url and "api.anthropic.com" not in self.base_url:
            try:
                import httpx

                class _StripSDKHeadersTransport(httpx.AsyncHTTPTransport):
                    async def handle_async_request(self, request):
                        filtered = [
                            item for item in request.headers._list
                            if not item[0].lower().startswith(b"x-stainless")
                            and item[0].lower() != b"user-agent"
                        ]
                        filtered.append(
                            (b"user-agent", b"user-agent", b"python-httpx/0.27.0")
                        )
                        object.__setattr__(request.headers, "_list", filtered)
                        return await super().handle_async_request(request)

                kwargs["http_client"] = httpx.AsyncClient(
                    transport=_StripSDKHeadersTransport()
                )
                kwargs["default_headers"] = {"x-api-key": self.api_key}
            except Exception:
                pass
        return anthropic.AsyncAnthropic(**kwargs)

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
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": "ping",
                        },
                    ],
                },
            ],
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

        client_kwargs = {"base_url": self.base_url}
        if self.base_url == DASHSCOPE_BASE_URL:
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
        elif self.base_url == CODING_DASHSCOPE_BASE_URL:
            client_kwargs["default_headers"] = {
                "X-DashScope-Cdpl": json.dumps(
                    {
                        "agentType": "CoPaw",
                        "deployType": "UnKnown",
                        "moduleCode": "model",
                        "agentCode": "UnKnown",
                    },
                    ensure_ascii=False,
                ),
            }
        elif self.base_url and "api.anthropic.com" not in self.base_url:
            # 自定义中转服务：过滤 x-stainless-* 遥测头和 SDK User-Agent
            # 部分中转（如 fluxmod.art）会拦截 Anthropic SDK 特征请求头
            try:
                import httpx

                class _StripSDKHeadersTransport(httpx.AsyncHTTPTransport):
                    _api_key: str

                    def __init__(self, api_key: str, **kwargs):
                        super().__init__(**kwargs)
                        self._api_key = api_key

                    async def handle_async_request(self, request):
                        filtered = [
                            item for item in request.headers._list
                            if not item[0].lower().startswith(b"x-stainless")
                            and item[0].lower() != b"user-agent"
                        ]
                        filtered.append(
                            (b"user-agent", b"user-agent", b"python-httpx/0.27.0")
                        )
                        object.__setattr__(request.headers, "_list", filtered)
                        return await super().handle_async_request(request)

                client_kwargs["http_client"] = httpx.AsyncClient(
                    transport=_StripSDKHeadersTransport(api_key=self.api_key)
                )
                client_kwargs["default_headers"] = {
                    "x-api-key": self.api_key,
                }
            except Exception:
                pass

        return AnthropicChatModel(
            model_name=model_id,
            stream=True,
            api_key=self.api_key,
            stream_tool_parsing=False,
            client_kwargs=client_kwargs,
            generate_kwargs=self.generate_kwargs,
        )

    async def probe_model_multimodal(
        self,
        model_id: str,
        timeout: float = 10,
    ) -> ProbeResult:
        """Probe multimodal support using Anthropic messages API format.

        Anthropic does not support video input, so supports_video is
        always False.  Image support is probed by sending a minimal 1x1
        PNG via the Anthropic base64 image source format.
        """
        img_ok, img_msg = await self._probe_image_support(
            model_id,
            timeout,
        )
        return ProbeResult(
            supports_image=img_ok,
            supports_video=False,
            image_message=img_msg,
            video_message="Video not supported by Anthropic",
        )

    async def _probe_image_support(
        self,
        model_id: str,
        timeout: float = 10,
    ) -> tuple[bool, str]:
        """Probe image support via Anthropic messages API."""
        logger.info(
            "Image probe start: model=%s url=%s",
            model_id,
            self.base_url,
        )
        start_time = time.monotonic()
        client = self._client(timeout=timeout)
        try:
            resp = await client.messages.create(
                model=model_id,
                max_tokens=1,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": "image/png",
                                    "data": _PROBE_IMAGE_B64,
                                },
                            },
                            {"type": "text", "text": "hi"},
                        ],
                    },
                ],
                stream=True,
            )
            async for _ in resp:
                break
            elapsed = time.monotonic() - start_time
            logger.info(
                "Image probe done: model=%s result=%s %.2fs",
                model_id,
                True,
                elapsed,
            )
            return True, "Image supported"
        except anthropic.APIError as e:
            elapsed = time.monotonic() - start_time
            logger.warning(
                "Image probe error: model=%s type=%s msg=%s %.2fs",
                model_id,
                type(e).__name__,
                e,
                elapsed,
            )
            status = getattr(e, "status_code", None)
            if status == 400 or _is_media_keyword_error(e):
                return False, f"Image not supported: {e}"
            return False, f"Probe inconclusive: {e}"
        except Exception as e:
            elapsed = time.monotonic() - start_time
            logger.warning(
                "Image probe error: model=%s type=%s msg=%s %.2fs",
                model_id,
                type(e).__name__,
                e,
                elapsed,
            )
            return False, f"Probe failed: {e}"
