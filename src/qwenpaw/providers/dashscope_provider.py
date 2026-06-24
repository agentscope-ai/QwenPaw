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
        param_kwargs: Dict[str, Any] = {}
        for key in (
            "max_tokens",
            "thinking_enable",
            "thinking_budget",
            "temperature",
            "top_p",
            "top_k",
            "parallel_tool_calls",
        ):
            if key in effective:
                param_kwargs[key] = effective[key]

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
        )


class _DashScopeChatModelCompat:
    """Factory that creates a ``DashScopeChatModel`` subclass with custom
    tracking headers injected into every API call via ``extra_headers``."""

    def __new__(cls, **kwargs: Any) -> Any:
        from agentscope.model import DashScopeChatModel

        default_headers = kwargs.pop("default_headers", None)

        class _Compat(DashScopeChatModel):
            _qp_default_headers = default_headers

            async def _call_api(
                self,
                model_name,
                messages,
                tools=None,
                tool_choice=None,
                **extra_kwargs,
            ):
                if self._qp_default_headers:
                    existing = extra_kwargs.get("extra_headers") or {}
                    extra_kwargs["extra_headers"] = {
                        **self._qp_default_headers,
                        **existing,
                    }
                return await super()._call_api(
                    model_name,
                    messages,
                    tools,
                    tool_choice,
                    **extra_kwargs,
                )

        return _Compat(**kwargs)
