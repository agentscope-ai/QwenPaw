# -*- coding: utf-8 -*-
# pylint:disable=too-many-branches,too-many-statements
"""LocalChatModel — ChatModelBase implementation for local backends."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from typing import Any, AsyncGenerator, Literal, Optional, Type

from pydantic import BaseModel

from agentscope.model._model_base import ChatModelBase
from agentscope.model._model_response import ChatResponse
from agentscope.model._model_usage import ChatUsage
from agentscope.message import TextBlock, ToolUseBlock, ThinkingBlock

from .backends.base import LocalBackend
from .tag_parser import (
    extract_thinking_from_text,
    parse_tool_calls_from_text,
    text_contains_think_tag,
    text_contains_tool_call_tag,
)

logger = logging.getLogger(__name__)


def _json_loads_safe(s: str) -> dict:
    """Safely parse JSON string, returning empty dict on failure."""
    try:
        return json.loads(s)
    except (json.JSONDecodeError, TypeError):
        return {}


class LocalChatModel(ChatModelBase):
    """ChatModelBase implementation for local model backends.

    Wraps any ``LocalBackend`` (llama.cpp, future MLX) and presents it
    through the agentscope ``ChatModelBase`` interface.  Since backends are
    synchronous, inference runs in a thread executor for async compatibility.
    """

    def __init__(
        self,
        model_name: str,
        backend: LocalBackend,
        stream: bool = True,
        generate_kwargs: Optional[dict[str, Any]] = None,
    ) -> None:
        super().__init__(model_name, stream)
        self._backend = backend
        self._generate_kwargs = generate_kwargs or {}

    async def __call__(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        tool_choice: Literal["auto", "none", "required"] | str | None = None,
        structured_model: Type[BaseModel] | None = None,
        **kwargs: Any,
    ) -> ChatResponse | AsyncGenerator[ChatResponse, None]:
        merged_kwargs = {**self._generate_kwargs, **kwargs}
        start_datetime = datetime.now()

        if self.stream and not structured_model:
            return self._stream_response(
                messages,
                tools,
                tool_choice,
                start_datetime,
                **merged_kwargs,
            )

        # Non-streaming or structured output: run in thread
        loop = asyncio.get_running_loop()
        response = await loop.run_in_executor(
            None,
            lambda: self._backend.chat_completion(
                messages=messages,
                tools=tools,
                tool_choice=tool_choice,
                structured_model=structured_model,
                **merged_kwargs,
            ),
        )
        return self._parse_completion_response(
            response,
            start_datetime,
            structured_model,
        )

    async def _stream_response(
        self,
        messages: list[dict],
        tools: list[dict] | None,
        tool_choice: str | None,
        start_datetime: datetime,
        **kwargs: Any,
    ) -> AsyncGenerator[ChatResponse, None]:
        """Wrap synchronous streaming iterator as async generator.

        Uses a background thread to drive the synchronous iterator and
        feeds chunks through an ``asyncio.Queue``.
        """
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue = asyncio.Queue()
        _SENTINEL = object()

        def _produce() -> None:
            try:
                for chunk in self._backend.chat_completion_stream(
                    messages=messages,
                    tools=tools,
                    tool_choice=tool_choice,
                    **kwargs,
                ):
                    loop.call_soon_threadsafe(queue.put_nowait, chunk)
            except Exception as exc:
                loop.call_soon_threadsafe(queue.put_nowait, exc)
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, _SENTINEL)

        loop.run_in_executor(None, _produce)

        accumulated_text = ""
        accumulated_thinking = ""
        tool_calls: dict[int, dict] = {}

        while True:
            item = await queue.get()
            if item is _SENTINEL:
                break
            if isinstance(item, Exception):
                raise item

            chunk = item
            choices = chunk.get("choices", [])
            if not choices:
                continue

            delta = choices[0].get("delta", {})

            # Accumulate text
            content_piece = delta.get("content") or ""
            accumulated_text += content_piece

            # Accumulate reasoning/thinking content
            thinking_piece = delta.get("reasoning_content") or ""
            accumulated_thinking += thinking_piece

            # Handle tool calls in delta
            for tc in delta.get("tool_calls") or []:
                idx = tc.get("index", 0)
                if idx not in tool_calls:
                    tool_calls[idx] = {
                        "id": tc.get("id", f"call_{idx}"),
                        "name": (tc.get("function") or {}).get("name", ""),
                        "arguments": "",
                    }
                tool_calls[idx]["arguments"] += (tc.get("function") or {}).get(
                    "arguments",
                ) or ""

            # Build content blocks
            contents: list = []

            # Determine effective thinking and display text.
            # If the backend provides structured reasoning_content we use
            # that; otherwise fall back to extracting <think> tags from
            # the accumulated text.
            effective_thinking = accumulated_thinking
            effective_text = accumulated_text

            if (
                not effective_thinking
                and effective_text
                and text_contains_think_tag(effective_text)
            ):
                parsed_thinking = extract_thinking_from_text(effective_text)
                effective_thinking = parsed_thinking.thinking
                effective_text = parsed_thinking.remaining_text
                # If <think> is still open, suppress all text output
                # (thinking is still streaming).
                if parsed_thinking.has_open_tag:
                    effective_text = ""

            if effective_thinking:
                contents.append(
                    ThinkingBlock(
                        type="thinking",
                        thinking=effective_thinking,
                    ),
                )

            # Fallback: parse <tool_call> tags from effective text when
            # the backend doesn't provide structured tool_calls.
            if (
                not tool_calls
                and effective_text
                and text_contains_tool_call_tag(effective_text)
            ):
                parsed = parse_tool_calls_from_text(effective_text)
                display_text = parsed.text_before
                if parsed.text_after:
                    display_text = (
                        f"{display_text}\n{parsed.text_after}".strip()
                        if display_text
                        else parsed.text_after
                    )
                if display_text:
                    contents.append(
                        TextBlock(type="text", text=display_text),
                    )
                for ptc in parsed.tool_calls:
                    contents.append(
                        ToolUseBlock(
                            type="tool_use",
                            id=ptc.id,
                            name=ptc.name,
                            input=ptc.arguments,
                            raw_input=ptc.raw_arguments,
                        ),
                    )
            elif effective_text:
                contents.append(
                    TextBlock(type="text", text=effective_text),
                )

            for tc_data in tool_calls.values():
                contents.append(
                    ToolUseBlock(
                        type="tool_use",
                        id=tc_data["id"],
                        name=tc_data["name"],
                        input=_json_loads_safe(tc_data["arguments"]),
                        raw_input=tc_data["arguments"],
                    ),
                )

            usage_raw = chunk.get("usage")
            elapsed = (datetime.now() - start_datetime).total_seconds()
            usage = (
                ChatUsage(
                    input_tokens=usage_raw.get("prompt_tokens", 0),
                    output_tokens=usage_raw.get("completion_tokens", 0),
                    time=elapsed,
                )
                if usage_raw
                else None
            )

            if contents:
                yield ChatResponse(content=contents, usage=usage)

    def _parse_completion_response(
        self,
        response: dict,
        start_datetime: datetime,
        structured_model: Type[BaseModel] | None = None,
    ) -> ChatResponse:
        """Parse a non-streaming response dict into ChatResponse."""
        content_blocks: list = []
        metadata = None

        choices = response.get("choices", [])
        if choices:
            message = choices[0].get("message", {})

            # Reasoning/thinking content
            thinking = message.get("reasoning_content") or ""
            text = message.get("content") or ""

            # Fallback: if backend didn't return structured
            # reasoning_content but the text contains <think> tags,
            # extract them.
            if not thinking and text and text_contains_think_tag(text):
                parsed_thinking = extract_thinking_from_text(text)
                thinking = parsed_thinking.thinking
                text = parsed_thinking.remaining_text

            if thinking:
                content_blocks.append(
                    ThinkingBlock(type="thinking", thinking=thinking),
                )

            # Tool calls
            backend_tool_calls = message.get("tool_calls") or []

            # Fallback: if backend didn't return structured tool_calls but
            # the text contains <tool_call> tags, parse them from text.
            if (
                not backend_tool_calls
                and text
                and text_contains_tool_call_tag(text)
            ):
                parsed = parse_tool_calls_from_text(text)
                clean_text = parsed.text_before
                if parsed.text_after:
                    clean_text = (
                        f"{clean_text}\n{parsed.text_after}".strip()
                        if clean_text
                        else parsed.text_after
                    )
                if clean_text:
                    content_blocks.append(
                        TextBlock(type="text", text=clean_text),
                    )
                    if structured_model:
                        metadata = _json_loads_safe(clean_text)
                for tc in parsed.tool_calls:
                    content_blocks.append(
                        ToolUseBlock(
                            type="tool_use",
                            id=tc.id,
                            name=tc.name,
                            input=tc.arguments,
                            raw_input=tc.raw_arguments,
                        ),
                    )
            else:
                if text:
                    content_blocks.append(
                        TextBlock(type="text", text=text),
                    )
                    if structured_model:
                        metadata = _json_loads_safe(text)
                for tc in backend_tool_calls:
                    func = tc.get("function", {})
                    content_blocks.append(
                        ToolUseBlock(
                            type="tool_use",
                            id=tc.get("id", ""),
                            name=func.get("name", ""),
                            input=_json_loads_safe(
                                func.get("arguments", "{}"),
                            ),
                            raw_input=func.get("arguments", ""),
                        ),
                    )

        usage_raw = response.get("usage")
        elapsed = (datetime.now() - start_datetime).total_seconds()
        usage = (
            ChatUsage(
                input_tokens=usage_raw.get("prompt_tokens", 0),
                output_tokens=usage_raw.get("completion_tokens", 0),
                time=elapsed,
            )
            if usage_raw
            else None
        )

        return ChatResponse(
            content=content_blocks,
            usage=usage,
            metadata=metadata,
        )
