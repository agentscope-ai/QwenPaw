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

import logging
from typing import Any, Dict

from agentscope.model import ChatModelBase
from pydantic import Field

from .openai_provider import OpenAIProvider

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
        # 2.0 Parameters: only the fields declared on
        # DashScopeChatModel.Parameters are accepted.  Pop the known ones,
        # drop anything else (the remainder were aimed at the 1.x
        # ``generate_kwargs`` passthrough, which is gone).
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

        return DashScopeChatModel(
            credential=credential,
            model=model_id,
            parameters=DashScopeChatModel.Parameters(**param_kwargs),
            stream=True,
        )
