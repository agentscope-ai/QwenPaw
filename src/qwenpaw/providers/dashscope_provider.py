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
from typing import Any, Dict

from agentscope.model import ChatModelBase
from pydantic import Field

from .capping_formatter import MAX_INLINE_MEDIA_BYTES
from .capping_formatter import _CappingDashScopeFormatter
from .openai_provider import (
    CODING_DASHSCOPE_BASE_URL,
    DASHSCOPE_BASE_URLS,
    TOKEN_PLAN_BASE_URL,
    OpenAIProvider,
)

logger = logging.getLogger(__name__)


class DashScopeProvider(OpenAIProvider):
    """Provider that wires the builtin DashScope endpoint to 2.0 native
    ``DashScopeChatModel``."""

    chat_model: str = Field(default="DashScopeChatModel")
    thinking_param_style: str = Field(default="budget")

    max_inline_media_bytes: int = Field(
        default=MAX_INLINE_MEDIA_BYTES,
        ge=0,
        description=(
            "Maximum size (in bytes) of a local media file inlined as "
            "base64 into the model request body. Media above this is "
            "replaced with a text placeholder to avoid oversized requests "
            "when large files (e.g. generated videos) persist in "
            "conversation history. 0 disables capping."
        ),
    )

    def _is_builtin_model(self, model_id: str) -> bool:
        return any(m.id == model_id for m in self.models)

    def _apply_thinking_config(
        self,
        model_id: str,
        effective: dict,
    ) -> None:
        if not self._is_builtin_model(model_id):
            return
        enabled, budget, effort = self._get_thinking_config(model_id)

        # Resolve the effective thinking_param_style for this model:
        # model-level override takes precedence over the provider default.
        model_info = self.get_model_info(model_id)
        param_style = (
            model_info.thinking_param_style
            if model_info and model_info.thinking_param_style
            else self.thinking_param_style
        )

        if param_style == "effort":
            # Effort-style models (e.g. GLM-5.2) pass both ``thinking`` and
            # ``reasoning_effort`` inside ``extra_body`` (OpenAI-compat path).
            # They do NOT support ``enable_thinking`` (Qwen-style parameter).
            eb = effective.setdefault("extra_body", {})
            if not isinstance(eb, dict):
                eb = {}
                effective["extra_body"] = eb
            if enabled is True:
                eb.setdefault("thinking", {"type": "enabled"})
            elif enabled is False:
                eb.setdefault("thinking", {"type": "disabled"})
            if effort is not None:
                eb.setdefault("reasoning_effort", effort)
            return

        # Budget-style (default for DashScope Qwen models).
        eb = effective.get("extra_body")
        eb = eb if isinstance(eb, dict) else {}
        if enabled is not None:
            if (
                "thinking_enable" not in effective
                and "enable_thinking" not in eb
            ):
                effective["thinking_enable"] = enabled
        if enabled is False:
            return
        if budget is not None:
            if (
                "thinking_budget" not in effective
                and "thinking_budget" not in eb
            ):
                effective["thinking_budget"] = budget
        if effort is not None:
            effective.setdefault("reasoning_effort", effort)

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
        self._apply_thinking_config(model_id, effective)

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
                relay_reasoning_content=self._get_preserve_thinking(model_id),
            ),
        )


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
                # Translate the neutral ``disable_thinking`` flag
                if extra_kwargs.pop("disable_thinking", False):
                    body = dict(extra_kwargs.get("extra_body") or {})
                    body.update(
                        {
                            "enable_thinking": False,
                            "thinking": {"type": "disabled"},
                        },
                    )
                    extra_kwargs["extra_body"] = body

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
