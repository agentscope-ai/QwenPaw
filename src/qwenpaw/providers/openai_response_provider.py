# -*- coding: utf-8 -*-
"""An OpenAI Responses API provider implementation."""

from __future__ import annotations

import logging
from typing import Any

from agentscope.model import ChatModelBase, OpenAIResponseModel

from qwenpaw.providers.openai_provider import OpenAIProvider

logger = logging.getLogger(__name__)


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
        merged = {**self._extra_generate_kwargs, **generate_kwargs}
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
    """Provider that uses the OpenAI Responses API instead of Chat Completions.

    Inherits connection/discovery logic from ``OpenAIProvider`` but
    creates ``OpenAIResponseModel`` instances via ``get_chat_model_instance``.
    The ``check_model_connection`` method uses the Responses API endpoint.

    Multimodal probing (``_probe_image_support`` / ``_probe_video_support``)
    is inherited from ``OpenAIProvider`` and uses the Chat Completions
    endpoint.  This works for OpenAI (which supports both APIs) and fails
    gracefully (returns "probe inconclusive") for third-party providers
    that only expose the Response API.
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
        )
