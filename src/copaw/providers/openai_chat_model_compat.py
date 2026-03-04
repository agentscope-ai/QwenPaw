# -*- coding: utf-8 -*-
"""OpenAI chat model compatibility wrappers."""

from __future__ import annotations

import json
import time
from datetime import datetime
from types import SimpleNamespace
from typing import Any, AsyncGenerator, Type
from urllib.parse import urlsplit, urlunsplit

from agentscope.model import OpenAIChatModel
from agentscope.model._model_response import ChatResponse
from agentscope.model._model_usage import ChatUsage
from pydantic import BaseModel


def _clone_with_overrides(obj: Any, **overrides: Any) -> Any:
    """Clone a stream object into a mutable namespace with overrides."""
    data = dict(getattr(obj, "__dict__", {}))
    data.update(overrides)
    return SimpleNamespace(**data)


def _sanitize_tool_call(tool_call: Any) -> Any | None:
    """Normalize a tool call for parser safety, or drop it if unusable."""
    if not hasattr(tool_call, "index"):
        return None

    function = getattr(tool_call, "function", None)
    if function is None:
        return None

    has_name = hasattr(function, "name")
    has_arguments = hasattr(function, "arguments")

    raw_name = getattr(function, "name", "")
    if isinstance(raw_name, str):
        safe_name = raw_name
    elif raw_name is None:
        safe_name = ""
    else:
        safe_name = str(raw_name)

    raw_arguments = getattr(function, "arguments", "")
    if isinstance(raw_arguments, str):
        safe_arguments = raw_arguments
    elif raw_arguments is None:
        safe_arguments = ""
    else:
        try:
            safe_arguments = json.dumps(raw_arguments, ensure_ascii=False)
        except (TypeError, ValueError):
            safe_arguments = str(raw_arguments)

    if (
        has_name
        and has_arguments
        and isinstance(raw_name, str)
        and isinstance(raw_arguments, str)
    ):
        return tool_call

    safe_function = SimpleNamespace(
        name=safe_name,
        arguments=safe_arguments,
    )
    return _clone_with_overrides(tool_call, function=safe_function)


def _sanitize_chunk(chunk: Any) -> Any:
    """Drop/normalize malformed tool-calls in a streaming chunk."""
    choices = getattr(chunk, "choices", None)
    if not choices:
        return chunk

    sanitized_choices: list[Any] = []
    changed = False

    for choice in choices:
        delta = getattr(choice, "delta", None)
        if delta is None:
            sanitized_choices.append(choice)
            continue

        raw_tool_calls = getattr(delta, "tool_calls", None)
        if not raw_tool_calls:
            sanitized_choices.append(choice)
            continue

        choice_changed = False
        sanitized_tool_calls: list[Any] = []
        for tool_call in raw_tool_calls:
            sanitized = _sanitize_tool_call(tool_call)
            if sanitized is not tool_call:
                choice_changed = True
            if sanitized is not None:
                sanitized_tool_calls.append(sanitized)

        if choice_changed:
            changed = True
            sanitized_delta = _clone_with_overrides(
                delta,
                tool_calls=sanitized_tool_calls,
            )
            sanitized_choice = _clone_with_overrides(
                choice,
                delta=sanitized_delta,
            )
            sanitized_choices.append(sanitized_choice)
            continue

        sanitized_choices.append(choice)

    if not changed:
        return chunk
    return _clone_with_overrides(chunk, choices=sanitized_choices)


def _sanitize_stream_item(item: Any) -> Any:
    """Sanitize either plain stream chunks or structured stream items."""
    if hasattr(item, "chunk"):
        chunk = item.chunk
        sanitized_chunk = _sanitize_chunk(chunk)
        if sanitized_chunk is chunk:
            return item
        return _clone_with_overrides(item, chunk=sanitized_chunk)

    return _sanitize_chunk(item)


def _ensure_v1_base_url(base_url: str) -> str:
    """Ensure base URL path ends with /v1 for Responses API."""
    parts = urlsplit(base_url)
    path = (parts.path or "").rstrip("/")
    if not path:
        path = "/v1"
    elif not path.endswith("/v1"):
        path = f"{path}/v1"
    return urlunsplit(
        (parts.scheme, parts.netloc, path, parts.query, parts.fragment),
    )


def _stringify_for_tool_output(value: Any) -> str:
    """Convert arbitrary tool output payload into a string."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        texts: list[str] = []
        for block in value:
            if isinstance(block, dict):
                if block.get("type") == "text":
                    text_val = block.get("text")
                    if isinstance(text_val, str):
                        texts.append(text_val)
                else:
                    try:
                        texts.append(json.dumps(block, ensure_ascii=False))
                    except (TypeError, ValueError):
                        texts.append(str(block))
            else:
                texts.append(str(block))
        return "\n".join(_ for _ in texts if _)
    try:
        return json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(value)


def _convert_openai_content_to_responses(
    content: Any,
    role: str | None = None,
) -> str | list[dict[str, Any]]:
    """Convert chat.completions content blocks to responses input blocks."""
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""

    out: list[dict[str, Any]] = []
    fallback_texts: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            fallback_texts.append(str(block))
            continue

        block_type = block.get("type")
        if block_type == "text":
            text_block_type = (
                "output_text" if role == "assistant" else "input_text"
            )
            out.append(
                {
                    "type": text_block_type,
                    "text": block.get("text", ""),
                },
            )
            continue

        if block_type == "image_url":
            if role == "assistant":
                try:
                    fallback_texts.append(json.dumps(block, ensure_ascii=False))
                except (TypeError, ValueError):
                    fallback_texts.append(str(block))
                continue
            image_url = block.get("image_url", {})
            url = image_url.get("url") if isinstance(image_url, dict) else ""
            if isinstance(url, str) and url:
                out.append(
                    {
                        "type": "input_image",
                        "image_url": url,
                    },
                )
            continue

        if block_type == "input_audio":
            if role == "assistant":
                try:
                    fallback_texts.append(json.dumps(block, ensure_ascii=False))
                except (TypeError, ValueError):
                    fallback_texts.append(str(block))
                continue
            input_audio = (
                block.get("input_audio", {})
                if isinstance(block.get("input_audio"), dict)
                else {}
            )
            out.append(
                {
                    "type": "input_audio",
                    "data": input_audio.get("data", ""),
                    "format": input_audio.get("format", ""),
                },
            )
            continue

        try:
            fallback_texts.append(json.dumps(block, ensure_ascii=False))
        except (TypeError, ValueError):
            fallback_texts.append(str(block))

    if out:
        return out
    return "\n".join(_ for _ in fallback_texts if _)


def _convert_messages_to_responses_input(
    messages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Convert chat.completions messages to responses input items."""
    input_items: list[dict[str, Any]] = []
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        role = msg.get("role")

        if role == "tool":
            call_id = (
                msg.get("tool_call_id")
                or msg.get("id")
                or "tool_call_unknown"
            )
            input_items.append(
                {
                    "type": "function_call_output",
                    "call_id": str(call_id),
                    "output": _stringify_for_tool_output(msg.get("content")),
                },
            )
            continue

        if role in {"system", "developer", "user", "assistant"}:
            converted_content = _convert_openai_content_to_responses(
                msg.get("content"),
                role=str(role),
            )
            if converted_content not in ("", [], None):
                input_items.append(
                    {
                        "role": role,
                        "content": converted_content,
                    },
                )

            if role == "assistant":
                for tool_call in msg.get("tool_calls", []) or []:
                    if not isinstance(tool_call, dict):
                        continue
                    function = tool_call.get("function", {})
                    if not isinstance(function, dict):
                        function = {}
                    call_id = tool_call.get("id") or "tool_call_unknown"
                    input_items.append(
                        {
                            "type": "function_call",
                            "call_id": str(call_id),
                            "name": str(function.get("name", "")),
                            "arguments": str(
                                function.get("arguments", "{}"),
                            ),
                        },
                    )
            continue

    return input_items


def _convert_tools_for_responses(tools: list[dict[str, Any]]) -> list[dict]:
    """Convert chat.completions tool schema to responses tool schema."""
    converted: list[dict] = []
    for tool in tools:
        if not isinstance(tool, dict):
            continue

        if (
            tool.get("type") == "function"
            and isinstance(tool.get("function"), dict)
        ):
            func = tool["function"]
            converted.append(
                {
                    "type": "function",
                    "name": func.get("name", ""),
                    "description": func.get("description", ""),
                    "parameters": func.get("parameters", {"type": "object"}),
                },
            )
            continue

        converted.append(tool)
    return converted


def _convert_tool_choice_for_responses(tool_choice: Any) -> Any:
    """Convert chat.completions tool_choice to responses format."""
    if (
        isinstance(tool_choice, dict)
        and tool_choice.get("type") == "function"
        and isinstance(tool_choice.get("function"), dict)
    ):
        function = tool_choice["function"]
        return {
            "type": "function",
            "name": function.get("name", ""),
        }
    return tool_choice


def _extract_text_from_response_output_item(item: dict[str, Any]) -> str:
    """Extract text from one responses output item."""
    content = item.get("content")
    if not isinstance(content, list):
        return ""

    texts: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        if block.get("type") in {"output_text", "text"}:
            text = block.get("text", "")
            if isinstance(text, str) and text:
                texts.append(text)
    return "\n".join(texts)


def _response_to_chat_response(
    response: Any,
    start_datetime: datetime,
) -> ChatResponse:
    """Convert responses API result to AgentScope ChatResponse."""
    if hasattr(response, "model_dump"):
        raw = response.model_dump()
    elif isinstance(response, dict):
        raw = response
    elif isinstance(response, str):
        raw = {
            "output": [
                {
                    "type": "message",
                    "content": [
                        {
                            "type": "output_text",
                            "text": response,
                        },
                    ],
                },
            ],
            "usage": {},
        }
    else:
        try:
            raw = dict(response)
        except Exception:
            raw = {
                "output": [
                    {
                        "type": "message",
                        "content": [
                            {
                                "type": "output_text",
                                "text": str(response),
                            },
                        ],
                    },
                ],
                "usage": {},
            }
    content_blocks: list[dict[str, Any]] = []

    for item in raw.get("output", []) or []:
        if not isinstance(item, dict):
            continue

        item_type = item.get("type")
        if item_type == "function_call":
            raw_args = item.get("arguments", "{}")
            if not isinstance(raw_args, str):
                try:
                    raw_args = json.dumps(raw_args, ensure_ascii=False)
                except (TypeError, ValueError):
                    raw_args = str(raw_args)
            try:
                parsed_args = json.loads(raw_args) if raw_args else {}
                if not isinstance(parsed_args, dict):
                    parsed_args = {}
            except json.JSONDecodeError:
                parsed_args = {}

            call_id = item.get("call_id") or item.get("id") or "tool_call"
            content_blocks.append(
                {
                    "type": "tool_use",
                    "id": str(call_id),
                    "name": str(item.get("name", "")),
                    "input": parsed_args,
                    "raw_input": raw_args,
                },
            )
            continue

        if item_type == "message":
            text = _extract_text_from_response_output_item(item)
            if text:
                content_blocks.append({"type": "text", "text": text})
            continue

    if not content_blocks:
        output_text = getattr(response, "output_text", "") or ""
        if not output_text and isinstance(raw, dict):
            maybe_text = raw.get("output_text", "")
            if isinstance(maybe_text, str):
                output_text = maybe_text
        if isinstance(output_text, str) and output_text:
            content_blocks.append({"type": "text", "text": output_text})

    usage = raw.get("usage", {}) if isinstance(raw.get("usage"), dict) else {}
    output_tokens = usage.get("output_tokens")
    if output_tokens is None:
        output_tokens = usage.get("completion_tokens", 0)
    input_tokens = usage.get("input_tokens")
    if input_tokens is None:
        input_tokens = usage.get("prompt_tokens", 0)

    parsed_usage = ChatUsage(
        input_tokens=int(input_tokens or 0),
        output_tokens=int(output_tokens or 0),
        time=max(time.time() - start_datetime.timestamp(), 0.0),
    )

    return ChatResponse(
        content=content_blocks,
        usage=parsed_usage,
        metadata=None,
    )


def _should_fallback_to_responses(exception: Exception) -> bool:
    """Detect backend errors indicating chat.completions incompatibility."""
    message = str(exception).lower()
    return (
        "unsupported legacy protocol" in message
        or "please use /v1/responses" in message
        or "your request was blocked" in message
    )


class _SanitizedStream:
    """Proxy OpenAI async stream that sanitizes each emitted item."""

    def __init__(self, stream: Any):
        self._stream = stream
        self._ctx_stream: Any | None = None

    async def __aenter__(self) -> "_SanitizedStream":
        self._ctx_stream = await self._stream.__aenter__()
        return self

    async def __aexit__(
        self,
        exc_type: Any,
        exc: Any,
        tb: Any,
    ) -> bool | None:
        return await self._stream.__aexit__(exc_type, exc, tb)

    def __aiter__(self) -> "_SanitizedStream":
        return self

    async def __anext__(self) -> Any:
        if self._ctx_stream is None:
            raise StopAsyncIteration
        item = await self._ctx_stream.__anext__()
        return _sanitize_stream_item(item)


class OpenAIChatModelCompat(OpenAIChatModel):
    """OpenAIChatModel with robust parsing for malformed tool-call chunks."""

    async def __call__(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        tool_choice: str | dict | None = None,
        structured_model: Type[BaseModel] | None = None,
        **kwargs: Any,
    ) -> ChatResponse | AsyncGenerator[ChatResponse, None]:
        """Call chat.completions first, fallback to responses on incompatibility."""
        try:
            return await super().__call__(
                messages=messages,
                tools=tools,
                tool_choice=tool_choice,
                structured_model=structured_model,
                **kwargs,
            )
        except Exception as exc:
            if structured_model is not None or not _should_fallback_to_responses(
                exc,
            ):
                raise

            base_url = _ensure_v1_base_url(str(self.client.base_url))
            client = self.client.with_options(base_url=base_url)
            start_datetime = datetime.now()

            request: dict[str, Any] = {
                "model": self.model_name,
                "input": _convert_messages_to_responses_input(messages),
            }
            if not request["input"]:
                request["input"] = [{"role": "user", "content": ""}]

            if tools:
                request["tools"] = _convert_tools_for_responses(tools)
            if tool_choice:
                request["tool_choice"] = _convert_tool_choice_for_responses(
                    tool_choice,
                )

            if "temperature" in kwargs:
                request["temperature"] = kwargs["temperature"]
            if "top_p" in kwargs:
                request["top_p"] = kwargs["top_p"]
            if "max_output_tokens" in kwargs:
                request["max_output_tokens"] = kwargs["max_output_tokens"]
            elif "max_tokens" in kwargs:
                request["max_output_tokens"] = kwargs["max_tokens"]

            response = await client.responses.create(**request)
            parsed = _response_to_chat_response(response, start_datetime)

            if self.stream:

                async def _single_chunk_stream() -> AsyncGenerator[
                    ChatResponse,
                    None,
                ]:
                    yield parsed

                return _single_chunk_stream()

            return parsed

    async def _parse_openai_stream_response(
        self,
        start_datetime: datetime,
        response: Any,
        structured_model: Type[BaseModel] | None = None,
    ) -> AsyncGenerator[ChatResponse, None]:
        sanitized_response = _SanitizedStream(response)
        async for parsed in super()._parse_openai_stream_response(
            start_datetime=start_datetime,
            response=sanitized_response,
            structured_model=structured_model,
        ):
            yield parsed
