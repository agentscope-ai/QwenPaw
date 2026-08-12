# -*- coding: utf-8 -*-
"""An OpenAI Responses API provider implementation."""

from __future__ import annotations

import logging
import time
from typing import Any

from agentscope.model import ChatModelBase, OpenAIResponseModel

from .capping_formatter import _CappingOpenAIResponseFormatter
from .openai_provider import OpenAIProvider

logger = logging.getLogger(__name__)

_NONE_REASONING_EFFORT_MODELS = frozenset(
    {
        "gpt-5.5",
        "gpt-5.5-2026-04-23",
        "gpt-5.6",
        "gpt-5.6-luna",
        "gpt-5.6-sol",
        "gpt-5.6-terra",
    },
)


def _supports_none_reasoning_effort(model_name: str) -> bool:
    """Whether a documented model accepts ``reasoning.effort=none``."""
    canonical_name = model_name.rsplit("/", 1)[-1].lower()
    return canonical_name in _NONE_REASONING_EFFORT_MODELS


def _extract_response_text(response: Any) -> str:
    """Extract aggregated output text from a Responses API
    response object.

    Prefers the SDK's built-in ``output_text`` property when
    available (concatenates all output_text parts); falls back
    to manual traversal for plain-dict / SimpleNamespace mocks.
    """
    agg = getattr(response, "output_text", None)
    if agg is not None:
        return agg
    for item in getattr(response, "output", []):
        if getattr(item, "type", None) != "message":
            continue
        for part in getattr(item, "content", []):
            if getattr(part, "type", None) == "output_text":
                return getattr(part, "text", "") or ""
    return ""


def _extract_reasoning_text(response: Any) -> str:
    """Extract concatenated reasoning summary text from a
    Responses API response.

    Reasoning items have ``type == "reasoning"`` with a
    ``summary`` list whose elements carry a ``.text``
    attribute.
    """
    parts: list[str] = []
    for item in getattr(response, "output", []):
        if getattr(item, "type", None) != "reasoning":
            continue
        for s in getattr(item, "summary", []):
            text = getattr(s, "text", "")
            if text:
                parts.append(text)
    return " ".join(parts)


class OpenAIResponseModelCompat(OpenAIResponseModel):
    """OpenAIResponseModel with extra-kwargs injection and tool schema
    sanitization.

    * ``extra_generate_kwargs`` — merged into every ``_call_api`` call
      (provider-level kwargs like ``extra_body``).
    * ``_format_tools`` — sanitizes boolean JSON Schema values that strict
      providers reject (same fix as ``OpenAIChatModelCompat``).
    """

    def __init__(
        self,
        *,
        extra_generate_kwargs: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        self._extra_generate_kwargs = extra_generate_kwargs or {}
        super().__init__(**kwargs)

    async def _call_api(
        self,
        model_name: str,
        messages: Any,
        tools: list[dict] | None = None,
        tool_choice: Any | None = None,
        **generate_kwargs: Any,
    ) -> Any:
        max_tokens = generate_kwargs.pop("max_tokens", None)
        if (
            max_tokens is not None
            and "max_output_tokens" not in generate_kwargs
        ):
            generate_kwargs["max_output_tokens"] = max_tokens
        merged = {**self._extra_generate_kwargs, **generate_kwargs}
        disable_thinking = merged.pop("disable_thinking", False)
        inherited_max_tokens = merged.pop("max_tokens", None)
        if (
            inherited_max_tokens is not None
            and "max_output_tokens" not in merged
        ):
            merged["max_output_tokens"] = inherited_max_tokens
        if disable_thinking:
            merged.pop("reasoning", None)
            if _supports_none_reasoning_effort(model_name):
                merged["reasoning"] = {"effort": "none"}
        return await super()._call_api(
            model_name,
            messages,
            tools,
            tool_choice,
            **merged,
        )

    def _format_tools(
        self,
        tools: list[dict] | None,
        tool_choice: Any | None,
    ) -> tuple[list[dict] | None, Any]:
        from .openai_chat_model_compat import _sanitize_tool_schemas

        if tools:
            tools = _sanitize_tool_schemas(tools)
        return super()._format_tools(tools, tool_choice)


class OpenAIResponseProvider(OpenAIProvider):
    """Provider that uses the OpenAI Responses API instead of
    Chat Completions.

    Inherits connection/discovery logic from ``OpenAIProvider``
    but creates ``OpenAIResponseModel`` instances via
    ``get_chat_model_instance``.

    Multimodal probing is overridden to use the Responses API
    endpoint (``client.responses.create``) so the probe result
    accurately reflects what the Responses API actually
    supports.  This prevents false-positive ``supports_video``
    results that occur when probing via Chat Completions on
    providers where the Responses API does not support video
    (e.g. DashScope).
    """

    async def check_model_connection(
        self,
        model_id: str,
        timeout: float = 5,
    ) -> tuple[bool, str]:
        """Check if a model is reachable via the Responses API."""
        from openai import APIError

        model_id = (model_id or "").strip()
        if not model_id:
            return False, "Empty model ID"

        try:
            client = self._client(timeout=timeout)
            res = await client.responses.create(
                model=model_id,
                input="ping",
                timeout=timeout,
                max_output_tokens=20,
                stream=True,
            )
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

    # Responses API's max_output_tokens includes reasoning
    # tokens, so reasoning models (o-series, gpt-5) can
    # exhaust the budget on thinking alone.  1024 gives enough
    # headroom for a one-word color answer after reasoning.
    _PROBE_TOKEN_BUDGET = 1024

    async def _probe_image_support(
        self,
        model_id: str,
        timeout: float = 15,
    ) -> tuple[bool, str]:
        """Probe image support via the Responses API."""
        from openai import APIError

        from .multimodal_prober import (
            _IMAGE_PROBE_PROMPT,
            _PROBE_IMAGE_B64,
            _is_media_keyword_error,
            evaluate_image_probe_answer,
        )

        logger.info(
            "Image probe (responses) start: model=%s url=%s",
            model_id,
            self.base_url,
        )
        start_time = time.monotonic()
        client = self._client(timeout=timeout)
        try:
            res = await client.responses.create(
                model=model_id,
                input=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "input_image",
                                "image_url": (
                                    "data:image/png;base64,"
                                    f"{_PROBE_IMAGE_B64}"
                                ),
                            },
                            {
                                "type": "input_text",
                                "text": _IMAGE_PROBE_PROMPT,
                            },
                        ],
                    },
                ],
                max_output_tokens=self._PROBE_TOKEN_BUDGET,
                timeout=timeout,
            )
            answer = _extract_response_text(res).lower().strip()
            reasoning = _extract_reasoning_text(res).lower().strip()
            return evaluate_image_probe_answer(
                answer,
                model_id,
                start_time,
                reasoning,
            )
        except APIError as e:
            elapsed = time.monotonic() - start_time
            logger.warning(
                "Image probe error: model=%s %s %.2fs",
                model_id,
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
                "Image probe error: model=%s %s %.2fs",
                model_id,
                e,
                elapsed,
            )
            return False, f"Probe failed: {e}"

    async def _try_video_url(
        self,
        model_id: str,
        video_url: str,
        timeout: float,
        *,
        start_time: float,
    ) -> tuple[bool, str] | None:
        """Try a single video URL via the Responses API.

        Returns None to signal the caller should try the next
        format.
        """
        from openai import APIError

        from .multimodal_prober import (
            _PROBE_VIDEO_URL,
            _is_media_keyword_error,
            evaluate_video_probe_answer,
        )

        is_http = video_url == _PROBE_VIDEO_URL
        req_timeout = timeout * 3 if is_http else timeout
        client = self._client(timeout=req_timeout)
        try:
            res = await client.responses.create(
                model=model_id,
                input=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "input_video",
                                "video_url": video_url,
                            },
                            {
                                "type": "input_text",
                                "text": (
                                    "What is the single "
                                    "dominant color shown in "
                                    "this video? Reply with "
                                    "ONLY the color name, "
                                    "nothing else."
                                ),
                            },
                        ],
                    },
                ],
                max_output_tokens=self._PROBE_TOKEN_BUDGET,
                timeout=req_timeout,
            )
            answer = _extract_response_text(res)
            reasoning = _extract_reasoning_text(res)
            return evaluate_video_probe_answer(
                answer,
                model_id,
                start_time,
                reasoning=reasoning,
                is_http=is_http,
            )
        except APIError as e:
            status = getattr(e, "status_code", None)
            if status == 400:
                logger.debug(
                    "Video probe format rejected (400): %s",
                    e,
                )
                return None
            elapsed = time.monotonic() - start_time
            is_kw = _is_media_keyword_error(e)
            label = "not supported" if is_kw else "inconclusive"
            logger.warning(
                "Video probe error: model=%s %s %.2fs",
                model_id,
                e,
                elapsed,
            )
            return False, f"Video {label}: {e}"
        except Exception as e:
            elapsed = time.monotonic() - start_time
            logger.warning(
                "Video probe error: model=%s %s %.2fs",
                model_id,
                e,
                elapsed,
            )
            return False, f"Probe failed: {e}"

    def get_chat_model_instance(self, model_id: str) -> ChatModelBase:
        from agentscope.credential import OpenAICredential

        credential = OpenAICredential(
            id=f"qwenpaw-{self.id}",
            api_key=self.api_key,
            base_url=self.base_url,
        )

        merged_headers = self._build_default_headers()
        gen_kwargs = self.get_effective_generate_kwargs(model_id)
        parameters = OpenAIResponseModel.Parameters(
            max_tokens=gen_kwargs.pop("max_tokens", None),
            temperature=gen_kwargs.pop("temperature", None),
        )

        client_kwargs: dict[str, Any] = {}
        if merged_headers:
            client_kwargs["default_headers"] = merged_headers

        return OpenAIResponseModelCompat(
            credential=credential,
            model=model_id,
            parameters=parameters,
            stream=True,
            context_size=self._get_context_size(model_id),
            client_kwargs=client_kwargs,
            extra_generate_kwargs=gen_kwargs or None,
            formatter=_CappingOpenAIResponseFormatter(
                max_bytes=self.max_inline_media_bytes,
            ),
        )
