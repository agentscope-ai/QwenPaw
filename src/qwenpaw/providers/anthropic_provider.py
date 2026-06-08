# -*- coding: utf-8 -*-
"""An Anthropic provider implementation."""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime
from typing import Any, Dict, List

import httpx
from agentscope.model import ChatModelBase
import anthropic

from qwenpaw.providers.multimodal_prober import (
    ProbeResult,
    _PROBE_IMAGE_B64,
    _IMAGE_PROBE_PROMPT,
    _is_media_keyword_error,
    evaluate_image_probe_answer,
)
from qwenpaw.providers.provider import ModelInfo, Provider

logger = logging.getLogger(__name__)

DASHSCOPE_BASE_URLS = (
    "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
    "https://dashscope-us.aliyuncs.com/compatible-mode/v1",
)
CODING_DASHSCOPE_BASE_URL = "https://coding.dashscope.aliyuncs.com/v1"
TOKEN_PLAN_BASE_URL = (
    "https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"
)


class _StripApiKeyTransport(httpx.AsyncHTTPTransport):
    """Async transport that removes the x-api-key header from every request.

    Used when auth_mode='auth_token' to avoid sending both x-api-key and
    Authorization headers simultaneously, which some proxies reject.

    The request is reconstructed with ``extensions`` preserved so that
    per-request configuration such as timeouts and SSE hints set by the
    Anthropic SDK are not lost.
    """

    async def handle_async_request(
        self,
        request: httpx.Request,
    ) -> httpx.Response:
        filtered = [
            (k, v)
            for k, v in request.headers.items()
            if k.lower() != "x-api-key"
        ]
        new_request = httpx.Request(
            method=request.method,
            url=request.url,
            headers=filtered,
            content=request.content,
            extensions=request.extensions,
        )
        return await super().handle_async_request(new_request)


class AnthropicProvider(Provider):
    """Provider implementation for Anthropic API."""

    # Cached AsyncClient for auth_token mode; re-created when auth_mode
    # changes so that the transport is always consistent with the current
    # provider config.
    _strip_http_client: httpx.AsyncClient | None = None

    def _build_default_headers(self) -> Dict[str, str]:
        return dict(self.custom_headers) if self.custom_headers else {}

    def _get_strip_http_client(self) -> httpx.AsyncClient:
        """Return a cached AsyncClient backed by _StripApiKeyTransport."""
        if self._strip_http_client is None:
            self._strip_http_client = httpx.AsyncClient(
                transport=_StripApiKeyTransport(),
            )
        return self._strip_http_client

    def _client(self, timeout: float = 5) -> anthropic.AsyncAnthropic:
        default_headers = self._build_default_headers()
        if self.auth_mode == "auth_token":
            return anthropic.AsyncAnthropic(
                auth_token=self.api_key,
                base_url=self.base_url,
                default_headers=default_headers,
                http_client=self._get_strip_http_client(),
                timeout=timeout,
            )
        return anthropic.AsyncAnthropic(
            api_key=self.api_key,
            base_url=self.base_url,
            default_headers=default_headers,
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
        """Check if Anthropic provider is reachable.

        First tries models.list(); if that endpoint is not supported by the
        proxy (e.g. returns 404/405) falls back to a minimal messages.create
        call so that custom proxies that only expose the messages API still
        pass the connection test.
        """
        client = self._client(timeout=timeout)
        try:
            await client.models.list()
            return True, ""
        except anthropic.APIStatusError as e:
            # Some proxies don't implement the models endpoint (404/405).
            # Fall back to a lightweight messages probe instead.
            if e.status_code in (404, 405):
                return await self._check_connection_via_messages(client)
            return False, f"Anthropic API error: {e}"
        except anthropic.APIError as e:
            # Network / auth errors from models.list – report directly
            return False, f"Anthropic API error: {e}"
        except Exception:
            return (
                False,
                f"Unknown exception when connecting to `{self.base_url}`",
            )

    async def _check_connection_via_messages(
        self,
        client: anthropic.AsyncAnthropic,
    ) -> tuple[bool, str]:
        """Fallback: check reachability via messages.create."""
        model = self.models[0].id if self.models else "claude-opus-4-5"
        try:
            await client.messages.create(
                model=model,
                max_tokens=1,
                messages=[{"role": "user", "content": "ping"}],
            )
            return True, ""
        except anthropic.APIStatusError as e:
            # 400/404/422: server is reachable and auth is accepted –
            # the model may simply not exist on this proxy, which is fine
            # for a connection check.
            if e.status_code in (400, 404, 422):
                return True, ""
            return False, f"Anthropic API error: {e}"
        except anthropic.APIError as e:
            return False, f"Anthropic API error: {e}"
        except Exception as e:
            return False, f"Unknown exception: {e}"

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
        from agentscope.credential import AnthropicCredential
        from agentscope.model import AnthropicChatModel

        effective_generate_kwargs = self.get_effective_generate_kwargs(
            model_id,
        )
        max_tokens = effective_generate_kwargs.pop("max_tokens", 16384)

        params_kwargs: Dict[str, Any] = {"max_tokens": max_tokens}
        for key in ("thinking_enable", "thinking_budget"):
            if key in effective_generate_kwargs:
                params_kwargs[key] = effective_generate_kwargs.pop(key)

        credential = AnthropicCredential(
            api_key=self.api_key or "",
            base_url=self.base_url,
        )

        merged_headers = self._build_default_headers()
        dashscope_meta = json.dumps(
            {
                "agentType": "QwenPaw",
                "deployType": "UnKnown",
                "moduleCode": "model",
                "agentCode": "UnKnown",
            },
            ensure_ascii=False,
        )
        if self.base_url in DASHSCOPE_BASE_URLS:
            merged_headers["x-dashscope-agentapp"] = dashscope_meta
        elif self.base_url in (
            CODING_DASHSCOPE_BASE_URL,
            TOKEN_PLAN_BASE_URL,
        ):
            merged_headers["X-DashScope-Cdpl"] = dashscope_meta

        return _AnthropicChatModelCompat(
            credential=credential,
            model=model_id,
            parameters=AnthropicChatModel.Parameters(**params_kwargs),
            stream=True,
            default_headers=merged_headers or None,
            auth_mode=getattr(self, "auth_mode", None),
            strip_http_client=(
                self._get_strip_http_client()
                if getattr(self, "auth_mode", None) == "auth_token"
                else None
            ),
        )

    async def probe_model_multimodal(
        self,
        model_id: str,
        timeout: float = 60,
        image_only: bool = False,  # pylint: disable=unused-argument
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
        """Probe image support via Anthropic messages API.

        Uses a two-stage check (same strategy as OpenAIProvider):
        1. If the API rejects the request (400 / media-keyword error)
           -> not supported.
        2. If accepted, verify the model can *actually perceive* the
           image by asking for the dominant color of a solid-red PNG.
           Some providers silently accept image payloads without
           processing them, so a pure API-error check would produce
           false positives.
        """
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
                max_tokens=200,
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
                            {
                                "type": "text",
                                "text": _IMAGE_PROBE_PROMPT,
                            },
                        ],
                    },
                ],
            )
            answer = ""
            for block in resp.content:
                if hasattr(block, "text"):
                    answer += block.text
            return evaluate_image_probe_answer(
                answer,
                model_id,
                start_time,
            )
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


class _AnthropicChatModelCompat:
    """Mixin wrapper around ``AnthropicChatModel`` that injects custom headers
    and supports ``auth_token`` mode.

    Constructed lazily so the import-heavy ``AnthropicChatModel`` doesn't slow
    module load when Anthropic is not configured.
    """

    def __new__(cls, **kwargs: Any) -> Any:
        from agentscope.model import AnthropicChatModel

        default_headers = kwargs.pop("default_headers", None)
        auth_mode = kwargs.pop("auth_mode", None)
        strip_http_client = kwargs.pop("strip_http_client", None)

        class _Compat(AnthropicChatModel):
            _qp_default_headers = default_headers
            _qp_auth_mode = auth_mode
            _qp_strip_http_client = strip_http_client
            _qp_cached_client: Any = None
            _qp_cached_client_key: tuple = ()

            def _get_or_create_client(self) -> Any:
                """Return a cached AsyncAnthropic client, rebuilding only when
                credential or base_url changes."""
                key = (
                    self.credential.base_url,
                    self.credential.api_key.get_secret_value(),
                    id(self._qp_default_headers),
                    self._qp_auth_mode,
                )
                if (
                    self._qp_cached_client is not None
                    and self._qp_cached_client_key == key
                ):
                    return self._qp_cached_client

                client_kwargs: Dict[str, Any] = {
                    "base_url": self.credential.base_url,
                }
                if self._qp_default_headers:
                    client_kwargs["default_headers"] = self._qp_default_headers
                if self._qp_auth_mode == "auth_token":
                    client_kwargs[
                        "auth_token"
                    ] = self.credential.api_key.get_secret_value()
                    if self._qp_strip_http_client is not None:
                        client_kwargs[
                            "http_client"
                        ] = self._qp_strip_http_client
                else:
                    client_kwargs[
                        "api_key"
                    ] = self.credential.api_key.get_secret_value()

                self._qp_cached_client = anthropic.AsyncAnthropic(
                    **client_kwargs,
                )
                self._qp_cached_client_key = key
                return self._qp_cached_client

            async def _call_api(
                self,
                model_name,
                messages,
                tools=None,
                tool_choice=None,
                **generate_kwargs,
            ):
                client = self._get_or_create_client()

                max_tokens = self.parameters.max_tokens or 8192
                kw: Dict[str, Any] = {
                    "model": model_name,
                    "max_tokens": max_tokens,
                    "stream": self.stream,
                    **generate_kwargs,
                }
                if self.parameters.thinking_enable and "thinking" not in kw:
                    budget = self.parameters.thinking_budget or (
                        max_tokens // 2
                    )
                    if budget >= max_tokens:
                        max_tokens = budget + 1024
                        kw["max_tokens"] = max_tokens
                    kw["thinking"] = {
                        "type": "enabled",
                        "budget_tokens": budget,
                    }

                fmt_tools, fmt_tc = self._format_tools(tools, tool_choice)
                if fmt_tools:
                    kw["tools"] = fmt_tools
                if fmt_tc is not None:
                    kw["tool_choice"] = fmt_tc

                formatted = await self.formatter.format(messages)
                if formatted and formatted[0]["role"] == "system":
                    kw["system"] = formatted[0]["content"]
                    formatted = formatted[1:]
                kw["messages"] = formatted

                start = datetime.now()
                response = await client.messages.create(**kw)

                if self.stream:
                    return self._parse_anthropic_stream_completion_response(
                        start,
                        response,
                    )
                return await self._parse_anthropic_completion_response(
                    start,
                    response,
                )

        return _Compat(**kwargs)
