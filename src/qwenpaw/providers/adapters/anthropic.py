# -*- coding: utf-8 -*-
"""AgentScope Anthropic model with QwenPaw request policy."""

from datetime import datetime
from typing import Any, Dict

import anthropic
from agentscope.model import AnthropicChatModel

from .cache_policy import mark_stable_prefix
from .wire_protocol import anthropic_base_url


def resolve_parameters(
    generate_kwargs: dict,
    output_capacity: int | None,
) -> tuple[AnthropicChatModel.Parameters, dict]:
    """Resolve model parameters without constructing a client."""
    extra = dict(generate_kwargs)
    default_output = (
        min(16_384, output_capacity) if output_capacity else 16_384
    )
    max_tokens = extra.pop(f"max_tokens", None)
    max_tokens = default_output if max_tokens is None else max_tokens
    if output_capacity and max_tokens > output_capacity:
        raise ValueError(
            f"Output limit exceeds model capacity {output_capacity}",
        )
    params = {f"max_tokens": max_tokens}
    for key in (f"thinking_enable", f"thinking_budget"):
        if key in extra:
            params[key] = extra.pop(key)
    return AnthropicChatModel.Parameters(**params), extra


def resolve_request_parameters(
    parameters: AnthropicChatModel.Parameters,
    generate_kwargs: dict,
) -> dict:
    """Share thinking defaults between request serialization and display."""
    extra = dict(generate_kwargs)
    if extra.pop(f"disable_thinking", False):
        extra[f"thinking"] = {f"type": f"disabled"}
    max_tokens = parameters.max_tokens or 8192
    result = {f"max_tokens": max_tokens, **extra}
    if parameters.thinking_enable and f"thinking" not in result:
        budget = parameters.thinking_budget or (max_tokens // 2)
        if budget >= max_tokens:
            result[f"max_tokens"] = budget + 1024
        result[f"thinking"] = {
            f"type": f"enabled",
            f"budget_tokens": budget,
        }
    return result


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
        kw: Dict[str, Any] = {
            f"model": model_name,
            f"stream": self.stream,
            **resolve_request_parameters(self.parameters, generate_kwargs),
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
