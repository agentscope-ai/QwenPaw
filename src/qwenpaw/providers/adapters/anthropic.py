# -*- coding: utf-8 -*-
"""AgentScope Anthropic model with QwenPaw request policy."""

from datetime import datetime
from typing import Any, Dict

import anthropic
from agentscope.model import AnthropicChatModel

from .cache_policy import mark_stable_prefix
from .wire_protocol import anthropic_base_url


async def strip_api_key_header(request: Any) -> None:
    """Keep bearer authentication exclusive on the SDK transport."""
    request.headers.pop(f"x-api-key", None)


class AnthropicModel(AnthropicChatModel):
    """Own credentials, headers and protocol policy per model instance."""

    def __init__(self, **kwargs: Any) -> None:
        self._qp_output_capacity = kwargs.pop(f"output_capacity", None)
        self._qp_default_headers = kwargs.pop(f"default_headers", None)
        self._qp_auth_mode = kwargs.pop(f"auth_mode", None)
        self._request_policy = kwargs.pop(f"request_policy", None)
        self._extra_generate_kwargs = (
            kwargs.pop(
                f"extra_generate_kwargs",
                {},
            )
            or {}
        )
        self._qp_cached_client = None
        self._qp_cached_client_key = ()
        super().__init__(**kwargs)

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
            and not self._qp_cached_client.is_closed()
        ):
            return self._qp_cached_client

        client_kwargs: Dict[str, Any] = {
            "base_url": anthropic_base_url(self.credential.base_url),
        }
        if self._qp_default_headers:
            client_kwargs["default_headers"] = self._qp_default_headers
        if self._qp_auth_mode == "auth_token":
            client_kwargs[
                "auth_token"
            ] = self.credential.api_key.get_secret_value()
            client_kwargs[f"http_client"] = anthropic.DefaultAsyncHttpxClient(
                event_hooks={f"request": [strip_api_key_header]},
            )
        else:
            client_kwargs[
                "api_key"
            ] = self.credential.api_key.get_secret_value()

        self._qp_cached_client = anthropic.AsyncAnthropic(
            **client_kwargs,
        )
        self._qp_cached_client_key = key
        return self._qp_cached_client

    async def _request_client(self):
        """Close the old transport when credentials replace the client."""
        previous_client = self._qp_cached_client
        client = self._get_or_create_client()
        if previous_client is not None and previous_client is not client:
            await previous_client.close()
        return client

    async def _call_api(
        self,
        model_name,
        messages,
        tools=None,
        tool_choice=None,
        **generate_kwargs,
    ):
        generate_kwargs = {
            **self._extra_generate_kwargs,
            **generate_kwargs,
        }
        explicit_cache = generate_kwargs.get(
            f"enable_prompt_cache_breakpoint",
            False,
        )
        if self._request_policy is not None:
            generate_kwargs = self._request_policy(
                model_name,
                f"anthropic",
                generate_kwargs,
            )
        # Translate the neutral ``disable_thinking`` flag
        if generate_kwargs.pop("disable_thinking", False):
            generate_kwargs["thinking"] = {"type": "disabled"}

        max_tokens = self.parameters.max_tokens or 8192
        kw: Dict[str, Any] = {
            "model": model_name,
            "max_tokens": max_tokens,
            "stream": self.stream,
            **generate_kwargs,
        }
        if self.parameters.thinking_enable and "thinking" not in kw:
            budget = self.parameters.thinking_budget or (max_tokens // 2)
            if budget >= max_tokens:
                max_tokens = budget + 1024
                kw["max_tokens"] = max_tokens
            kw["thinking"] = {
                "type": "enabled",
                "budget_tokens": budget,
            }

        capacity = self._qp_output_capacity
        if capacity and kw[f"max_tokens"] > capacity:
            raise ValueError(
                f"Output and thinking budget exceed model capacity "
                f"{capacity}",
            )

        fmt_tools, fmt_tc = self._format_tools(tools, tool_choice)
        if fmt_tools:
            kw["tools"] = fmt_tools
        if fmt_tc is not None:
            kw["tool_choice"] = fmt_tc

        formatted = await self.formatter.format(messages)
        if explicit_cache:
            formatted = mark_stable_prefix(formatted, responses=False)
        if formatted and formatted[0]["role"] == "system":
            kw["system"] = formatted[0]["content"]
            formatted = formatted[1:]
        kw["messages"] = formatted

        client = await self._request_client()
        start = datetime.now()
        response = None
        try:
            response = await client.messages.create(**kw)
            if self.stream:
                return self._owned_stream(start, response, client)
            return await self._parse_anthropic_completion_response(
                start,
                response,
            )
        finally:
            if self._qp_auth_mode == f"auth_token" and (
                not self.stream or response is None
            ):
                await client.close()

    async def _owned_stream(self, start, response, client):
        """Keep the model-owned transport alive until streaming finishes."""
        try:
            chunks = self._parse_anthropic_stream_completion_response(
                start,
                response,
            )
            async for chunk in chunks:
                yield chunk
        finally:
            if self._qp_auth_mode == f"auth_token":
                await client.close()
