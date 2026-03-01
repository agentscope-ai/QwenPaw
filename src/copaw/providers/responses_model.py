# -*- coding: utf-8 -*-
"""OpenAI Responses API adapter model.

This model keeps AgentScope's ChatModelBase contract but sends requests to
`responses.create` first. If the upstream endpoint does not support
Responses API, it falls back to the original `chat.completions` path.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, AsyncGenerator, Literal, Type

from pydantic import BaseModel

from agentscope.message import AudioBlock, Base64Source, TextBlock, ThinkingBlock, ToolUseBlock
from agentscope.model import ChatResponse, OpenAIChatModel
from agentscope.model._model_usage import ChatUsage


def _as_dict(obj: Any) -> dict[str, Any]:
    if isinstance(obj, dict):
        return obj
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    if hasattr(obj, "dict"):
        return obj.dict()
    return {}


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _safe_json_loads(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str):
        return {}
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}


class OpenAIResponsesChatModel(OpenAIChatModel):
    """Adapter for providers that only support OpenAI Responses API."""

    async def __call__(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        tool_choice: Literal["auto", "none", "required"] | str | None = None,
        structured_model: Type[BaseModel] | None = None,
        **kwargs: Any,
    ) -> ChatResponse | AsyncGenerator[ChatResponse, None]:
        # Keep structured output on chat.completions.parse for compatibility.
        if structured_model is not None:
            return await super().__call__(
                messages,
                tools=tools,
                tool_choice=tool_choice,
                structured_model=structured_model,
                **kwargs,
            )

        # Runtime request metadata (session/channel) can be threaded through
        # agent layers via kwargs. Strip non-Responses keys so they do not
        # override the converted `input` payload or provider model name.
        extra_kwargs = dict(kwargs)
        for key in (
            "input",
            "session_id",
            "user_id",
            "channel",
            "structured_model",
            "tools",
            "tool_choice",
        ):
            extra_kwargs.pop(key, None)
        if extra_kwargs.get("model") is None:
            extra_kwargs.pop("model", None)

        request_kwargs = {
            "model": self.model_name,
            "input": self._format_messages_for_responses(messages),
            **self.generate_kwargs,
            **extra_kwargs,
        }

        if self.reasoning_effort and "reasoning" not in request_kwargs:
            request_kwargs["reasoning"] = {"effort": self.reasoning_effort}

        if tools:
            request_kwargs["tools"] = self._format_tools_for_responses(
                self._format_tools_json_schemas(tools),
            )

        if tool_choice:
            if tool_choice == "any":
                tool_choice = "required"
            self._validate_tool_choice(tool_choice, tools)
            request_kwargs["tool_choice"] = self._format_responses_tool_choice(
                tool_choice,
            )

        start_datetime = datetime.now()

        try:
            response = await self.client.responses.create(**request_kwargs)
            parsed = self._parse_responses_response(start_datetime, response)
            if self.stream:
                return self._stream_single_response(parsed)
            return parsed
        except Exception as exc:  # pragma: no cover - provider-dependent
            if self._should_fallback_to_chat_completions(exc):
                return await super().__call__(
                    messages,
                    tools=tools,
                    tool_choice=tool_choice,
                    structured_model=structured_model,
                    **kwargs,
                )
            raise

    @staticmethod
    def _format_responses_tool_choice(
        tool_choice: Literal["auto", "none", "required"] | str,
    ) -> str | dict[str, Any]:
        if tool_choice in ("auto", "none", "required"):
            return tool_choice
        return {"type": "function", "name": tool_choice}

    @staticmethod
    def _format_tools_for_responses(tools: list[dict]) -> list[dict]:
        formatted: list[dict] = []
        for tool in tools:
            if not isinstance(tool, dict):
                continue

            if tool.get("type") != "function":
                formatted.append(tool)
                continue

            function = tool.get("function")
            if isinstance(function, dict):
                item: dict[str, Any] = {
                    "type": "function",
                    "name": function.get("name", ""),
                }
                if function.get("description"):
                    item["description"] = function["description"]
                if function.get("parameters") is not None:
                    item["parameters"] = function["parameters"]
                if function.get("strict") is not None:
                    item["strict"] = function["strict"]
                formatted.append(item)
                continue

            # Already in Responses style.
            item = {
                "type": "function",
                "name": tool.get("name", ""),
            }
            if tool.get("description"):
                item["description"] = tool["description"]
            if tool.get("parameters") is not None:
                item["parameters"] = tool["parameters"]
            if tool.get("strict") is not None:
                item["strict"] = tool["strict"]
            formatted.append(item)

        return formatted

    @staticmethod
    def _should_fallback_to_chat_completions(exc: Exception) -> bool:
        status_code = getattr(exc, "status_code", None)
        if status_code in {404, 405, 501}:
            return True

        msg = str(exc).lower()
        markers = [
            "responses",
            "not found",
            "unsupported",
            "unknown endpoint",
            "unknown path",
        ]
        return "responses" in msg and any(token in msg for token in markers)

    @staticmethod
    def _format_messages_for_responses(messages: list[dict]) -> list[dict]:
        formatted: list[dict] = []
        for msg in messages:
            role = msg.get("role")
            content = msg.get("content")

            if role == "tool":
                tool_call_id = msg.get("tool_call_id") or msg.get("id") or ""
                formatted.append(
                    {
                        "type": "function_call_output",
                        "call_id": tool_call_id,
                        "output": content if isinstance(content, str) else json.dumps(content, ensure_ascii=False),
                    },
                )
                continue

            if role == "assistant" and isinstance(msg.get("tool_calls"), list):
                for call in msg["tool_calls"]:
                    if not isinstance(call, dict):
                        continue
                    function = call.get("function")
                    if not isinstance(function, dict):
                        continue
                    call_id = call.get("id") or call.get("call_id") or ""
                    arguments = function.get("arguments", "")
                    formatted.append(
                        {
                            "type": "function_call",
                            "call_id": call_id,
                            "name": function.get("name", ""),
                            "arguments": (
                                arguments
                                if isinstance(arguments, str)
                                else json.dumps(arguments, ensure_ascii=False)
                            ),
                        },
                    )

            new_msg: dict[str, Any] = {
                "role": role,
                "content": OpenAIResponsesChatModel._format_content_blocks(
                    content,
                    role=role,
                ),
            }

            # Responses API does not support `name` on input messages for
            # OpenAI-compatible providers, so only keep role/content.
            if new_msg["content"] in (None, "", []):
                continue

            formatted.append(new_msg)

        return formatted

    @staticmethod
    def _format_content_blocks(content: Any, role: str | None = None) -> Any:
        if isinstance(content, str):
            block_type = "output_text" if role == "assistant" else "input_text"
            return [{"type": block_type, "text": content}]
        if not isinstance(content, list):
            return content

        out: list[dict[str, Any]] = []
        for block in content:
            if isinstance(block, str):
                out.append(
                    {
                        "type": "output_text" if role == "assistant" else "input_text",
                        "text": block,
                    },
                )
                continue

            if not isinstance(block, dict):
                block = _as_dict(block)
            if not isinstance(block, dict):
                continue
            block_type = block.get("type")
            if block_type in {"text", "input_text", "output_text"}:
                normalized_type = (
                    "output_text" if role == "assistant" else "input_text"
                )
                out.append(
                    {
                        "type": normalized_type,
                        "text": block.get("text", ""),
                    },
                )
            elif block_type == "image_url":
                image_url = block.get("image_url", {})
                url = image_url.get("url") if isinstance(image_url, dict) else ""
                out.append({"type": "input_image", "image_url": url})
            elif block_type == "input_audio":
                audio = block.get("input_audio", {})
                out.append(
                    {
                        "type": "input_audio",
                        "input_audio": {
                            "data": audio.get("data", ""),
                            "format": audio.get("format", "wav"),
                        },
                    },
                )
            else:
                out.append(block)

        return out

    @staticmethod
    async def _stream_single_response(
        response: ChatResponse,
    ) -> AsyncGenerator[ChatResponse, None]:
        yield response

    def _parse_responses_response(
        self,
        start_datetime: datetime,
        response: Any,
    ) -> ChatResponse:
        content_blocks: list[TextBlock | ToolUseBlock | ThinkingBlock | AudioBlock] = []

        output_items = _get(response, "output", []) or []
        for item in output_items:
            item_type = _get(item, "type", "")

            if item_type == "message":
                for block in _get(item, "content", []) or []:
                    block_type = _get(block, "type", "")
                    if block_type in {"output_text", "text"}:
                        text = _get(block, "text", "")
                        if text:
                            content_blocks.append(TextBlock(type="text", text=text))
                    elif block_type in {"output_audio", "audio"}:
                        data = _get(block, "data", "")
                        transcript = _get(block, "transcript", "")
                        if data:
                            media_type = self.generate_kwargs.get("audio", {}).get(
                                "format",
                                "wav",
                            )
                            content_blocks.append(
                                AudioBlock(
                                    type="audio",
                                    source=Base64Source(
                                        data=data,
                                        media_type=f"audio/{media_type}",
                                        type="base64",
                                    ),
                                ),
                            )
                        if transcript:
                            content_blocks.append(
                                TextBlock(type="text", text=transcript),
                            )

            elif item_type in {"reasoning", "output_reasoning"}:
                summary = _get(item, "summary", "")
                if isinstance(summary, str) and summary:
                    content_blocks.append(
                        ThinkingBlock(type="thinking", thinking=summary),
                    )
                elif isinstance(summary, list):
                    thinking_text = "\n".join(
                        _get(part, "text", "")
                        for part in summary
                        if _get(part, "text", "")
                    )
                    if thinking_text:
                        content_blocks.append(
                            ThinkingBlock(type="thinking", thinking=thinking_text),
                        )

            elif item_type in {"function_call", "tool_call"}:
                arguments = _get(item, "arguments", "")
                content_blocks.append(
                    ToolUseBlock(
                        type="tool_use",
                        id=_get(item, "call_id", "") or _get(item, "id", ""),
                        name=_get(item, "name", ""),
                        input=_safe_json_loads(arguments),
                        raw_input=arguments if isinstance(arguments, str) else json.dumps(arguments, ensure_ascii=False),
                    ),
                )

        # Fallback to top-level output_text when provider returns compact schema.
        if not any(block.get("type") == "text" for block in content_blocks):
            output_text = _get(response, "output_text", "")
            if output_text:
                content_blocks.append(TextBlock(type="text", text=output_text))

        usage_raw = _get(response, "usage", None)
        usage = None
        if usage_raw:
            usage_raw_dict = _as_dict(usage_raw)
            usage = ChatUsage(
                input_tokens=(
                    usage_raw_dict.get("input_tokens")
                    or usage_raw_dict.get("prompt_tokens")
                    or 0
                ),
                output_tokens=(
                    usage_raw_dict.get("output_tokens")
                    or usage_raw_dict.get("completion_tokens")
                    or 0
                ),
                time=(datetime.now() - start_datetime).total_seconds(),
                metadata=usage_raw,
            )

        return ChatResponse(content=content_blocks, usage=usage)
