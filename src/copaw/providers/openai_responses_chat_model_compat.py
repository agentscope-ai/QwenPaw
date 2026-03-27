# -*- coding: utf-8 -*-
"""OpenAI Responses API compatibility wrapper."""

from __future__ import annotations

import json
from datetime import datetime
from types import SimpleNamespace
from typing import Any, AsyncGenerator, Type

from agentscope.message import TextBlock, ThinkingBlock, ToolUseBlock
from agentscope.model import OpenAIChatModel
from agentscope.model._model_response import ChatResponse
from agentscope.model._model_usage import ChatUsage
from pydantic import BaseModel


def _safe_json_loads(raw: str) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        loaded = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


class OpenAIResponsesChatModelCompat(OpenAIChatModel):
    """OpenAIChatModel variant that sends requests through Responses API.

    This is primarily used for endpoints such as GitHub Copilot where newer
    models are exposed on `/responses` but not on `/chat/completions`.
    """

    _SUPPORTED_STRING_FORMATS = {
        "date-time",
        "time",
        "date",
        "duration",
        "email",
        "hostname",
        "ipv4",
        "ipv6",
        "uuid",
    }

    _STRIP_SCHEMA_KEYS = {
        "default",
        "title",
        "examples",
        "example",
        "deprecated",
        "readOnly",
        "writeOnly",
    }

    async def __call__(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        tool_choice: str | None = None,
        structured_model: Type[BaseModel] | None = None,
        **kwargs: Any,
    ) -> ChatResponse | AsyncGenerator[ChatResponse, None]:
        if not isinstance(messages, list):
            raise ValueError(
                "OpenAI `messages` field expected type `list`, "
                f"got `{type(messages)}` instead.",
            )
        if not all("role" in msg and "content" in msg for msg in messages):
            raise ValueError(
                "Each message in the 'messages' list must contain a 'role' "
                "and 'content' key for OpenAI API.",
            )
        if structured_model is not None:
            raise NotImplementedError(
                "Responses API structured output is not implemented for this model",
            )

        params = self._build_responses_params(
            messages=messages,
            tools=tools,
            tool_choice=tool_choice,
            kwargs=kwargs,
        )

        start_datetime = datetime.now()
        if self.stream:
            params["stream"] = True
            response = await self.client.responses.create(**params)
            return self._parse_responses_stream_response(
                start_datetime,
                response,
            )

        response = await self.client.responses.create(**params)
        return self._parse_responses_response(start_datetime, response)

    def _build_responses_params(
        self,
        messages: list[dict],
        tools: list[dict] | None,
        tool_choice: str | None,
        kwargs: dict[str, Any],
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "model": self.model_name,
            "input": self._convert_messages(messages),
            **self._convert_generate_kwargs(),
            **kwargs,
        }

        if self.reasoning_effort and "reasoning" not in params:
            params["reasoning"] = {"effort": self.reasoning_effort}

        if tools:
            params["tools"] = self._format_responses_tools(tools)

        if tool_choice:
            if tool_choice == "any":
                tool_choice = "required"
            self._validate_tool_choice(tool_choice, tools)
            params["tool_choice"] = self._format_responses_tool_choice(
                tool_choice,
            )

        params.pop("messages", None)
        params.pop("stream", None)
        params.pop("stream_options", None)
        return params

    def _convert_generate_kwargs(self) -> dict[str, Any]:
        params: dict[str, Any] = {}
        for key, value in self.generate_kwargs.items():
            if key == "max_tokens":
                params["max_output_tokens"] = value
                continue
            if key == "response_format":
                continue
            params[key] = value
        return params

    @staticmethod
    def _format_responses_tool_choice(tool_choice: str) -> Any:
        if tool_choice in {"auto", "none", "required"}:
            return tool_choice
        return {
            "type": "function",
            "name": tool_choice,
        }

    @staticmethod
    def _format_responses_tools(
        tools: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        formatted: list[dict[str, Any]] = []
        for tool in tools:
            if not isinstance(tool, dict):
                continue

            tool_type = tool.get("type")
            if tool_type != "function":
                formatted.append(tool)
                continue

            function_spec = tool.get("function")
            if not isinstance(function_spec, dict):
                formatted.append(tool)
                continue

            formatted.append(
                {
                    "type": "function",
                    "name": str(function_spec.get("name") or ""),
                    "description": function_spec.get("description"),
                    "parameters": OpenAIResponsesChatModelCompat._normalize_responses_schema(
                        function_spec.get("parameters") or {},
                    ),
                    "strict": bool(function_spec.get("strict", True)),
                },
            )

        return formatted

    @staticmethod
    def _normalize_responses_schema(schema: Any) -> Any:
        if isinstance(schema, list):
            return [
                OpenAIResponsesChatModelCompat._normalize_responses_schema(
                    item
                )
                for item in schema
            ]

        if not isinstance(schema, dict):
            return schema

        original_required = {
            str(item)
            for item in schema.get("required", [])
            if isinstance(item, str)
        }
        original_properties = schema.get("properties")
        if not isinstance(original_properties, dict):
            original_properties = {}

        normalized: dict[str, Any] = {}
        for key, value in schema.items():
            if key in OpenAIResponsesChatModelCompat._STRIP_SCHEMA_KEYS:
                continue

            if key == "format":
                if (
                    isinstance(value, str)
                    and value
                    in OpenAIResponsesChatModelCompat._SUPPORTED_STRING_FORMATS
                ):
                    normalized[key] = value
                continue

            if key in {
                "properties",
                "$defs",
                "definitions",
            } and isinstance(value, dict):
                normalized[key] = {
                    str(
                        child_key
                    ): OpenAIResponsesChatModelCompat._normalize_responses_schema(
                        child_value,
                    )
                    for child_key, child_value in value.items()
                }
                continue

            if key in {"items", "contains", "additionalProperties"}:
                normalized[
                    key
                ] = OpenAIResponsesChatModelCompat._normalize_responses_schema(
                    value
                )
                continue

            if key in {"prefixItems", "anyOf", "oneOf"} and isinstance(
                value, list
            ):
                normalized[key] = [
                    OpenAIResponsesChatModelCompat._normalize_responses_schema(
                        item
                    )
                    for item in value
                ]
                continue

            if key in {
                "allOf",
                "not",
                "dependentRequired",
                "dependentSchemas",
                "if",
                "then",
                "else",
                "patternProperties",
                "propertyNames",
            }:
                continue

            normalized[key] = value

        schema_type = normalized.get("type")
        has_object_shape = (
            schema_type == "object" or "properties" in normalized
        )
        if has_object_shape:
            properties = normalized.get("properties")
            if isinstance(properties, dict):
                ordered_property_names = list(properties.keys())
                for property_name in ordered_property_names:
                    property_schema = properties[property_name]
                    if property_name not in original_required:
                        original_property_schema = original_properties.get(
                            property_name
                        )
                        if OpenAIResponsesChatModelCompat._should_make_optional_nullable(
                            original_property_schema,
                        ):
                            properties[
                                property_name
                            ] = OpenAIResponsesChatModelCompat._make_optional_schema_nullable(
                                property_schema,
                            )
                normalized["required"] = ordered_property_names
            elif "required" not in normalized:
                normalized["required"] = []

            normalized["additionalProperties"] = False

        return normalized

    @staticmethod
    def _make_optional_schema_nullable(schema: Any) -> Any:
        if not isinstance(schema, dict):
            return {"anyOf": [schema, {"type": "null"}]}

        schema_type = schema.get("type")
        if schema_type == "null":
            return schema

        if isinstance(schema_type, list):
            if "null" in schema_type:
                return schema
            return {
                **schema,
                "type": [*schema_type, "null"],
            }

        any_of = schema.get("anyOf")
        if isinstance(any_of, list):
            if any(
                isinstance(item, dict) and item.get("type") == "null"
                for item in any_of
            ):
                return schema
            return {
                **schema,
                "anyOf": [*any_of, {"type": "null"}],
            }

        one_of = schema.get("oneOf")
        if isinstance(one_of, list):
            if any(
                isinstance(item, dict) and item.get("type") == "null"
                for item in one_of
            ):
                return schema
            return {
                **schema,
                "anyOf": [schema, {"type": "null"}],
            }

        if isinstance(schema_type, str):
            return {
                **schema,
                "type": [schema_type, "null"],
            }

        return {
            "anyOf": [schema, {"type": "null"}],
        }

    @staticmethod
    def _should_make_optional_nullable(schema: Any) -> bool:
        if not isinstance(schema, dict):
            return True

        if "default" in schema and schema.get("default") is not None:
            return False

        schema_type = schema.get("type")
        if schema_type == "null":
            return True

        if isinstance(schema_type, list) and "null" in schema_type:
            return True

        for key in ("anyOf", "oneOf"):
            variants = schema.get(key)
            if isinstance(variants, list) and any(
                isinstance(item, dict) and item.get("type") == "null"
                for item in variants
            ):
                return True

        return "default" not in schema

    def _convert_messages(self, messages: list[dict]) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for index, message in enumerate(messages):
            role = str(message.get("role") or "user")
            content = message.get("content")
            blocks = self._coerce_blocks(content)

            if role == "assistant":
                assistant_message = self._build_assistant_message(blocks)
                if assistant_message is not None:
                    items.append(assistant_message)
                items.extend(
                    self._convert_tool_related_items(
                        role=role,
                        blocks=blocks,
                        index=index,
                    ),
                )
                continue

            items.extend(
                self._convert_tool_related_items(
                    role=role,
                    blocks=blocks,
                    index=index,
                ),
            )

            normalized_role = (
                role if role in {"user", "system", "developer"} else "user"
            )
            message_content = self._build_input_message_content(
                content, blocks
            )
            if message_content:
                items.append(
                    {
                        "type": "message",
                        "role": normalized_role,
                        "content": message_content,
                    },
                )
        return items

    @staticmethod
    def _coerce_blocks(content: Any) -> list[dict[str, Any]]:
        if isinstance(content, str):
            return [{"type": "text", "text": content}]
        if isinstance(content, list):
            return [block for block in content if isinstance(block, dict)]
        return []

    def _convert_tool_related_items(
        self,
        role: str,
        blocks: list[dict[str, Any]],
        index: int,
    ) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []

        for block_index, block in enumerate(blocks):
            block_type = block.get("type")
            if block_type == "tool_use":
                call_id = str(
                    block.get("id") or f"tool-call-{index}-{block_index}"
                )
                raw_input = block.get("raw_input")
                if not isinstance(raw_input, str) or not raw_input:
                    raw_input = json.dumps(
                        block.get("input") or {}, ensure_ascii=False
                    )
                items.append(
                    {
                        "type": "function_call",
                        "call_id": call_id,
                        "name": str(block.get("name") or ""),
                        "arguments": raw_input,
                    },
                )
                continue

            if block_type == "tool_result":
                call_id = str(
                    block.get("id") or f"tool-result-{index}-{block_index}"
                )
                items.append(
                    {
                        "type": "function_call_output",
                        "call_id": call_id,
                        "output": self._stringify_tool_output(
                            block.get("output")
                        ),
                    },
                )

        if role == "tool" and not items:
            return items

        return items

    @staticmethod
    def _stringify_tool_output(output: Any) -> str:
        if isinstance(output, str):
            return output
        if isinstance(output, list):
            texts: list[str] = []
            for item in output:
                if isinstance(item, dict) and item.get("type") == "text":
                    text = item.get("text")
                    if isinstance(text, str) and text:
                        texts.append(text)
            if texts:
                return "\n".join(texts)
        try:
            return json.dumps(output, ensure_ascii=False)
        except (TypeError, ValueError):
            return str(output)

    def _build_assistant_message(
        self,
        blocks: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        content_parts: list[str] = []
        for block in blocks:
            block_type = block.get("type")
            if block_type == "text":
                text = block.get("text")
                if isinstance(text, str) and text:
                    content_parts.append(text)
                    continue
            if block_type == "thinking":
                thinking = block.get("thinking")
                if isinstance(thinking, str) and thinking:
                    content_parts.append(thinking)

        if not content_parts:
            return None

        return {
            "type": "message",
            "role": "assistant",
            "content": "\n\n".join(content_parts),
        }

    def _build_input_message_content(
        self,
        content: Any,
        blocks: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if isinstance(content, str):
            return [{"type": "input_text", "text": content}]

        converted: list[dict[str, Any]] = []
        for block in blocks:
            block_type = block.get("type")
            if block_type in {"text", "input_text"}:
                text = block.get("text")
                if isinstance(text, str) and text:
                    converted.append({"type": "input_text", "text": text})
                continue
            if block_type in {"image_url", "input_image"}:
                image_url = block.get("image_url")
                detail = block.get("detail") or "auto"
                if isinstance(image_url, dict):
                    image_url = image_url.get("url")
                if isinstance(image_url, str) and image_url:
                    converted.append(
                        {
                            "type": "input_image",
                            "image_url": image_url,
                            "detail": detail,
                        },
                    )
        return converted

    async def _parse_responses_stream_response(
        self,
        start_datetime: datetime,
        response: Any,
    ) -> AsyncGenerator[ChatResponse, None]:
        items_by_id: dict[str, dict[str, Any]] = {}
        items_by_index: dict[int, str] = {}

        async for event in response:
            event_type = getattr(event, "type", "")

            if event_type == "response.output_item.added":
                item = getattr(event, "item", None)
                if item is None:
                    continue
                self._merge_stream_item(
                    items_by_id=items_by_id,
                    items_by_index=items_by_index,
                    item=item,
                    output_index=int(getattr(event, "output_index", 0) or 0),
                )
                content = self._build_stream_content(
                    items_by_index, items_by_id
                )
                if content:
                    yield ChatResponse(content=content)
                continue

            if event_type in {
                "response.output_text.delta",
                "response.refusal.delta",
            }:
                item_id = str(getattr(event, "item_id", "") or "")
                if item_id:
                    state = items_by_id.setdefault(
                        item_id,
                        self._new_stream_item_state(
                            item_type="message",
                            order=int(getattr(event, "output_index", 0) or 0),
                        ),
                    )
                    state["text"] += str(getattr(event, "delta", "") or "")
                    content = self._build_stream_content(
                        items_by_index, items_by_id
                    )
                    if content:
                        yield ChatResponse(content=content)
                continue

            if event_type in {
                "response.reasoning_text.delta",
                "response.reasoning_summary_text.delta",
            }:
                item_id = str(getattr(event, "item_id", "") or "")
                if item_id:
                    state = items_by_id.setdefault(
                        item_id,
                        self._new_stream_item_state(
                            item_type="reasoning",
                            order=int(getattr(event, "output_index", 0) or 0),
                        ),
                    )
                    state["reasoning"] += str(
                        getattr(event, "delta", "") or ""
                    )
                    content = self._build_stream_content(
                        items_by_index, items_by_id
                    )
                    if content:
                        yield ChatResponse(content=content)
                continue

            if event_type == "response.function_call_arguments.delta":
                item_id = str(getattr(event, "item_id", "") or "")
                if item_id:
                    state = items_by_id.setdefault(
                        item_id,
                        self._new_stream_item_state(
                            item_type="function_call",
                            order=int(getattr(event, "output_index", 0) or 0),
                        ),
                    )
                    state["arguments"] += str(
                        getattr(event, "delta", "") or ""
                    )
                    content = self._build_stream_content(
                        items_by_index, items_by_id
                    )
                    if content:
                        yield ChatResponse(content=content)
                continue

            if event_type == "response.function_call_arguments.done":
                item_id = str(getattr(event, "item_id", "") or "")
                if item_id:
                    state = items_by_id.setdefault(
                        item_id,
                        self._new_stream_item_state(
                            item_type="function_call",
                            order=int(getattr(event, "output_index", 0) or 0),
                        ),
                    )
                    state["name"] = str(
                        getattr(event, "name", "") or state["name"]
                    )
                    state["arguments"] = str(
                        getattr(event, "arguments", "") or state["arguments"],
                    )
                    content = self._build_stream_content(
                        items_by_index,
                        items_by_id,
                        finalize_tools=True,
                    )
                    if content:
                        yield ChatResponse(content=content)
                continue

            if event_type == "response.output_item.done":
                item = getattr(event, "item", None)
                if item is not None:
                    self._merge_stream_item(
                        items_by_id=items_by_id,
                        items_by_index=items_by_index,
                        item=item,
                        output_index=int(
                            getattr(event, "output_index", 0) or 0
                        ),
                    )
                continue

            if event_type == "response.completed":
                final_response = getattr(event, "response", None)
                if final_response is not None:
                    yield self._parse_responses_response(
                        start_datetime,
                        final_response,
                    )
                continue

            if event_type in {
                "response.failed",
                "response.error",
                "response.incomplete",
            }:
                message = getattr(event, "message", None)
                if not message:
                    error = getattr(event, "error", None)
                    message = getattr(error, "message", None) or str(
                        error or event_type
                    )
                raise RuntimeError(str(message))

    def _parse_responses_response(
        self,
        start_datetime: datetime,
        response: Any,
    ) -> ChatResponse:
        content_blocks: list[TextBlock | ThinkingBlock | ToolUseBlock] = []

        for item in getattr(response, "output", []) or []:
            item_type = getattr(item, "type", "")

            if item_type == "reasoning":
                reasoning_text = self._extract_reasoning_text(item)
                if reasoning_text:
                    content_blocks.append(
                        ThinkingBlock(
                            type="thinking",
                            thinking=reasoning_text,
                        ),
                    )
                continue

            if item_type == "message":
                for block in getattr(item, "content", []) or []:
                    block_type = getattr(block, "type", "")
                    if block_type == "output_text":
                        text = getattr(block, "text", "")
                    elif block_type == "refusal":
                        text = getattr(block, "refusal", "")
                    else:
                        text = ""
                    if text:
                        content_blocks.append(
                            TextBlock(
                                type="text",
                                text=text,
                            ),
                        )
                continue

            if item_type == "function_call":
                raw_input = getattr(item, "arguments", "") or ""
                content_blocks.append(
                    ToolUseBlock(
                        type="tool_use",
                        id=str(
                            getattr(item, "call_id", "")
                            or getattr(item, "id", "")
                        ),
                        name=str(getattr(item, "name", "") or ""),
                        input=_safe_json_loads(raw_input),
                        raw_input=raw_input,
                    ),
                )

        usage_data = getattr(response, "usage", None)
        usage = None
        if usage_data is not None:
            usage = ChatUsage(
                input_tokens=int(getattr(usage_data, "input_tokens", 0) or 0),
                output_tokens=int(
                    getattr(usage_data, "output_tokens", 0) or 0
                ),
                time=(datetime.now() - start_datetime).total_seconds(),
                metadata=usage_data,
            )

        return ChatResponse(
            content=content_blocks,
            usage=usage,
        )

    def _build_stream_content(
        self,
        items_by_index: dict[int, str],
        items_by_id: dict[str, dict[str, Any]],
        finalize_tools: bool = False,
    ) -> list[TextBlock | ThinkingBlock | ToolUseBlock]:
        content_blocks: list[TextBlock | ThinkingBlock | ToolUseBlock] = []

        for output_index in sorted(items_by_index):
            item_id = items_by_index[output_index]
            state = items_by_id.get(item_id)
            if not state:
                continue

            item_type = state["type"]
            if item_type == "reasoning" and state["reasoning"]:
                content_blocks.append(
                    ThinkingBlock(
                        type="thinking",
                        thinking=state["reasoning"],
                    ),
                )
                continue

            if item_type == "message" and state["text"]:
                content_blocks.append(
                    TextBlock(
                        type="text",
                        text=state["text"],
                    ),
                )
                continue

            if item_type == "function_call":
                raw_input = state["arguments"]
                input_obj = (
                    _safe_json_loads(raw_input)
                    if finalize_tools or self.stream_tool_parsing
                    else {}
                )
                content_blocks.append(
                    ToolUseBlock(
                        type="tool_use",
                        id=state["call_id"],
                        name=state["name"],
                        input=input_obj,
                        raw_input=raw_input,
                    ),
                )

        return content_blocks

    def _merge_stream_item(
        self,
        items_by_id: dict[str, dict[str, Any]],
        items_by_index: dict[int, str],
        item: Any,
        output_index: int,
    ) -> None:
        item_type = getattr(item, "type", "")
        if item_type == "function_call":
            item_id = str(
                getattr(item, "id", "")
                or getattr(item, "call_id", "")
                or f"function-{output_index}"
            )
            state = items_by_id.setdefault(
                item_id,
                self._new_stream_item_state(
                    item_type="function_call",
                    order=output_index,
                ),
            )
            state["call_id"] = str(
                getattr(item, "call_id", "") or state["call_id"] or item_id
            )
            state["name"] = str(getattr(item, "name", "") or state["name"])
            state["arguments"] = str(
                getattr(item, "arguments", "") or state["arguments"]
            )
            items_by_index[output_index] = item_id
            return

        if item_type == "message":
            item_id = str(getattr(item, "id", "") or f"message-{output_index}")
            state = items_by_id.setdefault(
                item_id,
                self._new_stream_item_state(
                    item_type="message",
                    order=output_index,
                ),
            )
            text_parts: list[str] = []
            for block in getattr(item, "content", []) or []:
                block_type = getattr(block, "type", "")
                if block_type == "output_text":
                    text = getattr(block, "text", "")
                elif block_type == "refusal":
                    text = getattr(block, "refusal", "")
                else:
                    text = ""
                if text:
                    text_parts.append(text)
            if text_parts:
                state["text"] = "".join(text_parts)
            items_by_index[output_index] = item_id
            return

        if item_type == "reasoning":
            item_id = str(
                getattr(item, "id", "") or f"reasoning-{output_index}"
            )
            state = items_by_id.setdefault(
                item_id,
                self._new_stream_item_state(
                    item_type="reasoning",
                    order=output_index,
                ),
            )
            reasoning_text = self._extract_reasoning_text(item)
            if reasoning_text:
                state["reasoning"] = reasoning_text
            items_by_index[output_index] = item_id

    @staticmethod
    def _new_stream_item_state(
        item_type: str,
        order: int,
    ) -> dict[str, Any]:
        return {
            "type": item_type,
            "order": order,
            "text": "",
            "reasoning": "",
            "call_id": "",
            "name": "",
            "arguments": "",
        }

    @staticmethod
    def _extract_reasoning_text(item: Any) -> str:
        pieces: list[str] = []
        for summary in getattr(item, "summary", []) or []:
            text = getattr(summary, "text", "")
            if isinstance(text, str) and text:
                pieces.append(text)
        if pieces:
            return "\n".join(pieces)

        for content in getattr(item, "content", []) or []:
            text = getattr(content, "text", "")
            if isinstance(text, str) and text:
                pieces.append(text)
        return "\n".join(pieces)
