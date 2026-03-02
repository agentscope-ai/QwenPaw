# -*- coding: utf-8 -*-
"""OpenAI-compatible model using Responses API with chat fallback."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, AsyncGenerator, Literal, Type

from pydantic import BaseModel

from agentscope.message import TextBlock, ToolUseBlock
from agentscope.model import ChatModelBase, ChatResponse
from agentscope.model._model_usage import ChatUsage


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _to_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value)
    return ""


class OpenAIResponsesChatModel(ChatModelBase):
    """Chat model that calls `client.responses.create` first."""

    def __init__(
        self,
        model_name: str,
        api_key: str | None = None,
        stream: bool = True,
        reasoning_effort: Literal["low", "medium", "high"] | None = None,
        organization: str | None = None,
        client_type: Literal["openai", "azure"] = "openai",
        client_kwargs: dict[str, Any] | None = None,
        generate_kwargs: dict[str, Any] | None = None,
        **_: Any,
    ) -> None:
        super().__init__(model_name, stream)

        import openai

        if client_type == "azure":
            self.client = openai.AsyncAzureOpenAI(
                api_key=api_key,
                organization=organization,
                **(client_kwargs or {}),
            )
        else:
            self.client = openai.AsyncClient(
                api_key=api_key,
                organization=organization,
                **(client_kwargs or {}),
            )

        self.reasoning_effort = reasoning_effort
        self.generate_kwargs = generate_kwargs or {}

    async def __call__(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        tool_choice: Literal["auto", "none", "required"] | str | None = None,
        structured_model: Type[BaseModel] | None = None,
        **kwargs: Any,
    ) -> ChatResponse | AsyncGenerator[ChatResponse, None]:
        if not isinstance(messages, list):
            raise ValueError(
                "Responses `messages` field expected type `list`, "
                f"got `{type(messages)}` instead.",
            )

        try:
            response = await self._call_responses(
                messages,
                tools,
                tool_choice,
                structured_model,
                **kwargs,
            )
        except Exception:
            response = await self._call_chat_completions(
                messages,
                tools,
                tool_choice,
                **kwargs,
            )

        if not self.stream:
            return response

        async def _single_chunk() -> AsyncGenerator[ChatResponse, None]:
            yield response

        return _single_chunk()

    async def _call_responses(
        self,
        messages: list[dict],
        tools: list[dict] | None,
        tool_choice: Literal["auto", "none", "required"] | str | None,
        structured_model: Type[BaseModel] | None,
        **kwargs: Any,
    ) -> ChatResponse:
        req: dict[str, Any] = {
            "model": self.model_name,
            "input": self._messages_to_input(messages),
            "stream": False,
            **self.generate_kwargs,
            **kwargs,
        }

        if self.reasoning_effort and "reasoning" not in req:
            req["reasoning"] = {"effort": self.reasoning_effort}

        if tools:
            req["tools"] = tools

        if tool_choice:
            self._validate_tool_choice(tool_choice, tools)
            req["tool_choice"] = self._format_responses_tool_choice(
                tool_choice,
            )

        if structured_model:
            req["text"] = {"format": structured_model.model_json_schema()}

        started = datetime.now()
        raw = await self.client.responses.create(**req)
        return self._parse_responses(started, raw)

    async def _call_chat_completions(
        self,
        messages: list[dict],
        tools: list[dict] | None,
        tool_choice: Literal["auto", "none", "required"] | str | None,
        **kwargs: Any,
    ) -> ChatResponse:
        payload: dict[str, Any] = {
            "model": self.model_name,
            "messages": self._messages_to_chat(messages),
            "stream": False,
            **self.generate_kwargs,
            **kwargs,
        }

        if tools:
            payload["tools"] = tools

        if tool_choice:
            self._validate_tool_choice(tool_choice, tools)
            payload["tool_choice"] = self._format_chat_tool_choice(tool_choice)

        started = datetime.now()
        raw = await self.client.chat.completions.create(**payload)

        blocks: list[TextBlock | ToolUseBlock] = []
        choices = _get(raw, "choices", []) or []
        if choices:
            message = _get(choices[0], "message", {})
            text = _to_text(_get(message, "content", ""))
            if text:
                blocks.append(TextBlock(type="text", text=text))

            for tool_call in _get(message, "tool_calls", []) or []:
                function = _get(tool_call, "function", {})
                raw_args = _to_text(_get(function, "arguments", "{}")) or "{}"
                try:
                    parsed_args = json.loads(raw_args)
                except json.JSONDecodeError:
                    parsed_args = {}
                blocks.append(
                    ToolUseBlock(
                        type="tool_use",
                        id=_to_text(_get(tool_call, "id", "tool_call"))
                        or "tool_call",
                        name=_to_text(_get(function, "name", "tool")) or "tool",
                        input=parsed_args,
                        raw_input=raw_args,
                    ),
                )

        if not blocks:
            blocks.append(TextBlock(type="text", text=""))

        usage_obj = _get(raw, "usage")
        usage = None
        if usage_obj is not None:
            usage = ChatUsage(
                input_tokens=int(_get(usage_obj, "prompt_tokens", 0) or 0),
                output_tokens=int(_get(usage_obj, "completion_tokens", 0) or 0),
                time=(datetime.now() - started).total_seconds(),
                metadata=usage_obj,
            )

        return ChatResponse(content=blocks, usage=usage)

    def _messages_to_input(self, messages: list[dict]) -> list[dict]:
        out: list[dict] = []
        for msg in messages:
            role = _to_text(_get(msg, "role", "user")) or "user"
            if role not in {"system", "user", "assistant", "developer"}:
                role = "user"
            out.append(
                {
                    "role": role,
                    "content": self._extract_text(_get(msg, "content", "")),
                },
            )
        return out

    def _messages_to_chat(self, messages: list[dict]) -> list[dict]:
        out: list[dict] = []
        for msg in messages:
            role = _to_text(_get(msg, "role", "user")) or "user"
            if role not in {"system", "user", "assistant", "tool"}:
                role = "user"
            out.append(
                {
                    "role": role,
                    "content": self._extract_text(_get(msg, "content", "")),
                },
            )
        return out

    def _extract_text(self, content: Any) -> str:
        if isinstance(content, str):
            return content

        if isinstance(content, list):
            chunks: list[str] = []
            for block in content:
                if isinstance(block, str):
                    chunks.append(block)
                    continue
                btype = _to_text(_get(block, "type", ""))
                if btype in {"text", "input_text", "output_text"}:
                    chunks.append(_to_text(_get(block, "text", "")))
                elif btype == "tool_result":
                    chunks.append(_to_text(_get(block, "output", "")))
            return "\n".join([x for x in chunks if x])

        if isinstance(content, dict):
            return _to_text(_get(content, "text", ""))

        return _to_text(content)

    def _parse_responses(
        self,
        started: datetime,
        response: Any,
    ) -> ChatResponse:
        blocks: list[TextBlock | ToolUseBlock] = []

        text = _to_text(_get(response, "output_text", ""))
        for item in _get(response, "output", []) or []:
            item_type = _to_text(_get(item, "type", ""))
            if item_type == "message":
                for block in _get(item, "content", []) or []:
                    btype = _to_text(_get(block, "type", ""))
                    if btype in {"output_text", "text", "input_text"}:
                        t = _to_text(_get(block, "text", ""))
                        if t:
                            text = f"{text}\n{t}" if text else t
            elif item_type in {"function_call", "tool_call"}:
                raw_args = _to_text(_get(item, "arguments", "{}")) or "{}"
                try:
                    parsed_args = json.loads(raw_args)
                except json.JSONDecodeError:
                    parsed_args = {}
                blocks.append(
                    ToolUseBlock(
                        type="tool_use",
                        id=_to_text(_get(item, "call_id", ""))
                        or _to_text(_get(item, "id", "tool_call")),
                        name=_to_text(_get(item, "name", "tool")) or "tool",
                        input=parsed_args,
                        raw_input=raw_args,
                    ),
                )

        if text:
            blocks.insert(0, TextBlock(type="text", text=text))

        if not blocks:
            blocks.append(TextBlock(type="text", text=""))

        usage_obj = _get(response, "usage")
        usage = None
        if usage_obj is not None:
            usage = ChatUsage(
                input_tokens=int(_get(usage_obj, "input_tokens", 0) or 0),
                output_tokens=int(_get(usage_obj, "output_tokens", 0) or 0),
                time=(datetime.now() - started).total_seconds(),
                metadata=usage_obj,
            )

        return ChatResponse(content=blocks, usage=usage)

    def _format_responses_tool_choice(
        self,
        tool_choice: Literal["auto", "none", "required"] | str,
    ) -> str | dict:
        if tool_choice in {"auto", "none", "required"}:
            return tool_choice
        return {"type": "function", "name": tool_choice}

    def _format_chat_tool_choice(
        self,
        tool_choice: Literal["auto", "none", "required"] | str,
    ) -> str | dict:
        if tool_choice in {"auto", "none", "required"}:
            return tool_choice
        return {"type": "function", "function": {"name": tool_choice}}
