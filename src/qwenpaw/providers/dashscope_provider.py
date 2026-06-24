# -*- coding: utf-8 -*-
"""DashScope provider using agentscope 2.0 native ``DashScopeChatModel``.

Most surface area (connection check, model listing, multimodal probe) is
reused from :class:`OpenAIProvider` because DashScope's
``compatible-mode/v1`` endpoint speaks OpenAI HTTP.  Only
:meth:`get_chat_model_instance` is overridden to construct the native 2.0
``DashScopeChatModel(credential=DashScopeCredential(...), ...)`` instead
of the OpenAI-compat wrapper.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict

from agentscope.formatter import DashScopeChatFormatter
from agentscope.message import Base64Source, URLSource
from agentscope.model import ChatModelBase
from pydantic import Field

from .openai_provider import (
    CODING_DASHSCOPE_BASE_URL,
    DASHSCOPE_BASE_URLS,
    TOKEN_PLAN_BASE_URL,
    OpenAIProvider,
)

logger = logging.getLogger(__name__)

# Maximum size (in bytes) of a local media file that we are willing to
# inline as base64 into the model request body.  agentscope's base
# DashScope formatter reads every ``file://`` media source off disk and
# base64-encodes the *entire* file on every API call — so a large file
# persisted in conversation history (e.g. a 42 MB generated video) would
# balloon the request body and cause the provider to drop the connection
# on every subsequent turn.  The model does not need such large media
# echoed back (it already has the surrounding text context), so anything
# above this cap is substituted with a small text placeholder.
_MAX_INLINE_MEDIA_BYTES = 2 * 1024 * 1024  # 2 MB


class DashScopeProvider(OpenAIProvider):
    """Provider that wires the builtin DashScope endpoint to 2.0 native
    ``DashScopeChatModel``."""

    chat_model: str = Field(default="DashScopeChatModel")

    max_inline_media_bytes: int = Field(
        default=_MAX_INLINE_MEDIA_BYTES,
        ge=0,
        description=(
            "Maximum size (in bytes) of a local media file inlined as "
            "base64 into the model request body. Media above this is "
            "replaced with a text placeholder to avoid oversized requests "
            "when large files (e.g. generated videos) persist in "
            "conversation history. 0 disables capping."
        ),
    )

    def get_chat_model_instance(self, model_id: str) -> ChatModelBase:
        from agentscope.credential import DashScopeCredential
        from agentscope.model import DashScopeChatModel

        if not self.api_key:
            from qwenpaw.exceptions import ProviderError

            raise ProviderError(
                message=(
                    f"DashScope provider '{self.id}' has no api_key "
                    "configured."
                ),
            )

        credential = DashScopeCredential(
            api_key=self.api_key,
            base_url=self.base_url,
        )

        effective = self.get_effective_generate_kwargs(model_id)

        # Back-compat: honour OpenAI-style ``extra_body`` so configs written
        # for the old OpenAIProvider path keep working after migration to the
        # native DashScopeChatModel.  Direct top-level keys take precedence.
        # Mapped keys are promoted; unmapped keys stay in ``extra_body`` and
        # are forwarded via ``extra_generate_kwargs``.
        extra_body = effective.pop("extra_body", None)
        if isinstance(extra_body, dict):
            remaining_body = dict(extra_body)
            _EXTRA_BODY_MAP = {
                "enable_thinking": "thinking_enable",
                "thinking_budget": "thinking_budget",
                "top_k": "top_k",
            }
            for eb_key, param_key in _EXTRA_BODY_MAP.items():
                if eb_key in remaining_body:
                    if param_key not in effective:
                        effective[param_key] = remaining_body[eb_key]
                    del remaining_body[eb_key]
            if remaining_body:
                effective["extra_body"] = remaining_body

        _PARAM_KEYS = (
            "max_tokens",
            "thinking_enable",
            "thinking_budget",
            "temperature",
            "top_p",
            "top_k",
            "parallel_tool_calls",
        )
        param_kwargs: Dict[str, Any] = {}
        for key in _PARAM_KEYS:
            if key in effective:
                param_kwargs[key] = effective.pop(key)

        thinking_explicitly_set = "thinking_enable" in param_kwargs

        # Remaining kwargs (e.g. seed, stop, frequency_penalty, …) are
        # forwarded to every ``_call_api`` invocation so user-supplied
        # generate_kwargs are not silently dropped.
        extra_generate_kwargs = effective or None

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

        return _DashScopeChatModelCompat(
            credential=credential,
            model=model_id,
            parameters=DashScopeChatModel.Parameters(**param_kwargs),
            stream=True,
            default_headers=merged_headers or None,
            context_size=self._get_context_size(model_id),
            thinking_explicitly_set=thinking_explicitly_set,
            extra_generate_kwargs=extra_generate_kwargs,
            formatter=_CappingDashScopeFormatter(
                max_bytes=self.max_inline_media_bytes,
            ),
        )


class _CappingDashScopeFormatter(DashScopeChatFormatter):
    """DashScope formatter that refuses to inline oversized local media.

    Overrides the per-source formatters to substitute a text placeholder
    when the underlying media would exceed ``max_bytes``.  Operates purely
    on the ephemeral formatted output, so persisted conversation history
    and UI media rendering are unaffected.  ``max_bytes <= 0`` disables
    capping (everything is inlined, matching the base formatter).
    """

    max_bytes: int = Field(default=_MAX_INLINE_MEDIA_BYTES)

    @staticmethod
    def _inline_media_size(source: Any) -> int | None:
        """Return the byte size of *source* if it would be inlined locally.

        Returns ``None`` for remote URLs (not read from disk here) and for
        unrecognised source types so the caller leaves them untouched.
        """
        if isinstance(source, URLSource):
            url = str(source.url)
            if url.startswith("file://"):
                try:
                    return os.path.getsize(url.removeprefix("file://"))
                except OSError:
                    return None
            return None
        if isinstance(source, Base64Source):
            # base64 length -> approximate raw byte count.
            return len(source.data or "") * 3 // 4
        return None

    def _maybe_cap(self, source: Any, kind: str) -> dict[str, Any] | None:
        if self.max_bytes <= 0:
            return None
        size = self._inline_media_size(source)
        if size is None or size <= self.max_bytes:
            return None
        return {
            "type": "text",
            "text": (
                f"[{kind} omitted from model context: local file is "
                f"{size} bytes, exceeds inline limit of "
                f"{self.max_bytes} bytes]"
            ),
        }

    def _format_video_source(self, source: Any) -> dict[str, Any]:
        capped = self._maybe_cap(source, "video")
        if capped is not None:
            return capped
        return super()._format_video_source(source)

    def _format_image_source(self, source: Any) -> dict[str, Any]:
        capped = self._maybe_cap(source, "image")
        if capped is not None:
            return capped
        return super()._format_image_source(source)

    def _format_audio_source(self, source: Any) -> dict[str, Any]:
        capped = self._maybe_cap(source, "audio")
        if capped is not None:
            return capped
        return super()._format_audio_source(source)


class _DashScopeChatModelCompat:
    """Factory that creates a ``DashScopeChatModel`` subclass with custom
    tracking headers injected into every API call via ``extra_headers``.

    When ``thinking_explicitly_set`` is ``False`` the wrapper temporarily
    sets ``parameters.thinking_enable`` to ``None`` before calling the
    base ``_call_api``, so the ``is not None`` guard in
    ``DashScopeChatModel._call_api`` skips emitting ``enable_thinking``
    and the DashScope API uses its own model-level default.
    """

    def __new__(cls, **kwargs: Any) -> Any:
        from agentscope.model import DashScopeChatModel

        default_headers = kwargs.pop("default_headers", None)
        thinking_explicitly_set = kwargs.pop(
            "thinking_explicitly_set",
            True,
        )
        extra_generate_kwargs = kwargs.pop("extra_generate_kwargs", None)

        class _Compat(DashScopeChatModel):
            _qp_default_headers = default_headers
            _qp_thinking_explicit = thinking_explicitly_set
            _qp_extra_generate_kwargs = extra_generate_kwargs or {}

            async def _call_api(
                self,
                model_name,
                messages,
                tools=None,
                tool_choice=None,
                **extra_kwargs,
            ):
                if self._qp_extra_generate_kwargs:
                    extra_kwargs = {
                        **self._qp_extra_generate_kwargs,
                        **extra_kwargs,
                    }
                if self._qp_default_headers:
                    existing = extra_kwargs.get("extra_headers") or {}
                    extra_kwargs["extra_headers"] = {
                        **self._qp_default_headers,
                        **existing,
                    }

                # When the user never configured thinking, temporarily mask
                # the default ``False`` so the base class skips sending
                # ``enable_thinking`` to the API.
                #
                # Note: concurrent async calls may interleave the
                # save/mask/restore sequence, but the race is benign —
                # the masked value (``None``) is exactly what every call
                # in this branch needs, so the worst-case outcome is
                # ``thinking_enable`` staying at ``None`` between calls,
                # which still correctly suppresses ``enable_thinking``.
                if not self._qp_thinking_explicit:
                    saved = self.parameters.thinking_enable
                    self.parameters.__dict__["thinking_enable"] = None
                    try:
                        return await super()._call_api(
                            model_name,
                            messages,
                            tools,
                            tool_choice,
                            **extra_kwargs,
                        )
                    finally:
                        self.parameters.__dict__["thinking_enable"] = saved

                return await super()._call_api(
                    model_name,
                    messages,
                    tools,
                    tool_choice,
                    **extra_kwargs,
                )

        return _Compat(**kwargs)
