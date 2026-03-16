# -*- coding: utf-8 -*-
"""Chat model adapter for Codex ChatGPT auth."""

from __future__ import annotations

import json
import logging
import time
from copy import deepcopy
from datetime import datetime
from typing import Any, AsyncGenerator, Literal, Type

import httpx
from pydantic import BaseModel

from agentscope.model import OpenAIChatModel
from agentscope.model._model_response import ChatResponse, ChatUsage
from agentscope.model._model_response import TextBlock, ToolUseBlock

from .auth_helper_registry import refresh_provider_auth
from .provider import Provider

logger = logging.getLogger(__name__)


def _safe_json_loads(raw: str) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


class CodexResponsesChatModel(OpenAIChatModel):
    """Use ChatGPT-backed Codex responses endpoint as a chat model."""

    def __init__(
        self,
        model_name: str,
        access_token: str,
        account_id: str,
        base_url: str = "https://chatgpt.com/backend-api/codex",
        stream: bool = True,
        generate_kwargs: dict[str, Any] | None = None,
        provider: Provider | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            model_name=model_name,
            api_key="unused",
            stream=stream,
            generate_kwargs=generate_kwargs,
            **kwargs,
        )
        self.base_url = base_url.rstrip("/")
        self.provider = provider
        self.access_token = access_token
        self.account_id = account_id
        self.http = httpx.AsyncClient(timeout=120)
        self._closed = False

    async def __call__(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        tool_choice: Literal["auto", "none", "required"] | str | None = None,
        structured_model: Type[BaseModel] | None = None,
        **kwargs: Any,
    ) -> ChatResponse | AsyncGenerator[ChatResponse, None]:
        if structured_model is not None:
            raise NotImplementedError(
                "Structured output is not supported for Codex browser auth yet.",
            )

        await self._refresh_auth_if_needed()
        payload = self._build_payload(messages, tools, tool_choice, **kwargs)
        start_time = time.monotonic()
        if self.stream:
            return self._stream_response(payload, start_time)
        return await self._collect_response(payload, start_time)

    def _build_payload(
        self,
        messages: list[dict],
        tools: list[dict] | None,
        tool_choice: Literal["auto", "none", "required"] | str | None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        instructions, input_items = self._convert_messages(messages)
        payload: dict[str, Any] = {
            "model": self.model_name,
            "instructions": instructions or "You are a helpful assistant.",
            "input": input_items,
            "stream": True,
            "store": False,
            **self.generate_kwargs,
            **kwargs,
        }
        if tools:
            payload["tools"] = self._format_codex_tools(tools)
        if tool_choice:
            self._validate_tool_choice(tool_choice, tools)
            payload["tool_choice"] = self._format_codex_tool_choice(
                tool_choice,
            )
        return payload

    @staticmethod
    def _format_codex_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Convert Chat Completions-style tool schemas to Codex Responses."""
        formatted_tools: list[dict[str, Any]] = []
        for tool in tools:
            if not isinstance(tool, dict):
                continue
            if tool.get("type") != "function":
                formatted_tools.append(deepcopy(tool))
                continue

            function = tool.get("function") or {}
            if not isinstance(function, dict):
                continue

            formatted_tool = {
                "type": "function",
                "name": function.get("name") or "",
                "description": function.get("description") or "",
                "parameters": function.get("parameters")
                or {"type": "object", "properties": {}},
            }

            strict = function.get("strict")
            if strict is not None:
                formatted_tool["strict"] = strict

            formatted_tools.append(formatted_tool)

        return formatted_tools

    @staticmethod
    def _format_codex_tool_choice(
        tool_choice: Literal["auto", "none", "required"] | str,
    ) -> str | dict[str, Any]:
        """Codex Responses expects specific-function tool choice at top level."""
        if tool_choice in {"auto", "none", "required"}:
            return tool_choice
        return {
            "type": "function",
            "name": tool_choice,
        }

    def _convert_messages(
        self,
        messages: list[dict],
    ) -> tuple[str, list[dict[str, Any]]]:
        instructions: list[str] = []
        input_items: list[dict[str, Any]] = []

        for message in messages:
            role = message.get("role", "user")
            if role == "tool":
                tool_output = message.get("content") or ""
                input_items.append(
                    {
                        "type": "function_call_output",
                        "call_id": message.get("tool_call_id"),
                        "output": tool_output,
                    },
                )
                continue

            content_blocks = message.get("content") or []
            if isinstance(content_blocks, str):
                content_blocks = [
                    {
                        "type": "text",
                        "text": content_blocks,
                    },
                ]

            if role == "system":
                for block in content_blocks:
                    text = block.get("text")
                    if isinstance(text, str) and text:
                        instructions.append(text)
                continue

            response_content: list[dict[str, Any]] = []
            for block in content_blocks:
                block_type = block.get("type")
                if block_type == "text":
                    text_type = (
                        "output_text" if role == "assistant" else "input_text"
                    )
                    response_content.append(
                        {
                            "type": text_type,
                            "text": block.get("text", ""),
                        },
                    )
                elif block_type == "image_url":
                    image_url = (block.get("image_url") or {}).get("url")
                    if image_url:
                        response_content.append(
                            {
                                "type": "input_image",
                                "image_url": image_url,
                            },
                        )

            if response_content:
                input_items.append(
                    {
                        "type": "message",
                        "role": role,
                        "content": response_content,
                    },
                )

            for tool_call in message.get("tool_calls") or []:
                function = tool_call.get("function") or {}
                input_items.append(
                    {
                        "type": "function_call",
                        "call_id": tool_call.get("id"),
                        "name": function.get("name"),
                        "arguments": function.get("arguments") or "{}",
                    },
                )

        return "\n\n".join(part for part in instructions if part).strip(), input_items

    async def _collect_response(
        self,
        payload: dict[str, Any],
        start_time: float,
    ) -> ChatResponse:
        final_response: ChatResponse | None = None
        async for chunk in self._stream_response(payload, start_time):
            final_response = chunk
        if final_response is None:
            raise RuntimeError("Codex response stream ended without data")
        return final_response

    async def _stream_response(
        self,
        payload: dict[str, Any],
        start_time: float,
    ) -> AsyncGenerator[ChatResponse, None]:
        text = ""
        tool_calls: dict[str, dict[str, Any]] = {}
        usage: ChatUsage | None = None
        completed = False

        async with self.http.stream(
            "POST",
            f"{self.base_url}/responses",
            headers={
                "Authorization": f"Bearer {self.access_token}",
                "ChatGPT-Account-Id": self.account_id,
                "User-Agent": "codex-cli",
                "Accept": "text/event-stream",
                "Content-Type": "application/json",
            },
            json=payload,
        ) as response:
            if response.status_code >= 400:
                raw_error = (await response.aread()).decode(
                    "utf-8",
                    "replace",
                )
                raise httpx.HTTPStatusError(
                    f"{response.status_code} error from Codex responses API: "
                    f"{raw_error[:500] or response.reason_phrase}",
                    request=response.request,
                    response=response,
                )
            event_name = ""
            data_lines: list[str] = []
            async for line in response.aiter_lines():
                if line == "":
                    maybe_chunk = self._consume_sse_event(
                        event_name,
                        data_lines,
                        text,
                        tool_calls,
                        start_time,
                    )
                    if maybe_chunk is not None:
                        text, usage, chunk, completed = maybe_chunk
                        yield chunk
                    event_name = ""
                    data_lines = []
                    continue
                if line.startswith("event: "):
                    event_name = line[len("event: ") :]
                elif line.startswith("data: "):
                    data_lines.append(line[len("data: ") :])

        if (text or tool_calls) and not completed:
            yield self._build_chat_response(text, tool_calls, usage, start_time)

    def _consume_sse_event(
        self,
        event_name: str,
        data_lines: list[str],
        text: str,
        tool_calls: dict[str, dict[str, Any]],
        start_time: float,
    ) -> tuple[str, ChatUsage | None, ChatResponse, bool] | None:
        if not event_name or not data_lines:
            return None
        try:
            payload = json.loads("\n".join(data_lines))
        except json.JSONDecodeError:
            return None

        usage: ChatUsage | None = None
        if event_name == "response.output_text.delta":
            text += payload.get("delta") or ""
            return (
                text,
                usage,
                self._build_chat_response(text, tool_calls, usage, start_time),
                False,
            )

        if event_name == "response.output_item.added":
            item = payload.get("item") or {}
            if item.get("type") == "function_call":
                tool_calls[item["id"]] = {
                    "type": "tool_use",
                    "id": item.get("call_id") or item.get("id"),
                    "name": item.get("name") or "",
                    "input": {},
                    "raw_input": "",
                }
            return None

        if event_name == "response.function_call_arguments.delta":
            item_id = payload.get("item_id")
            if item_id in tool_calls:
                tool_calls[item_id]["raw_input"] = (
                    tool_calls[item_id].get("raw_input", "") + (payload.get("delta") or "")
                )
            return None

        if event_name in {
            "response.function_call_arguments.done",
            "response.output_item.done",
        }:
            item_id = payload.get("item_id")
            item = payload.get("item") or {}
            if item.get("type") == "function_call":
                item_id = item.get("id") or item_id
                raw_input = item.get("arguments") or ""
                if item_id in tool_calls:
                    tool_calls[item_id]["raw_input"] = raw_input
                    tool_calls[item_id]["input"] = _safe_json_loads(raw_input)
                    return (
                        text,
                        usage,
                        self._build_chat_response(text, tool_calls, usage, start_time),
                        False,
                    )
            elif item_id in tool_calls:
                raw_input = payload.get("arguments") or tool_calls[item_id].get(
                    "raw_input",
                    "",
                )
                tool_calls[item_id]["raw_input"] = raw_input
                tool_calls[item_id]["input"] = _safe_json_loads(raw_input)
                return (
                    text,
                    usage,
                    self._build_chat_response(text, tool_calls, usage, start_time),
                    False,
                )
            return None

        if event_name == "response.completed":
            response_payload = payload.get("response") or {}
            raw_usage = response_payload.get("usage") or {}
            if raw_usage:
                usage = ChatUsage(
                    input_tokens=int(raw_usage.get("input_tokens") or 0),
                    output_tokens=int(raw_usage.get("output_tokens") or 0),
                    time=time.monotonic() - start_time,
                    metadata=raw_usage,
                )
            return (
                text,
                usage,
                self._build_chat_response(text, tool_calls, usage, start_time),
                True,
            )

        return None

    async def _refresh_auth_if_needed(self) -> None:
        if self.provider is None:
            return
        await refresh_provider_auth(
            self.provider,
            lambda current: current.persist(),
        )
        self.access_token = self.provider.auth.access_token
        self.account_id = self.provider.auth.account_id

    async def aclose(self) -> None:
        """Close the underlying HTTP client."""
        if self._closed:
            return
        await self.http.aclose()
        self._closed = True

    async def __aenter__(self) -> "CodexResponsesChatModel":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.aclose()

    @staticmethod
    def _build_chat_response(
        text: str,
        tool_calls: dict[str, dict[str, Any]],
        usage: ChatUsage | None,
        start_time: float,
    ) -> ChatResponse:
        content: list[TextBlock | ToolUseBlock] = []
        if text:
            content.append(
                TextBlock(
                    type="text",
                    text=text,
                ),
            )
        for tool in tool_calls.values():
            content.append(
                ToolUseBlock(
                    type="tool_use",
                    id=str(tool.get("id") or ""),
                    name=str(tool.get("name") or ""),
                    input=tool.get("input") or {},
                    raw_input=str(tool.get("raw_input") or ""),
                ),
            )
        if usage is None:
            usage = ChatUsage(
                input_tokens=0,
                output_tokens=0,
                time=time.monotonic() - start_time,
            )
        return ChatResponse(content=content, usage=usage)
