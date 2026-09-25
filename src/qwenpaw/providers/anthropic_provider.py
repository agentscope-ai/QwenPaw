# -*- coding: utf-8 -*-
"""An Anthropic provider implementation."""

from __future__ import annotations

import json
import logging
import time
from typing import Any, ClassVar, Dict, List

from agentscope.model import ChatModelBase
import anthropic
from pydantic import Field

from .model_info import release_date
from ..utils.io_utils import run_sync_io
from .adapters.wire_protocol import anthropic_base_url
from .multimodal_prober import (
    ProbeResult,
    _PROBE_IMAGE_B64,
    _PROBE_VIDEO_B64,
    _PROBE_VIDEO_URL,
    _IMAGE_PROBE_PROMPT,
    _is_media_keyword_error,
    evaluate_image_probe_answer,
    evaluate_video_probe_answer,
)
from .provider import (
    ModelConnectionResult,
    ModelInfo,
    Provider,
)

from ..utils.logging import sanitize_log_value
from .adapters.anthropic import (
    AnthropicModel as _AnthropicChatModelCompat,
    strip_api_key_header,
    resolve_parameters,
)
from .capping_formatter import (
    ANTHROPIC_AUDIO_BYTES,
    ANTHROPIC_IMAGE_BYTES,
    ANTHROPIC_VIDEO_BYTES,
    _CappingAnthropicFormatter,
)

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


class AnthropicProvider(Provider):
    """Provider implementation for Anthropic API."""

    wire_protocol: ClassVar[str] = f"anthropic"

    def cache_capabilities(self, model_id: str) -> frozenset[str]:
        """Anthropic wire format supports explicit cache breakpoints."""
        if model_id.startswith(f"claude-"):
            return frozenset({f"anthropic"})
        return super().cache_capabilities(model_id)

    max_inline_media_bytes: int = Field(
        default=ANTHROPIC_AUDIO_BYTES,
        ge=0,
        description=(
            "Maximum size (in bytes) of a local media file inlined as "
            "base64 into the model request body. Media above this is "
            "replaced with a text placeholder to avoid oversized requests "
            "when large files (e.g. generated videos) persist in "
            "conversation history. 0 disables capping."
        ),
    )
    max_image_bytes: int | None = Field(default=ANTHROPIC_IMAGE_BYTES, ge=0)
    max_video_bytes: int | None = Field(default=ANTHROPIC_VIDEO_BYTES, ge=0)
    max_audio_bytes: int | None = Field(default=ANTHROPIC_AUDIO_BYTES, ge=0)

    # Cached AsyncClient for auth_token mode; re-created when auth_mode
    # changes so that the transport is always consistent with the current
    # provider config.
    _strip_http_client: Any | None = None

    async def close(self) -> None:
        """Release the cached transport after replacing configuration."""
        client, self._strip_http_client = self._strip_http_client, None
        if client is not None:
            await client.aclose()

    def _build_default_headers(self) -> Dict[str, str]:
        return dict(self.custom_headers) if self.custom_headers else {}

    def _get_strip_http_client(self) -> Any:
        """Use the SDK's client type and strip API keys before sending."""
        if self._strip_http_client is None:
            self._strip_http_client = anthropic.DefaultAsyncHttpxClient(
                event_hooks={f"request": [strip_api_key_header]},
            )
        return self._strip_http_client

    def _client(self, timeout: float = 5) -> anthropic.AsyncAnthropic:
        default_headers = self._build_default_headers()
        if self.auth_mode == "auth_token":
            return anthropic.AsyncAnthropic(
                auth_token=self.api_key,
                base_url=anthropic_base_url(self.base_url),
                default_headers=default_headers,
                http_client=self._get_strip_http_client(),
                timeout=timeout,
            )
        return anthropic.AsyncAnthropic(
            api_key=self.api_key,
            base_url=anthropic_base_url(self.base_url),
            default_headers=default_headers,
            timeout=timeout,
        )

    async def _close_client(
        self,
        client: anthropic.AsyncAnthropic,
    ) -> None:
        """Close one SDK client without closing a shared HTTP client."""
        if self.auth_mode == "auth_token":
            return
        close = getattr(client, "close", None)
        if close is not None:
            await close()

    @classmethod
    def _normalize_models_payload(cls, payload: Any) -> List[ModelInfo]:
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
            metadata: dict[str, Any] = {
                **cls.parse_model_pricing(row),
                f"released_at": release_date(
                    getattr(row, f"created_at", None),
                ),
            }
            context_window = getattr(row, f"max_input_tokens", None)
            if (
                isinstance(context_window, (int, float))
                and context_window >= 1000
            ):
                metadata[f"max_input_length_auto_detected"] = int(
                    context_window,
                )
                metadata[f"input_token_limit"] = int(context_window)
                metadata[f"input_token_limit_source"] = f"api"
            output_limit = getattr(row, f"max_tokens", None)
            if type(output_limit) is int and output_limit > 0:
                metadata[f"max_output_length"] = output_limit
                metadata[f"max_output_length_source"] = f"api"
            models.append(ModelInfo(id=model_id, name=model_name, **metadata))

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
        client = await run_sync_io(self._client, timeout=timeout)
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
        finally:
            await self._close_client(client)

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
        client = await run_sync_io(self._client, timeout=timeout)
        try:
            payload = await client.models.list()
            if hasattr(payload, "__aiter__"):
                rows = [row async for row in payload]
                return self._normalize_models_payload(rows)
            return self._normalize_models_payload(payload)
        finally:
            await self._close_client(client)

    async def check_model_connection(
        self,
        model_id: str,
        timeout: float = 5,
    ) -> ModelConnectionResult:
        """Check if a specific model is reachable/usable."""
        target = (model_id or "").strip()
        if not target:
            return ModelConnectionResult(
                success=False,
                message="Empty model ID",
            )

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
        client = await run_sync_io(self._client, timeout=timeout)
        try:
            resp = await client.messages.create(**body)
            try:
                # Consume one event to ensure the model is responsive.
                async for _ in resp:
                    break
            finally:
                await resp.close()
            return ModelConnectionResult(success=True)
        except anthropic.APIError as exc:
            status = getattr(exc, "status_code", None)
            return ModelConnectionResult(
                success=False,
                message=(
                    f"Model '{model_id}' is not reachable or usable: "
                    f"{self.connection_error_message(exc)}"
                ),
                http_status=status if isinstance(status, int) else None,
                error_kind=(
                    "permission_denied"
                    if status in (401, 403)
                    else "model_not_found"
                    if status == 404
                    else None
                ),
            )
        except Exception as exc:
            return ModelConnectionResult(
                success=False,
                message=(
                    f"Unknown exception when connecting to model "
                    f"'{model_id}': {self.connection_error_message(exc)}"
                ),
            )
        finally:
            await self._close_client(client)

    def get_chat_model_instance(self, model_id: str) -> ChatModelBase:
        from agentscope.credential import AnthropicCredential

        effective_generate_kwargs = self.get_effective_generate_kwargs(
            model_id,
        )
        output_cap = self.resolve_model_info(model_id).max_output_length
        parameters, effective_generate_kwargs = resolve_parameters(
            effective_generate_kwargs,
            output_cap,
        )

        credential = AnthropicCredential(
            api_key=self.api_key or "",
            base_url=anthropic_base_url(self.base_url),
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
            output_capacity=output_cap,
            request_policy=self.prepare_request,
            extra_generate_kwargs=effective_generate_kwargs,
            credential=credential,
            model=model_id,
            parameters=parameters,
            stream=True,
            default_headers=merged_headers or None,
            auth_mode=getattr(self, "auth_mode", None),
            context_size=self._get_context_size(model_id),
            formatter=_CappingAnthropicFormatter(
                max_bytes=self.max_inline_media_bytes,
                max_image_bytes=self.max_image_bytes,
                max_video_bytes=self.max_video_bytes,
                max_audio_bytes=self.max_audio_bytes,
            ),
        )

    async def probe_model_multimodal(
        self,
        model_id: str,
        timeout: float = 60,
        image_only: bool = False,
    ) -> ProbeResult:
        """Probe multimodal support via Anthropic messages API.

        Image support is probed by sending a solid-red PNG.
        Video support is probed by sending a solid-blue MP4
        to cover third-party Anthropic-compatible providers
        that accept video input (official Anthropic does not).
        """
        img_ok, img_msg = await self._probe_image_support(
            model_id,
            timeout,
        )
        if not img_ok:
            return ProbeResult(
                supports_image=img_ok,
                supports_video=None,
                image_message=img_msg,
                video_message="Skipped: image probe failed",
            )
        if image_only:
            return ProbeResult(
                supports_image=img_ok,
                supports_video=False,
                image_message=img_msg,
                video_message="Skipped: image_only=True",
            )
        vid_ok, vid_msg = await self._probe_video_support(
            model_id,
            timeout,
        )
        return ProbeResult(
            supports_image=img_ok,
            supports_video=vid_ok,
            image_message=img_msg,
            video_message=vid_msg,
        )

    async def _probe_video_support(
        self,
        model_id: str,
        timeout: float = 30,
    ) -> tuple[bool | None, str]:
        """Probe video support via Anthropic messages API.

        Tries a base64 probe video first; if the provider
        rejects it (400) falls back to an HTTP URL probe.
        Official Anthropic endpoints reject ``video`` blocks
        entirely; third-party providers may accept them.
        """
        log_model = sanitize_log_value(model_id)
        logger.info(
            "Video probe start: model=%s url=%s",
            log_model,
            self.base_url,
        )
        start_time = time.monotonic()
        sources = [
            {
                "type": "base64",
                "media_type": "video/mp4",
                "data": _PROBE_VIDEO_B64,
            },
            {
                "type": "url",
                "url": _PROBE_VIDEO_URL,
            },
        ]
        last_err = ""
        last_400: list[str] = []
        for source in sources:
            is_http = source.get("type") == "url"
            result = await self._try_video_source(
                model_id,
                source,
                timeout=(timeout * 3 if is_http else timeout),
                start_time=start_time,
                is_http=is_http,
                last_400=last_400,
            )
            if result is not None:
                return result
            detail = last_400[-1] if last_400 else ""
            last_err = (
                f"format rejected ({source['type']})"
                f"{f': {detail}' if detail else ''}"
            )
        elapsed = time.monotonic() - start_time
        logger.info(
            "Video probe: model=%s ok=False %.2fs",
            log_model,
            elapsed,
        )
        return False, f"Video not supported: {last_err}"

    async def _try_video_source(
        self,
        model_id: str,
        source: dict,
        timeout: float,
        *,
        start_time: float,
        is_http: bool = False,
        last_400: list[str] | None = None,
    ) -> tuple[bool | None, str] | None:
        """Try one video source format. Return None to try next.

        If a 400 error occurs and *last_400* is provided, the
        error summary is appended to help callers log the
        actual rejection reason.
        """
        log_model = sanitize_log_value(model_id)
        client = await run_sync_io(self._client, timeout=timeout)
        try:
            resp = await client.messages.create(
                model=model_id,
                max_tokens=200,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "video",
                                "source": source,
                            },
                            {
                                "type": "text",
                                "text": (
                                    "What is the single "
                                    "dominant color shown "
                                    "in this video? Reply "
                                    "with ONLY the color "
                                    "name, nothing else."
                                ),
                            },
                        ],
                    },
                ],
            )
            answer = ""
            thinking = ""
            for block in resp.content:
                btype = getattr(block, "type", "")
                if btype == "thinking":
                    thinking += getattr(
                        block,
                        "thinking",
                        "",
                    )
                elif hasattr(block, "text"):
                    answer += block.text
            return evaluate_video_probe_answer(
                answer,
                model_id,
                start_time,
                reasoning=thinking,
                is_http=is_http,
            )
        except anthropic.APIError as e:
            status = getattr(e, "status_code", None)
            if status == 400:
                logger.debug(
                    "Video probe format rejected (400): %s",
                    e,
                )
                if last_400 is not None:
                    last_400.append(str(e)[:200])
                return None
            elapsed = time.monotonic() - start_time
            err_type = type(e).__name__
            logger.warning(
                "Video probe error: model=%s %s %s %.2fs",
                log_model,
                err_type,
                sanitize_log_value(e),
                elapsed,
            )
            if status in {400, 422} and _is_media_keyword_error(e):
                return False, f"Video not supported: {e}"
            return None, f"Probe inconclusive: {e}"
        except Exception as e:
            elapsed = time.monotonic() - start_time
            err_type = type(e).__name__
            logger.warning(
                "Video probe error: model=%s %s %s %.2fs",
                log_model,
                err_type,
                sanitize_log_value(e),
                elapsed,
            )
            return None, f"Probe failed: {e}"
        finally:
            await self._close_client(client)

    async def _probe_image_support(
        self,
        model_id: str,
        timeout: float = 10,
    ) -> tuple[bool | None, str]:
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
        log_model = sanitize_log_value(model_id)
        logger.info(
            "Image probe start: model=%s url=%s",
            log_model,
            self.base_url,
        )
        start_time = time.monotonic()
        client = await run_sync_io(self._client, timeout=timeout)
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
                log_model,
                type(e).__name__,
                sanitize_log_value(e),
                elapsed,
            )
            status = getattr(e, "status_code", None)
            if status in {400, 422} and _is_media_keyword_error(e):
                return False, f"Image not supported: {e}"
            return None, f"Probe inconclusive: {e}"
        except Exception as e:
            elapsed = time.monotonic() - start_time
            logger.warning(
                "Image probe error: model=%s type=%s msg=%s %.2fs",
                log_model,
                type(e).__name__,
                sanitize_log_value(e),
                elapsed,
            )
            return None, f"Probe failed: {e}"
        finally:
            await self._close_client(client)
